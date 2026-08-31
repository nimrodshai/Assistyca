"""Read-only calendar summaries for portal actions.

The portal stores provider credentials encrypted at rest.  This module accepts
the decrypted credential only at the point of execution, calls the Google
Calendar read API, and returns a deterministic summary without sending meeting
contents to a language model.  Keeping the first runner deterministic avoids
unexpected token spend and makes a manual run easy to diagnose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone
import json
import re
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3/calendars"
CALENDAR_LIST_API_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
CALENDAR_MAX_EVENTS = 100
CALENDAR_TIMEOUT_SECONDS = 20
# The picker in the action editor lists what the account can read. An account
# with more calendars than this has long stopped being a list someone reads.
CALENDAR_MAX_LISTED_CALENDARS = 50
# The connected account's own calendar. Google accepts this alias in place of
# the account address, so a saved action keeps working if the address changes.
PRIMARY_CALENDAR_ID = "primary"
# A calendar the account can only see as busy blocks has no titles to summarize,
# so it is never offered as something an action could read.
CALENDAR_READABLE_ACCESS_ROLES = ("reader", "writer", "owner")
# One read per calendar, so the list has to stay short enough that a run does
# not turn into a long chain of provider calls. It also caps what an account can
# choose to have read: choosing more calendars than a run reads would drop the
# rest without saying so.
CALENDAR_MAX_CALENDARS = 8
# A calendar ID is either the connected account's own calendar or the address
# of a calendar shared with it. Nothing else is ever put in the request path.
CALENDAR_ID_PATTERN = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


class CalendarSummaryError(RuntimeError):
    """A safe, user-facing calendar runner error."""

    def __init__(self, message: str, *, code: str = "calendar_summary_failed") -> None:
        super().__init__(message)
        self.code = code


class CalendarAuthorizationError(CalendarSummaryError):
    """The stored credential cannot read calendar events."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="calendar_authorization_failed")


class CalendarListUnavailableError(CalendarSummaryError):
    """The stored credential can read events but cannot list the calendars.

    Connections made before the portal asked for the calendar-list grant land
    here.  They still summarize fine; only the picker needs the reconnect.
    """

    def __init__(self) -> None:
        super().__init__(
            "Reconnect Google Calendar to choose which of its calendars this action reads.",
            code="calendar_list_scope_missing",
        )


class CalendarNotSharedError(CalendarSummaryError):
    """One extra calendar is not readable by the connected account."""

    def __init__(self, calendar_id: str) -> None:
        super().__init__(
            f"I couldn’t read {calendar_id}. Ask them to share their calendar with the connected Google account, then run it again.",
            code="calendar_not_shared",
        )
        self.calendar_id = calendar_id


def normalize_calendar_id(value: Any) -> str:
    """Return a calendar ID that is safe to put in the request path."""

    candidate = str(value or "").strip().strip("<>").lower()
    return candidate if CALENDAR_ID_PATTERN.match(candidate) else "primary"


def _calendar_id_entries(value: Any) -> list[str]:
    """Every calendar named by a field or a saved selection, as safe IDs."""

    if isinstance(value, (list, tuple, set)):
        entries = [str(item) for item in value]
    else:
        entries = re.split(r"[,\n;]+", str(value or ""))
    calendar_ids: list[str] = []
    for entry in entries:
        if not entry.strip():
            continue
        calendar_id = normalize_calendar_id(entry)
        if calendar_id not in calendar_ids:
            calendar_ids.append(calendar_id)
    return calendar_ids[:CALENDAR_MAX_CALENDARS]


def parse_calendar_ids(value: Any) -> list[str]:
    """Turn the saved calendar field into the calendars a run should read.

    The field holds one tag per calendar: the connected account, whatever it is
    labelled, plus any address the user added.  Every tag that is not an address
    means the connected account's own calendar, which Google calls "primary".
    """

    return _calendar_id_entries(value) or ["primary"]


def normalize_selected_calendar_ids(value: Any) -> list[str]:
    """The calendars an account chose to have read, as IDs.

    Unlike ``parse_calendar_ids`` an empty answer stays empty: "nothing has been
    chosen yet" and "only the account's own calendar" are different states, and
    the first is the one that should go and ask.
    """

    return _calendar_id_entries(value)


