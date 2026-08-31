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
# not turn into a long chain of provider calls.
CALENDAR_MAX_CALENDARS = 5
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


def parse_calendar_ids(value: Any) -> list[str]:
    """Turn the saved calendar field into the calendars a run should read.

    The field holds one tag per calendar: the connected account, whatever it is
    labelled, plus any address the user added.  Every tag that is not an address
    means the connected account's own calendar, which Google calls "primary".
    """

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
    return calendar_ids[:CALENDAR_MAX_CALENDARS] or ["primary"]


@dataclass(frozen=True)
class CalendarDateRange:
    label: str
    start: datetime
    end: datetime

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


def _parse_explicit_date_range(value: str, zone: ZoneInfo) -> CalendarDateRange | None:
    match = re.search(
        r"(?P<start>\d{4}-\d{1,2}-\d{1,2})\s*(?:to|through|until|[-–])\s*(?P<end>\d{4}-\d{1,2}-\d{1,2})",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        start_date = date.fromisoformat(match.group("start"))
        end_date = date.fromisoformat(match.group("end"))
    except ValueError as exc:
        raise CalendarSummaryError("The meeting date range is not valid. Choose a range such as next week.", code="invalid_date_range") from exc
    if end_date < start_date:
        raise CalendarSummaryError("The meeting date range ends before it starts. Choose a valid range.", code="invalid_date_range")
    return CalendarDateRange(
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        start=_start_of_day(start_date, zone),
        end=_start_of_day(end_date + timedelta(days=1), zone),
    )


def parse_calendar_date_range(
    value: str | None,
    *,
    timezone_name: str | None = "UTC",
    now: datetime | None = None,
) -> CalendarDateRange:
    """Resolve the portal's friendly date ranges into an API interval."""

    zone = _safe_zone(timezone_name)
    current = (now or datetime.now(zone)).astimezone(zone)
    today = current.date()
    normalized = re.sub(r"\s+", " ", str(value or "next week").strip().lower())
    explicit = _parse_explicit_date_range(normalized, zone)
    if explicit:
        return explicit

    if normalized in {"today", "this day"}:
        start_date, end_date = today, today
    elif normalized in {"tomorrow", "next day"}:
        start_date = end_date = today + timedelta(days=1)
    elif normalized in {"this week", "this calendar week"}:
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif normalized in {"next week", "next calendar week"}:
        start_date = today - timedelta(days=today.weekday()) + timedelta(days=7)
        end_date = start_date + timedelta(days=6)
    elif normalized in {"this month", "current month"}:
        start_date = today.replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
    elif normalized in {"next month"}:
        start_date = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
    else:
        raise CalendarSummaryError(
            "I couldn’t understand that meeting date range. Choose today, this week, next week, or a specific range.",
            code="invalid_date_range",
        )

    return CalendarDateRange(
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        start=_start_of_day(start_date, zone),
        end=_start_of_day(end_date + timedelta(days=1), zone),
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
                "start": date_range.start.isoformat(),
                "end": date_range.end.isoformat(),
            },
        }