def calendar_field_names_a_calendar(value: Any) -> bool:
    """True when the saved field picked calendars rather than the connection.

    Every tag that is not an address names the account rather than a calendar
    inside it, which is what "Connected calendar" and every question typed in
    chat amount to.  Those read whatever the account chose; a field that named
    real calendars is a narrower request and is left exactly as it was written.
    """

    if isinstance(value, (list, tuple, set)):
        entries = [str(item) for item in value]
    else:
        entries = re.split(r"[,\n;]+", str(value or ""))
    return any(
        CALENDAR_ID_PATTERN.match(str(entry).strip().strip("<>").lower())
        for entry in entries
        if str(entry).strip()
    )


def resolve_calendar_ids(value: Any, *, account_calendar_ids: Any = None) -> list[str]:
    """Which calendars one run should read, given what the account chose.

    "What is on my calendar" is a question about all of them.  A Google account
    holds several - work, family, a shared one someone added - and reading only
    the account's own calendar answers a question nobody asked.
    """

    if calendar_field_names_a_calendar(value):
        return parse_calendar_ids(value)
    return normalize_selected_calendar_ids(account_calendar_ids) or parse_calendar_ids(value)


@dataclass(frozen=True)
class CalendarDateRange:
    label: str
    start: datetime
    end: datetime
    # True when the words named no period this could place and the week ahead
    # was read instead. The answer says which days it read rather than passing
    # a guess off as the range that was asked for.
    assumed: bool = False

    @property
    def start_date(self) -> date:
        return self.start.date()

    @property
    def end_date(self) -> date:
        # The API end is exclusive, while the user-facing label is inclusive.
        return (self.end - timedelta(days=1)).date()


def _safe_zone(timezone_name: str | None) -> ZoneInfo:
    normalized = str(timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _start_of_day(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, dt_time.min, tzinfo=zone)


# A calendar read is one provider call per calendar per run, so a period that
# names half a year is clamped rather than turned into a long chain of reads.
CALENDAR_MAX_RANGE_DAYS = 92
# What a run reads when the words name no period it can place. A calendar
# question is nearly always about the days just ahead.
CALENDAR_FALLBACK_RANGE_DAYS = 7
# A period nobody writes out in more words than this, and a phrase this reader
# will not spend longer than this looking through for one.
_MAX_SCANNED_WORDS = 16
_MAX_SCANNED_PHRASE_WORDS = 5

_WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tues": 1, "tue": 1,
    "wednesday": 2, "weds": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# People count in words as readily as in digits: "the next couple of days" is
# the same question as "the next 2 days".
_COUNT_WORDS = {
    "a": 1, "an": 1, "one": 1, "couple": 2, "two": 2, "few": 3, "three": 3,
    "several": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "fortnight": 14, "month": 30, "months": 30}


def _alternation(names) -> str:
    # Longest first, so "thursday" is not read as "thu" with letters left over.
    return "|".join(sorted(names, key=len, reverse=True))


_ISO_DATE = r"\d{4}-\d{1,2}-\d{1,2}"
_EXPLICIT_RANGE_RE = re.compile(
    rf"(?P<start>{_ISO_DATE})\s*(?:to|through|thru|until|till|and|[-–—])\s*(?P<end>{_ISO_DATE})",
    re.IGNORECASE,
)
_SINGLE_ISO_RE = re.compile(rf"^(?:{_ISO_DATE})$")
# Words that name a part of a day rather than a day of its own. "Tomorrow
# morning" is a question about tomorrow: which hours of it are free is worked
# out from the gaps between the meetings, so the range only needs the day.
_DAY_PART_RE = re.compile(
    r"\b(?:first thing|early|earliest|latest|late|later|mid)?[ -]?"
    r"(?:mornings?|afternoons?|evenings?|nights?|midday|noon|lunchtimes?|a\.?m\.?|p\.?m\.?)\b"
)
# Words a person puts in front of a period that say nothing about which days it
# covers.
_FILLER_RE = re.compile(
    r"^(?:for|on|in|at|during|over|about|around|of|the|my|our|any|some|sometime|some time|just|please)\b\s*"
)
_WEEKDAY_RE = re.compile(rf"^(?:(this|next|coming|last|past|previous)\s+)?({_alternation(_WEEKDAY_NAMES)})s?$")
_MONTH_ONLY_RE = re.compile(rf"^(?:month of\s+)?({_alternation(_MONTH_NAMES)})\.?(?:\s+(\d{{4}}))?$")
_MONTH_DAY_RE = re.compile(
    rf"^({_alternation(_MONTH_NAMES)})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?$"
)
_DAY_MONTH_RE = re.compile(
    rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_alternation(_MONTH_NAMES)})\.?(?:,?\s+(\d{{4}}))?$"
)
_DAY_ORDINAL_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)$")
_COUNT_UNIT_RE = re.compile(
    rf"^(?:(next|coming|following|upcoming|last|past|previous)\s+)?"
    rf"(?:(\d{{1,3}}|{_alternation(_COUNT_WORDS)})\s+)?(?:of\s+)?"
    rf"({_alternation(_UNIT_DAYS)})$"
)


def _end_of_month(value: date) -> date:
    first_of_next = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_of_next - timedelta(days=1)


def _first_of_next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _clamp_day_of_month(year: int, month: int, day: int) -> date:
    last = _end_of_month(date(year, month, 1)).day
    return date(year, month, min(day, last))


def _normalize_range_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("’", "'")).strip().lower()
    return text.strip(" ?!.,;:")


def _strip_filler(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _FILLER_RE.sub("", text).strip()
    return text


def _read_explicit_range(text: str) -> tuple[date, date] | None:
    match = _EXPLICIT_RANGE_RE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group("start")), date.fromisoformat(match.group("end"))
    except ValueError:
        # A date that reads like one but names no real day is not a range; the
        # rest of the reader gets its turn instead of the run stopping here.
        return None


def _read_named_date(text: str, today: date) -> tuple[date, date] | None:
    """A day named as a date rather than as a distance from today."""

    if _SINGLE_ISO_RE.match(text):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        return day, day

    match = _MONTH_DAY_RE.match(text) or _DAY_MONTH_RE.match(text)
    if match:
        groups = match.groups()
        month_name, day_text = (groups[0], groups[1]) if groups[0] in _MONTH_NAMES else (groups[1], groups[0])
        month = _MONTH_NAMES[month_name]
        day_number = int(day_text)
        year = int(groups[2]) if groups[2] else today.year
        day = _clamp_day_of_month(year, month, day_number)
        if not groups[2] and day < today:
            # A date already gone by, named without a year, is the one coming.
            day = _clamp_day_of_month(year + 1, month, day_number)
        return day, day

    match = _MONTH_ONLY_RE.match(text)
    if match:
        month = _MONTH_NAMES[match.group(1)]
        year = int(match.group(2)) if match.group(2) else today.year
        if not match.group(2) and month < today.month:
            year += 1
        start = date(year, month, 1)
        return start, _end_of_month(start)

    match = _DAY_ORDINAL_RE.match(text)
    if match:
        day_number = int(match.group(1))
        if not 1 <= day_number <= 31:
            return None
        day = _clamp_day_of_month(today.year, today.month, day_number)
        if day < today:
            following = _first_of_next_month(today)
            day = _clamp_day_of_month(following.year, following.month, day_number)
        return day, day
    return None


def _read_calendar_days(text: str, today: date) -> tuple[date, date] | None:
    """Read a period written the way a person says it as the days it covers.

    Returns None when the words name no period this can place, so the caller
    decides what to read instead of this inventing a range nobody asked for.
    """

    monday = today - timedelta(days=today.weekday())
    tomorrow = today + timedelta(days=1)

    if text in {"", "this", "now", "right now", "today", "tonight", "this day", "current day", "rest of today", "rest of the day"}:
        return today, today
    if text in {"tomorrow", "tomorrow's", "next day", "day after today"}:
        return tomorrow, tomorrow
    if text in {"day after tomorrow", "overmorrow"}:
        return today + timedelta(days=2), today + timedelta(days=2)
    if text in {"yesterday", "day before", "day before today", "previous day"}:
        return today - timedelta(days=1), today - timedelta(days=1)
    if text in {"this week", "this calendar week", "current week", "week"}:
        return monday, monday + timedelta(days=6)
    if text in {"rest of the week", "rest of this week", "remainder of the week", "week ahead"}:
        return today, monday + timedelta(days=6)
    if text in {"next week", "next calendar week", "following week"}:
        return monday + timedelta(days=7), monday + timedelta(days=13)
    if text in {"week after next", "week after the next one"}:
        return monday + timedelta(days=14), monday + timedelta(days=20)
    if text in {"last week", "previous week", "week before", "past week"}:
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if text in {"weekend", "this weekend", "coming weekend"}:
        saturday = monday + timedelta(days=5)
        if today > saturday + timedelta(days=1):
            saturday += timedelta(days=7)
        return saturday, saturday + timedelta(days=1)
    if text in {"next weekend"}:
        return monday + timedelta(days=12), monday + timedelta(days=13)
    if text in {"this month", "current month", "month"}:
        return today.replace(day=1), _end_of_month(today)
    if text in {"rest of the month", "rest of this month", "remainder of the month"}:
        return today, _end_of_month(today)
    if text in {"next month", "following month"}:
        start = _first_of_next_month(today)
        return start, _end_of_month(start)
    if text in {"last month", "previous month", "month before"}:
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end

    match = _WEEKDAY_RE.match(text)
    if match:
        qualifier, name = match.group(1), match.group(2)
        target = _WEEKDAY_NAMES[name]
        if qualifier in {"last", "past", "previous"}:
            day = today - timedelta(days=(today.weekday() - target) % 7 or 7)
        elif qualifier == "next":
            # The one in next week, which is what "next Thursday" means to
            # someone looking at a diary, even on a Wednesday.
            day = monday + timedelta(days=7 + target)
        else:
            day = today + timedelta(days=(target - today.weekday()) % 7)
        return day, day

    named = _read_named_date(text, today)
    if named:
        return named

    match = _COUNT_UNIT_RE.match(text)
    if match:
        direction, count_text, unit = match.group(1), match.group(2) or "1", match.group(3)
        count = int(count_text) if count_text.isdigit() else _COUNT_WORDS.get(count_text, 1)
        span = max(1, count) * _UNIT_DAYS[unit]
        if direction in {"last", "past", "previous"}:
            return today - timedelta(days=span - 1), today
        return today, today + timedelta(days=span - 1)
    return None


def _scan_for_days(text: str, today: date) -> tuple[date, date] | None:
    """Find a period inside a longer phrase.

    A field meant to hold "tomorrow" sometimes arrives holding the sentence it
    came from. The days are in there either way, so the longest run of words
    that reads as a period is used rather than the whole string being called
    unreadable.
    """

    tokens = text.split(" ")[:_MAX_SCANNED_WORDS]
    for width in range(min(len(tokens), _MAX_SCANNED_PHRASE_WORDS), 0, -1):
        for start in range(0, len(tokens) - width + 1):
            days = _read_calendar_days(" ".join(tokens[start:start + width]), today)
            if days is not None:
                return days
    return None


def parse_calendar_date_range(
    value: str | None,
    *,
    timezone_name: str | None = "UTC",
    now: datetime | None = None,
) -> CalendarDateRange:
    """Resolve a period written in someone's own words into an API interval.

    The words arrive as they were typed - "tomorrow morning", "Thursday", "the
    next few days" - so this reads them rather than matching them against a
    list.  When it still cannot place them it reads the week ahead and says so
    through ``assumed``: a question about the diary is better answered with the
    days it read named out loud than refused for its phrasing.
    """

    zone = _safe_zone(timezone_name)
    current = (now or datetime.now(zone)).astimezone(zone)
    today = current.date()
    raw = _normalize_range_text(value) or "next week"

    assumed = False
    days = _read_explicit_range(raw)
    if days is None:
        text = _strip_filler(raw)
        without_day_part = _strip_filler(re.sub(r"\s+", " ", _DAY_PART_RE.sub(" ", text)).strip(" -,"))
        days = _read_calendar_days(text, today)
        if days is None and without_day_part != text:
            days = _read_calendar_days(without_day_part, today)
        if days is None:
            days = _scan_for_days(without_day_part, today) or _scan_for_days(text, today)
    if days is None:
        days = (today, today + timedelta(days=CALENDAR_FALLBACK_RANGE_DAYS - 1))
        assumed = True

    start_date, end_date = days
    if end_date < start_date:
        # A range written back to front is a range, not a mistake worth
        # stopping for.
        start_date, end_date = end_date, start_date
    if (end_date - start_date).days + 1 > CALENDAR_MAX_RANGE_DAYS:
        end_date = start_date + timedelta(days=CALENDAR_MAX_RANGE_DAYS - 1)

    return CalendarDateRange(
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        start=_start_of_day(start_date, zone),
        end=_start_of_day(end_date + timedelta(days=1), zone),
        assumed=assumed,
    )


def _event_datetime(value: Any, zone: ZoneInfo, *, end: bool = False) -> datetime | None:
    if not isinstance(value, dict):
        return None
    raw = str(value.get("dateTime") or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone)
    raw_date = str(value.get("date") or "").strip()
    if raw_date:
        try:
            return _start_of_day(date.fromisoformat(raw_date), zone)
        except ValueError:
            return None
    return None


def normalize_calendar_event(event: dict[str, Any], *, timezone_name: str | None = "UTC") -> dict[str, Any] | None:
    zone = _safe_zone(timezone_name)
    start = _event_datetime(event.get("start"), zone)
    end = _event_datetime(event.get("end"), zone, end=True)
    if start is None:
        return None
    return {
        "id": str(event.get("id") or "").strip(),
        "title": str(event.get("summary") or "Untitled meeting").strip() or "Untitled meeting",
        "start": start,
        "end": end,
        "location": str(event.get("location") or "").strip(),
        "description": str(event.get("description") or "").strip(),
        "allDay": bool(event.get("start", {}).get("date")) if isinstance(event.get("start"), dict) else False,
    }


def normalize_calendar_list_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one Google calendarList row into something the portal can show.

    The account's own calendar comes back keyed by the account address; it is
    rewritten to "primary" so a saved action keeps pointing at the right
    calendar even if the address behind the connection changes.
    """

    access_role = str(entry.get("accessRole") or "").strip().lower()
    if access_role not in CALENDAR_READABLE_ACCESS_ROLES:
        return None
    is_primary = bool(entry.get("primary"))
    calendar_id = PRIMARY_CALENDAR_ID if is_primary else normalize_calendar_id(entry.get("id"))
    if calendar_id == PRIMARY_CALENDAR_ID and not is_primary:
        # An ID that is not an address cannot be put in a request path, and
        # silently reading the account's own calendar instead would be a lie.
        return None
    label = str(entry.get("summaryOverride") or entry.get("summary") or "").strip()
    return {
        "id": calendar_id,
        "label": label or ("My calendar" if is_primary else calendar_id),
        "primary": is_primary,
        "accessRole": access_role,
    }


def _format_event_time(event: dict[str, Any]) -> str:
    start = event["start"]
    if event.get("allDay"):
        return start.strftime("%a, %b %-d · all day")
    end = event.get("end")
    start_label = start.strftime("%a, %b %-d · %-I:%M %p")
    if isinstance(end, datetime) and end.date() == start.date():
        return f"{start_label}–{end.strftime('%-I:%M %p')}"
    return start_label


def _display_range(date_range: CalendarDateRange) -> str:
    start = date_range.start
    end = date_range.end - timedelta(days=1)
    if start.date() == end.date():
        # One day is a day, not a range from itself to itself.
        return start.strftime("%b %-d, %Y")
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.strftime('%-d, %Y')}"
        return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d, %Y')}"
    return f"{start.strftime('%b %-d, %Y')}–{end.strftime('%b %-d, %Y')}"


def describe_calendar_records(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Each meeting as one flat line, for answering questions about them.

    The summary reads the diary out in order, which answers "what is on this
    week" and nothing else. A question about which meeting moved, where the
    afternoon is free, or who keeps booking an hour is answered from the
    meetings themselves, so they travel back in the same shape every other
    lookup uses.
    """

    records: list[dict[str, str]] = []
    for event in events:
        record = {
            "kind": "meeting",
            "when": _format_event_time(event),
            "title": str(event.get("title") or "").strip(),
            "location": str(event.get("location") or "").strip(),
            "detail": re.sub(r"\s+", " ", str(event.get("description") or "")).strip()[:240],
        }
        records.append({key: value for key, value in record.items() if value})
    return records


# The hours a working day is assumed to run between when nobody has said
# otherwise. A free slot outside them is technically free and practically not,
# and offering someone 6am is worse than offering nothing.
CALENDAR_DAY_START_HOUR = 9
CALENDAR_DAY_END_HOUR = 18
# A gap shorter than this is not a slot anybody can put a meeting in.
CALENDAR_MIN_SLOT_MINUTES = 30
# Enough days to cover the week or two a question about availability is
# usually about.
CALENDAR_MAX_FREE_DAYS = 14


def _busy_periods(events: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    """The meetings that actually take up time, merged where they overlap.

    An all-day entry is left out. A birthday and a public holiday are all-day
    entries, and treating them as busy would report a whole day gone over
    something nobody has to attend. They still travel back as meetings, so an
    answer can mention them.
    """

    periods: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.get("allDay"):
            continue
        start = event.get("start")
        end = event.get("end") or start
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        if end <= start:
            # A zero-length entry still marks the moment as taken.
            end = start + timedelta(minutes=CALENDAR_MIN_SLOT_MINUTES)
        periods.append((start, end))
    periods.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in periods:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def find_calendar_conflicts(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Meetings that overlap each other, which is nearly always a mistake."""

    timed = [
        event for event in events
        if not event.get("allDay")
        and isinstance(event.get("start"), datetime)
        and isinstance(event.get("end"), datetime)
        and event["end"] > event["start"]
    ]
    timed.sort(key=lambda event: event["start"])
    conflicts: list[dict[str, str]] = []
    for index, event in enumerate(timed):
        for other in timed[index + 1:]:
            if other["start"] >= event["end"]:
                break
            conflicts.append({
                "day": event["start"].date().isoformat(),
                "first": str(event.get("title") or ""),
                "second": str(other.get("title") or ""),
                "overlapFrom": other["start"].strftime("%H:%M"),
                "overlapTo": min(event["end"], other["end"]).strftime("%H:%M"),
            })
    return conflicts


def describe_availability(
    events: list[dict[str, Any]],
    date_range: CalendarDateRange,
    *,
    timezone_name: str | None = "UTC",
    day_start_hour: int = CALENDAR_DAY_START_HOUR,
    day_end_hour: int = CALENDAR_DAY_END_HOUR,
) -> dict[str, Any]:
    """When this calendar is free, worked out rather than read off.

    The summary reads the diary out in order, which answers "what is on next
    week". "Am I free Thursday afternoon" is the question people actually ask
    a calendar, and it cannot be answered by listing what is on: it is about
    the gaps between the meetings, which is arithmetic, and arithmetic belongs
    here rather than in a sentence the model works out while writing.
    """

    zone = _safe_zone(timezone_name)
    busy = _busy_periods(events)
    days: list[dict[str, Any]] = []
    day = date_range.start_date
    # How many days the question covered, so a range longer than one answer
    # can carry knows what it left behind rather than stopping quietly.
    days_asked = (date_range.end_date - date_range.start_date).days + 1
    while day <= date_range.end_date and len(days) < CALENDAR_MAX_FREE_DAYS:
        opens = datetime.combine(day, dt_time(hour=day_start_hour), tzinfo=zone)
        closes = datetime.combine(day, dt_time(hour=day_end_hour), tzinfo=zone)
        free: list[dict[str, str]] = []
        cursor = opens
        for start, end in busy:
            if end <= opens or start >= closes:
                continue
            window_start = max(start, opens)
            if window_start - cursor >= timedelta(minutes=CALENDAR_MIN_SLOT_MINUTES):
                free.append({"from": cursor.strftime("%H:%M"), "to": window_start.strftime("%H:%M")})
            cursor = max(cursor, min(end, closes))
        if closes - cursor >= timedelta(minutes=CALENDAR_MIN_SLOT_MINUTES):
            free.append({"from": cursor.strftime("%H:%M"), "to": closes.strftime("%H:%M")})
        booked = sum(
            (min(end, closes) - max(start, opens)).total_seconds() / 60
            for start, end in busy
            if end > opens and start < closes
        )
        days.append({
            "day": day.isoformat(),
            "free": free,
            "bookedMinutes": int(max(0, booked)),
        })
        day += timedelta(days=1)

    availability: dict[str, Any] = {
        "workingHours": f"{day_start_hour:02d}:00-{day_end_hour:02d}:00",
        "timezone": str(zone),
        "freeByDay": days,
    }
    if date_range.assumed:
        # The words naming the period could not be placed, so these are the
        # days the run picked. Naming them lets the answer show its working
        # instead of quietly answering about a week nobody asked for.
        availability["dateRangeAssumed"] = _display_range(date_range)
    unread = max(0, days_asked - len(days))
    if unread:
        # "When am I free next month" answered with the first fortnight, and
        # nothing saying so, is a partial answer wearing a whole one's clothes.
        availability["daysNotChecked"] = unread
        availability["checkedThrough"] = days[-1]["day"] if days else ""
    conflicts = find_calendar_conflicts(events)
    if conflicts:
        availability["overlappingMeetings"] = conflicts
    all_day = [str(event.get("title") or "") for event in events if event.get("allDay")]
    if all_day:
        # Not counted as busy, because a birthday is not a meeting. Named, so
        # an answer offering that day can mention what is on it.
        availability["allDayEntries"] = all_day
    return availability


def build_calendar_summary(
    events: list[dict[str, Any]],
    date_range: CalendarDateRange,
    *,
    skipped_calendars: list[dict[str, Any]] | None = None,
) -> str:
    """Build a concise portal-safe summary from normalized event records."""

    header = f"Meeting summary · {_display_range(date_range)}"
    # A calendar that could not be read is named in the summary rather than
    # quietly leaving its meetings out.
    skipped_lines = [
        f"Couldn’t read {str(entry.get('calendar') or '').strip()}: {str(entry.get('message') or '').strip()}"
        for entry in (skipped_calendars or [])
        if str(entry.get("calendar") or "").strip()
    ]
    if not events:
        body = f"{header}\n\nNo meetings found in this range."
        return "\n".join([body, "", *skipped_lines]) if skipped_lines else body

    lines = [header, "", f"{len(events)} meeting{'s' if len(events) != 1 else ''}:"]
    for event in events[:CALENDAR_MAX_EVENTS]:
        detail = f"• {_format_event_time(event)} — {event['title']}"
        if event.get("location"):
            detail += f" · {event['location']}"
        lines.append(detail[:500])
        description = re.sub(r"\s+", " ", str(event.get("description") or "")).strip()
        if description:
            lines.append(f"  {description[:240]}")
    if len(events) > CALENDAR_MAX_EVENTS:
        lines.append(f"…and {len(events) - CALENDAR_MAX_EVENTS} more.")
    if skipped_lines:
        lines.extend(["", *skipped_lines])
    return "\n".join(lines)


# The same meeting shows up once per calendar it was invited to, and reading
# two calendars should not report it twice.
def _merge_calendar_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for event in events:
        event_id = str(event.get("id") or "").strip()
        key = (event_id,) if event_id else (event.get("start"), event.get("title"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
    merged.sort(key=lambda item: item["start"])
    return merged


class CalendarSummaryRunner:
    """Fetch and summarize a connected Google Calendar using read-only access."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = CALENDAR_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def _read_json(
        self,
        url: str,
        access_token: str,
        *,
        on_http_error: Callable[[urllib_error.HTTPError], CalendarSummaryError],
    ) -> dict[str, Any]:
        """GET one Google Calendar URL and return its JSON body.

        Transport failures read the same for every caller; only the meaning of
        an HTTP status differs between reading a calendar and listing them, so
        that one decision is left to the caller.
        """

        token = str(access_token or "").strip()
        if not token:
            raise CalendarAuthorizationError(
                "Calendar access needs attention: no usable access token is saved. Reconnect Calendar with Google read-only access, then run it again."
            )
        request = urllib_request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            raise on_http_error(exc) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise CalendarSummaryError(
                "I couldn’t reach Google Calendar. Check the connection and try the run again.",
                code="calendar_network_error",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CalendarSummaryError(
                "I couldn’t read Google Calendar just now. Try it again later, and reconnect Calendar if it keeps happening.",
                code="calendar_provider_error",
            ) from exc
        if not isinstance(payload, dict):
            raise CalendarSummaryError(
                "I couldn’t read Google Calendar just now. Try it again later, and reconnect Calendar if it keeps happening.",
                code="calendar_provider_error",
            )
        return payload

    def fetch_calendar_list(self, access_token: str) -> list[dict[str, Any]]:
        """Return the calendars inside the connected account, readable ones only.

        This is what lets the action editor offer real calendars - "Family",
        "Birthdays" - instead of asking someone to paste an ID.  It needs its
        own grant: the events scope can read a calendar but cannot say which
        calendars exist, so an older connection raises
        ``CalendarListUnavailableError`` rather than failing the whole editor.
        """

        def on_http_error(exc: urllib_error.HTTPError) -> CalendarSummaryError:
            # 403 here is the missing calendar-list grant, not a missing share:
            # the account is asking about itself, and there is nothing to share.
            if exc.code in {401, 403}:
                return CalendarListUnavailableError()
            return CalendarSummaryError(
                "I couldn’t read your list of calendars just now. Try it again later, and reconnect Calendar if it keeps happening.",
                code="calendar_provider_error",
            )

        params = urllib_parse.urlencode({
            "minAccessRole": "reader",
            "showDeleted": "false",
            "showHidden": "true",
            "maxResults": str(CALENDAR_MAX_LISTED_CALENDARS),
        })
        payload = self._read_json(
            f"{CALENDAR_LIST_API_URL}?{params}",
            access_token,
            on_http_error=on_http_error,
        )
        raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        calendars = [
            normalized
            for item in raw_items
            if isinstance(item, dict)
            for normalized in [normalize_calendar_list_entry(item)]
            if normalized is not None
        ]
        # The account's own calendar first, then the rest by name, so the
        # picker reads the same way twice in a row.
        calendars.sort(key=lambda entry: (not entry["primary"], entry["label"].lower()))
        return calendars[:CALENDAR_MAX_LISTED_CALENDARS]

    def fetch_events(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        date_range: CalendarDateRange,
    ) -> list[dict[str, Any]]:
        # A calendar ID reaches the request path only as "primary" or as an
        # address, so a saved label can never be read as a URL.
        safe_calendar_id = normalize_calendar_id(calendar_id)
        params = urllib_parse.urlencode({
            "timeMin": date_range.start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "timeMax": date_range.end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(CALENDAR_MAX_EVENTS),
        })
        encoded_calendar_id = urllib_parse.quote(safe_calendar_id, safe="")

        def on_http_error(exc: urllib_error.HTTPError) -> CalendarSummaryError:
            if exc.code == 401 or (exc.code == 403 and safe_calendar_id == PRIMARY_CALENDAR_ID):
                return CalendarAuthorizationError(
                    "Calendar access needs attention: Google rejected the saved credential or its permissions. Reconnect with a Google OAuth token that grants read-only Calendar access, then run it again."
                )
            # An extra calendar the account cannot open is a sharing problem
            # with that one calendar, not a problem with the connection.
            if exc.code in {403, 404}:
                return CalendarNotSharedError(safe_calendar_id)
            return CalendarSummaryError(
                # A client reads this sentence; the HTTP code stays in ``code``.
                "I couldn’t read Google Calendar just now. Try it again later, and reconnect Calendar if it keeps happening.",
                code="calendar_provider_error",
            )

        payload = self._read_json(
            f"{CALENDAR_API_URL}/{encoded_calendar_id}/events?{params}",
            access_token,
            on_http_error=on_http_error,
        )
        raw_events = payload.get("items") if isinstance(payload.get("items"), list) else []
        events = [
            normalized
            for item in raw_events
            if isinstance(item, dict)
            for normalized in [normalize_calendar_event(item, timezone_name=str(date_range.start.tzinfo or "UTC"))]
            if normalized is not None
        ]
        events.sort(key=lambda item: item["start"])
        return events

    def fetch_calendar_events(
        self,
        access_token: str,
        *,
        calendar_ids: list[str],
        date_range: CalendarDateRange,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Read every listed calendar and merge the meetings into one list."""

        events: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        first_error: CalendarSummaryError | None = None
        read_any = False
        for calendar_id in calendar_ids or ["primary"]:
            try:
                events.extend(self.fetch_events(access_token, calendar_id=calendar_id, date_range=date_range))
            except CalendarSummaryError as exc:
                # One unreadable calendar should not lose the meetings from the
                # others, so the run continues and says what it skipped.
                first_error = first_error or exc
                skipped.append({"calendar": calendar_id, "message": str(exc)})
                continue
            read_any = True
        if not read_any and first_error is not None:
            raise first_error
        return _merge_calendar_events(events), skipped

    def run(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        calendar_ids: Any = None,
        time_window: str = "next week",
        timezone_name: str = "UTC",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        date_range = parse_calendar_date_range(time_window, timezone_name=timezone_name, now=now)
        wanted = parse_calendar_ids(calendar_ids if calendar_ids is not None else calendar_id)
        events, skipped = self.fetch_calendar_events(
            access_token,
            calendar_ids=wanted,
            date_range=date_range,
        )
        summary = build_calendar_summary(events, date_range, skipped_calendars=skipped)
        return {
            "message": summary,
            "summary": summary,
            # The meetings themselves, so a question about them can be answered
            # from what is in the diary rather than from the summary of it.
            "items": describe_calendar_records(events),
            # When the diary is free, worked out from the gaps between the
            # meetings. "What is on next week" is answered by the summary
            # above; "am I free Thursday afternoon" can only be answered from
            # this, and it is arithmetic rather than something to write out
            # while composing a sentence.
            "availability": describe_availability(events, date_range, timezone_name=timezone_name),
            "eventCount": len(events),
            "calendars": wanted,
            "skippedCalendars": skipped,
            "dateRange": {
                "label": date_range.label,
                "display": _display_range(date_range),
                # True when the period could not be placed and the week ahead
                # was read instead, so the answer can say which days it read.
                "assumed": date_range.assumed,
                "start": date_range.start.isoformat(),
                "end": date_range.end.isoformat(),
            },
        }
