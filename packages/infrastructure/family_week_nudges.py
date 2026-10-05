"""The nudges that make a family's week something held for them.

Three moments, each once, on the person's own clock:

* the morning: what today holds, one bullet per thing, who takes and who
  collects, with anything nobody is down for yet said in its own bullet
  and nowhere else - the facts go to the model once, so they come back
  once;
* the evening before: a drop-off or pickup tomorrow that still has nobody,
  while there is time to sort it out - and a drive the account holder is
  down for that lands inside something already in their own calendar, which
  is the other way tomorrow goes wrong: everyone is named, and one of them
  is in a meeting;
* the ride: shortly before the account holder is the one driving, a word
  that it is time to leave - and only then: a drive someone else does, or a
  child who comes home on the bus, is in the morning plan and is not
  mentioned again through the day. Two of their drives close together -
  school and kindergarten both at eight - are one word, planned as one
  trip, not two messages a minute apart. A drive whose leaving time falls
  within twenty minutes of the morning message, either side, is in that
  message and is not said again: two messages at once saying the same
  thing read as a glitch, not as care;
* a birthday a month away, with an offer of the ready-made list to get
  ready for it.

Code decides what is due and says it plainly in the fallback sentence; the
message itself is written by the assistant from those facts, the way the
mailbox alerts are. The week is the usual week, so each day is first held up
against what the family said is not happening (schedule_exceptions) and
the school calendar where they live (school_days): on a holiday, a trip or
a sick day, what is off is not mentioned at all, and a day with nothing left
on it sends nothing. Each is claimed in the database
before it is queued, so two polls cannot send it twice, and a moment the
poll missed is skipped rather than sent late. A family that put off getting to know them is asked
once, lightly, on the day they were told it would come back.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error as urllib_error
import urllib.request as urllib_request
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure import household
from packages.infrastructure.account_types import account_feature_allowed
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.schedule_exceptions import activities_not_excepted
from packages.infrastructure.schedule_exceptions import family_week_paused
from packages.infrastructure.school_days import SchoolCalendar
from packages.infrastructure.school_days import describe_day
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE
from packages.infrastructure.whatsapp_agent_chat import infer_timezone_from_wa_id

NUDGE_SOURCE = "family_week"
DEFAULT_MORNING_HOUR = 7
DEFAULT_EVENING_HOUR = 20
DEFAULT_RIDE_LEAD_MINUTES = 30
# Drives of the owner's that follow one another within this many minutes
# of the first due are said together, as one trip.
DEFAULT_RIDE_MERGE_MINUTES = 30
# A drive whose leaving time is nearer than this to the morning message is
# told in the morning message alone, not reminded again beside it.
DEFAULT_RIDE_DIGEST_GAP_MINUTES = 20
DEFAULT_POLL_SECONDS = 120
# How late a moment may still be told. A poll that runs a little after the
# hour still counts; one that runs hours later has missed it.
MORNING_WINDOW_HOURS = 3
EVENING_WINDOW_HOURS = 2
# A birthday is raised a month ahead. One learned later is still raised
# while there is a little time, but not in its last days.
BIRTHDAY_EARLIEST_DAYS = 3
# Where one day of the account holder's own calendar is read from, over the
# server's own API, the way the inbox watch polls: a short-lived session for
# that account, and every usual check applied by the handler.
CALENDAR_DAY_ENDPOINT = "/api/family-week/calendar-day"
CALENDAR_READ_TIMEOUT_SECONDS = 60

# How a day of their calendar reaches the nudger: given the account, the day
# and where they live, the timed entries of that day, each with a title and
# a start and end. None means no calendar is read.
CalendarDayReader = Callable[[int, date, str], list[dict[str, Any]]]


@dataclass(frozen=True)
class FamilyWeekNudgeConfig:
    enabled: bool = True
    morning_hour: int = DEFAULT_MORNING_HOUR
    evening_hour: int = DEFAULT_EVENING_HOUR
    ride_lead_minutes: int = DEFAULT_RIDE_LEAD_MINUTES
    ride_merge_minutes: int = DEFAULT_RIDE_MERGE_MINUTES
    ride_digest_gap_minutes: int = DEFAULT_RIDE_DIGEST_GAP_MINUTES
    poll_seconds: int = DEFAULT_POLL_SECONDS
    # Whether each day is checked against the school calendar online. Off
    # only for an incident: without it a holiday is nudged like any day.
    school_calendar: bool = True


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(normalize_text(value) or default)
    except (TypeError, ValueError):
        return default


def load_family_week_nudge_config() -> FamilyWeekNudgeConfig:
    enabled_text = normalize_text(os.getenv("PORTAL_FAMILY_NUDGES_ENABLED")).lower()
    return FamilyWeekNudgeConfig(
        enabled=enabled_text not in {"0", "false", "no", "off", "disabled"},
        morning_hour=min(23, max(0, _parse_int(os.getenv("PORTAL_FAMILY_MORNING_HOUR"), DEFAULT_MORNING_HOUR))),
        evening_hour=min(23, max(0, _parse_int(os.getenv("PORTAL_FAMILY_EVENING_HOUR"), DEFAULT_EVENING_HOUR))),
        ride_lead_minutes=min(180, max(5, _parse_int(os.getenv("PORTAL_FAMILY_RIDE_LEAD_MINUTES"), DEFAULT_RIDE_LEAD_MINUTES))),
        ride_merge_minutes=min(180, max(0, _parse_int(os.getenv("PORTAL_FAMILY_RIDE_MERGE_MINUTES"), DEFAULT_RIDE_MERGE_MINUTES))),
        ride_digest_gap_minutes=min(180, max(0, _parse_int(os.getenv("PORTAL_FAMILY_RIDE_DIGEST_GAP_MINUTES"), DEFAULT_RIDE_DIGEST_GAP_MINUTES))),
        poll_seconds=max(30, _parse_int(os.getenv("PORTAL_FAMILY_NUDGE_POLL_SECONDS"), DEFAULT_POLL_SECONDS)),
        school_calendar=normalize_text(os.getenv("PORTAL_FAMILY_SCHOOL_CALENDAR")).lower()
        not in {"0", "false", "no", "off", "disabled"},
    )


# -- what is due, in code -----------------------------------------------------


def owner_phone(database: Any, user_id: int) -> str:
    """The account holder's own linked phone, never a family member's. A
    store without the distinction (an older one, a test double) gives the
    newest linked number, as before."""

    finder = getattr(database, "get_owner_whatsapp_number", None)
    if callable(finder):
        try:
            return normalize_text(finder(user_id=user_id))
        except Exception:  # noqa: BLE001 - fall back to the plain list
            pass
    linked = database.list_user_whatsapp_numbers(user_id=user_id)
    return normalize_text(linked[0].get("waId")) if linked else ""


def activities_on(activities: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    code = household.weekday_code(day)
    return [activity for activity in activities if code in (activity.get("days") or [])]


def _who(activity: dict[str, Any], owner_names: list[str] | None = None, viewer_names: list[str] | None = None) -> str:
    return ", ".join(_ride_word(name, owner_names or [], viewer_names) for name in activity.get("who") or [])


def _ride_word(value: Any, owner_names: list[str], viewer_names: list[str] | None = None) -> str:
    """Who drives, as the reader sees it. Read by the account holder, "me"
    and their own name are "you". Read by a family member on their own
    phone (viewer_names), their name is "you" and the account holder's "me"
    is the account holder's first name - never "you", which would hand them
    a drive that is not theirs."""

    if viewer_names is not None:
        if household.is_named(value, viewer_names):
            return "you"
        if household.is_self(value, owner_names):
            first = next((normalize_text(name).split(" ")[0] for name in owner_names if normalize_text(name)), "")
            return first or normalize_text(value)
        return normalize_text(value)
    return "you" if household.is_self(value, owner_names) else normalize_text(value)


def describe_activity_line(
    activity: dict[str, Any],
    owner_names: list[str],
    members: list[dict[str, Any]] | None = None,
    viewer_names: list[str] | None = None,
    during_work: dict[str, str] | None = None,
) -> str:
    """One activity as a plain line: time, what, for whom, who takes and
    collects. A grown-up's own week - their work - is the line alone: nobody
    takes them and nobody collects them, so neither is said to be missing.
    viewer_names is who is reading when it is a family member on their own
    phone rather than the account holder: "you" is then them. during_work
    is, by leg, the person's own work hours a drive of theirs falls inside
    and has not been settled: the morning says so in the same bullet, so a
    pickup they cannot make is not read as sorted."""

    parts = []
    times = normalize_text(activity.get("startTime"))
    if times and normalize_text(activity.get("endTime")):
        times = f"{times}-{activity['endTime']}"
    head = f"{times} {activity.get('title')}".strip()
    if _who(activity):
        head += f" ({_who(activity, owner_names, viewer_names)})"
    parts.append(head)
    if members is not None and household.is_grown_up_activity(activity, members, owner_names):
        return head
    takes = _ride_word(activity.get("dropOffBy"), owner_names, viewer_names)
    collects = _ride_word(activity.get("pickUpBy"), owner_names, viewer_names)
    inside = during_work or {}
    parts.append(
        (f"takes: {takes}" + (f" (inside your own {inside['drop_off']}, not settled yet)" if inside.get("drop_off") else ""))
        if takes else "nobody takes them yet"
    )
    parts.append(
        (f"collects: {collects}" + (f" (inside your own {inside['pick_up']}, not settled yet)" if inside.get("pick_up") else ""))
        if collects else "nobody collects them yet"
    )
    return ", ".join(parts)


def during_work_by_activity(
    activities: list[dict[str, Any]],
    members: list[dict[str, Any]] | None,
    owner_names: list[str],
    day: date,
) -> dict[int, dict[str, str]]:
    """For one day, the account holder's drives that fall inside their own
    work hours and are not settled, by activity id and leg, each as the
    hours they fall inside."""

    found: dict[int, dict[str, str]] = {}
    for record in household.drives_during_work(activities, members, owner_names, day=day):
        found.setdefault(int(record["activity"]["id"]), {})[record["leg"]] = household.describe_work_hours(record["work"])
    return found


def work_clash_lines(
    activities: list[dict[str, Any]],
    members: list[dict[str, Any]] | None,
    owner_names: list[str],
    day: date,
) -> list[str]:
    """The drives that day the account holder is down for which fall inside
    their own work hours, one plain line each, for the evening before. The
    hours are their own week, so unlike the calendar nothing is read for
    this - and once they have said a drive is fine as it is, it is not here."""

    lines = []
    for record in household.drives_during_work(activities, members, owner_names, day=day):
        activity = record["activity"]
        what = f"{activity.get('title')}" + (f" ({_who(activity, owner_names)})" if _who(activity) else "")
        which = "the drop-off" if record["leg"] == "drop_off" else "the pickup"
        lines.append(
            f"{what}, {which} at {record['at']}: you are down for it, but it falls inside your own "
            f"{household.describe_work_hours(record['work'])}"
        )
    return lines


def gap_lines(
    activities: list[dict[str, Any]],
    members: list[dict[str, Any]] | None = None,
    owner_names: list[str] | None = None,
) -> list[str]:
    lines = []
    for activity in activities:
        gaps = household.activity_gaps(activity, members, owner_names or [])
        if not gaps:
            continue
        what = f"{activity.get('title')}" + (f" ({_who(activity)})" if _who(activity) else "")
        when = normalize_text(activity.get("startTime") if gaps == ["drop_off"] else activity.get("endTime") or activity.get("startTime"))
        missing = " and ".join({"drop_off": "the drop-off", "pick_up": "the pickup"}[gap] for gap in gaps)
        lines.append(f"{what}{' at ' + when if when else ''}: nobody is down for {missing}")
    return lines


def rides_due_for_anyone(
    activities: list[dict[str, Any]],
    *,
    local_now: datetime,
    lead_minutes: int,
) -> list[dict[str, Any]]:
    """The drives today that somebody is down for, whose leaving time has
    come. Unlike the account's own week, a group's runs belong to whoever
    said they would take them, so each one carries that name: the reminder
    goes into the room and is addressed to them. A child who gets there on
    the bus or on foot is nobody's run, so the room is not told about it.
    """

    due = []
    for activity in activities_on(activities, local_now.date()):
        for leg, who_key, time_key in (("drop_off", "dropOffBy", "startTime"), ("pick_up", "pickUpBy", "endTime")):
            driver = normalize_text(activity.get(who_key))
            clock = household.normalize_time(activity.get(time_key))
            if not driver or not clock or household.nobody_drives(driver):
                continue
            hour, minute = (int(part) for part in clock.split(":"))
            moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment - timedelta(minutes=lead_minutes) <= local_now < moment:
                due.append({"activity": activity, "leg": leg, "at": clock, "driver": driver})
    return due


def owner_is_driving(activities: list[dict[str, Any]], owner_names: list[str]) -> bool:
    """Whether the account holder is down for any drive among these, at a
    time that is known - the only case their calendar is worth reading for."""

    for activity in activities:
        for who_key, time_key in (("dropOffBy", "startTime"), ("pickUpBy", "endTime")):
            if household.is_self(activity.get(who_key), owner_names) and household.normalize_time(activity.get(time_key)):
                return True
    return False


def _event_moment(value: Any, zone: ZoneInfo) -> datetime | None:
    """An event's start or end as the reader handed it over - a datetime, or
    the ISO text one becomes on the way through the API - in the person's zone."""

    if isinstance(value, datetime):
        moment = value
    else:
        text = normalize_text(value)
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone)


def ride_clashes(
    activities: list[dict[str, Any]],
    *,
    owner_names: list[str],
    day: date,
    zone: ZoneInfo,
    events: list[dict[str, Any]],
    lead_minutes: int,
) -> list[str]:
    """The drives that day the account holder is down for which land inside
    something in their own calendar.

    A drive takes the time around its moment, not the moment alone: they have
    to leave lead_minutes before and are on the road for a while after, so an
    entry anywhere in that stretch is the clash. All-day entries are not: a
    birthday or a holiday takes nobody out of the car. Each clash is one plain
    line with the entry named, so the evening message can ask who else can
    take it rather than letting the morning find out.
    """

    lead = timedelta(minutes=max(0, int(lead_minutes)))
    timed = []
    for event in events or ():
        if not isinstance(event, dict) or event.get("allDay"):
            continue
        start = _event_moment(event.get("start"), zone)
        if start is None:
            continue
        end = _event_moment(event.get("end"), zone) or start
        if end <= start:
            end = start + timedelta(minutes=1)
        timed.append((start, end, normalize_text(event.get("title")) or "something in your calendar"))
    if not timed:
        return []
    lines = []
    for activity in activities_on(activities, day):
        for leg, who_key, time_key in (("drop_off", "dropOffBy", "startTime"), ("pick_up", "pickUpBy", "endTime")):
            if not household.is_self(activity.get(who_key), owner_names):
                continue
            clock = household.normalize_time(activity.get(time_key))
            if not clock:
                continue
            hour, minute = (int(part) for part in clock.split(":"))
            moment = datetime.combine(day, dt_time(hour=hour, minute=minute), tzinfo=zone)
            window_start, window_end = moment - lead, moment + lead
            for start, end, title in timed:
                if start < window_end and end > window_start:
                    what = f"{activity.get('title')}" + (f" ({_who(activity, owner_names)})" if _who(activity) else "")
                    which = "the drop-off" if leg == "drop_off" else "the pickup"
                    lines.append(
                        f"{what}, {which} at {clock}: you are down for it, but your calendar has "
                        f"{title} {start:%H:%M}-{end:%H:%M}"
                    )
    return lines


def _is_driver(owner_names: list[str], driver_names: list[str] | None) -> Callable[[Any], bool]:
    """Whose drives are being looked for: the account holder's ("me" and
    their own name) by default, or a family member's by their name when
    driver_names is given - never "me", which is the account holder."""

    if driver_names is not None:
        return lambda who: household.is_named(who, driver_names)
    return lambda who: household.is_self(who, owner_names)


def _owner_rides_today(
    activities: list[dict[str, Any]],
    *,
    owner_names: list[str],
    local_now: datetime,
    driver_names: list[str] | None = None,
) -> list[tuple[datetime, dict[str, Any]]]:
    """Every leg today the account holder drives - or, with driver_names, a
    family member - with its moment, in time order. Only theirs: a leg
    somebody else or the bus takes is in the morning plan and nowhere else."""

    is_driver = _is_driver(owner_names, driver_names)
    rides = []
    for activity in activities_on(activities, local_now.date()):
        for leg, who_key, time_key in (("drop_off", "dropOffBy", "startTime"), ("pick_up", "pickUpBy", "endTime")):
            if not is_driver(activity.get(who_key)):
                continue
            clock = household.normalize_time(activity.get(time_key))
            if not clock:
                continue
            hour, minute = (int(part) for part in clock.split(":"))
            moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            rides.append((moment, {"activity": activity, "leg": leg, "at": clock}))
    # Two at the same time keep the week's own order.
    rides.sort(key=lambda pair: (pair[0], int(pair[1]["activity"].get("id") or 0)))
    return rides


def rides_due(
    activities: list[dict[str, Any]],
    *,
    owner_names: list[str],
    local_now: datetime,
    lead_minutes: int,
) -> list[dict[str, Any]]:
    """The drives today the account holder is down for, whose leaving time
    has come: within lead_minutes before it, and not yet past.

    Only theirs. A reminder through the day about a drive that is not theirs
    is noise, so it is never raised."""

    return [
        ride for moment, ride in _owner_rides_today(activities, owner_names=owner_names, local_now=local_now)
        if moment - timedelta(minutes=lead_minutes) <= local_now < moment
    ]


def rides_leaving_together(
    activities: list[dict[str, Any]],
    *,
    owner_names: list[str],
    local_now: datetime,
    lead_minutes: int,
    merge_minutes: int,
    driver_names: list[str] | None = None,
    digest_at: datetime | None = None,
    digest_gap_minutes: int = 0,
) -> list[dict[str, Any]]:
    """The owner's drives that go out as one word: those due now, and any
    other of theirs that follows within merge_minutes of the earliest of
    them. School at eight and kindergarten at eight, or at a quarter past,
    are one trip to plan - take both, drop one, then the other - so they are
    said once, in time order, not as two messages. A drive further off waits
    for its own time. driver_names makes them a family member's drives
    rather than the account holder's.

    digest_at is when this reader's morning message goes out. A drive whose
    leaving time - lead_minutes before it - is nearer than digest_gap_minutes
    to that moment, before or after, is in the morning message already and
    is left out here: it is not said again a minute later. A reader who
    gets no morning message passes nothing, and hears about every drive."""

    rides = _owner_rides_today(activities, owner_names=owner_names, local_now=local_now, driver_names=driver_names)
    lead = timedelta(minutes=lead_minutes)
    if digest_at is not None and digest_gap_minutes > 0:
        gap = timedelta(minutes=digest_gap_minutes)
        rides = [(moment, ride) for moment, ride in rides if abs(moment - lead - digest_at) >= gap]
    due = [moment for moment, _ride in rides if moment - lead <= local_now < moment]
    if not due:
        return []
    first = min(due)
    return [ride for moment, ride in rides if first <= moment <= first + timedelta(minutes=merge_minutes)]


# -- the account holder's own calendar -----------------------------------------


class LoopbackCalendarReader:
    """One day of the account holder's own calendar, read through the server's
    own API with a short-lived session for that account - the way the inbox
    watch polls - so the handler applies every usual check and the nudger
    never holds a credential. A calendar that cannot be read reads as empty:
    the evening message is never held up by it."""

    def __init__(self, database: Any, *, base_url: str, session_token_factory: Callable[[str], str]) -> None:
        self.database = database
        self.base_url = str(base_url or "").rstrip("/")
        self.session_token_factory = session_token_factory

    def __call__(self, user_id: int, day: date, timezone_name: str) -> list[dict[str, Any]]:
        if not self.base_url:
            return []
        user = self.database.get_user_by_id(user_id) or {}
        email = normalize_text(user.get("email"))
        if not email:
            return []
        request = urllib_request.Request(
            f"{self.base_url}{CALENDAR_DAY_ENDPOINT}",
            data=json.dumps({"day": day.isoformat(), "timezone": timezone_name}).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token_factory(email)}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=CALENDAR_READ_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except (urllib_error.HTTPError, urllib_error.URLError, OSError, ValueError) as exc:
            print(f"Family week nudger could not read the calendar for user {user_id}: {exc}", flush=True)
            return []
        events = body.get("events") if isinstance(body, dict) and body.get("ok") else None
        return [event for event in (events or []) if isinstance(event, dict)]


# -- the nudger ----------------------------------------------------------------


class FamilyWeekNudger:
    def __init__(
        self,
        database: Any,
        *,
        config: FamilyWeekNudgeConfig | None = None,
        school_calendar: SchoolCalendar | None = None,
        calendar_reader: CalendarDayReader | None = None,
    ) -> None:
        """school_calendar is what says whether a day is really on. Without
        one every day is the usual week, which is what a test wants.
        calendar_reader is how the account holder's own calendar is read for
        tomorrow's drives; without one, no clash is ever looked for."""

        self.database = database
        self.config = config or load_family_week_nudge_config()
        self.school_calendar = school_calendar
        self.calendar_reader = calendar_reader

    def _calendar_day(self, user_id: int, day: date, timezone_name: str) -> list[dict[str, Any]]:
        if self.calendar_reader is None:
            return []
        try:
            return list(self.calendar_reader(user_id, day, timezone_name) or [])
        except Exception as exc:  # noqa: BLE001 - the calendar is a courtesy check, never a blocker
            print(f"Family week nudger could not read the calendar for user {user_id}: {exc}", flush=True)
            return []

    def _on_day(
        self,
        *,
        user_id: int,
        group_id: str = "",
        timezone_name: str,
        day: date,
        activities: list[dict[str, Any]],
        exceptions: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """What of the usual week is really on that day, and what the school
        calendar said about the day when it is not an ordinary one.

        What the family said is off goes first and costs nothing; the
        calendar is only asked about what is left."""

        usual = activities_not_excepted(activities_on(activities, day), exceptions, day)
        if not usual or self.school_calendar is None:
            return usual, None
        user = self.database.get_user_by_id(user_id) or {}
        still_on, status = self.school_calendar.activities_still_on(
            user_id=user_id, scope=group_id, place=timezone_name, day=day, activities=usual,
            billing_email=normalize_text(user.get("email")),
        )
        return still_on, (status if status and not status.get("ordinary") else None)

    def _timezone_for_user(self, user_id: int) -> str:
        try:
            connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        except Exception:  # noqa: BLE001
            connection = {}
        wa_id = normalize_text(connection.get("ownerWaId")) or owner_phone(self.database, user_id)
        inferred = infer_timezone_from_wa_id(wa_id) if wa_id else ""
        return inferred or "UTC"

    def _owner_names(self, user_id: int) -> list[str]:
        user = self.database.get_user_by_id(user_id) or {}
        names = [normalize_text(user.get("displayName"))]
        for fact in self.database.list_account_facts(user_id=user_id):
            if fact.get("key") == "name":
                names.append(normalize_text(fact.get("fact")).removeprefix("Their name is ").rstrip("."))
        return [name for name in names if name]

    def _queue(
        self, *, user_id: int, now: datetime, timezone_name: str, title: str, instruction: str, fallback: str,
        offer: str = "", recipient_wa_id: str = "",
    ) -> None:
        """Queue one message for the account holder, or - with recipient_wa_id
        - for a family member's own phone on the same account."""

        connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        owner_wa_id = normalize_text(connection.get("ownerWaId")) or owner_phone(self.database, user_id)
        payload: dict[str, Any] = {
            "title": title,
            "instruction": instruction,
            "fallbackText": fallback,
            "oneOff": True,
            "source": NUDGE_SOURCE,
        }
        if offer:
            payload["offerInstruction"] = offer
        if recipient_wa_id:
            payload["recipientWaId"] = recipient_wa_id
        self.database.create_scheduled_action(
            user_id=user_id,
            action_type=STANDING_TASK_ACTION_TYPE,
            channel="whatsapp" if (recipient_wa_id or owner_wa_id) else "portal",
            recipient_ref=recipient_wa_id or "owner",
            run_at=now,
            timezone_name=timezone_name,
            payload=payload,
        )

    def _group_name(self, user_id: int, group_id: str) -> str:
        try:
            connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        except Exception:  # noqa: BLE001
            connection = {}
        metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
        for entry in metadata.get("groups") or []:
            if isinstance(entry, dict) and normalize_text(entry.get("id")) == group_id:
                return normalize_text(entry.get("subject"))
        return ""

    def _queue_group(
        self, *, user_id: int, group_id: str, group_name: str, now: datetime, timezone_name: str,
        title: str, instruction: str, fallback: str,
    ) -> None:
        """A nudge addressed to the room. It is written by a group turn - which
        can read the group's week and nothing of the account - and delivered
        into the group itself."""

        self.database.create_scheduled_action(
            user_id=user_id,
            action_type=STANDING_TASK_ACTION_TYPE,
            channel="whatsapp",
            recipient_ref=f"group:{group_id}",
            run_at=now,
            timezone_name=timezone_name,
            payload={
                "title": title,
                "instruction": instruction,
                "fallbackText": fallback,
                "oneOff": True,
                "source": NUDGE_SOURCE,
                "group": {"id": group_id, "name": group_name},
            },
        )

    def run_pending_for_groups(self, *, now: datetime | None = None) -> dict[str, Any]:
        """The nudges a group gets, which are the ones a rota needs: ask the
        room the evening before about a run nobody has taken, and remind the
        person who took one shortly before they have to leave.

        Everything here is the group's own week. Nothing of the account that
        opened the group is read, and nothing said here reaches it.
        """

        from packages.infrastructure.whatsapp_agent_chat import whatsapp_groups_enabled

        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        counts = {"groups": 0, "groupEvening": 0, "groupRides": 0}
        if not whatsapp_groups_enabled():
            return {"ok": True, **counts}
        for user_id, group_id in self.database.list_household_nudge_groups():
            if not account_feature_allowed(self.database, user_id=user_id, feature_id="family_week"):
                continue
            counts["groups"] += 1
            timezone_name = self._timezone_for_user(user_id)
            try:
                zone = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                zone, timezone_name = ZoneInfo("UTC"), "UTC"
            local_now = reference.astimezone(zone)
            today = local_now.date()
            group_name = self._group_name(user_id, group_id)
            activities = self.database.list_household_activities(user_id=user_id, group_id=group_id)
            members = self.database.list_household_members(user_id=user_id, group_id=group_id)
            exceptions = self.database.list_schedule_exceptions(
                user_id=user_id, group_id=group_id, ending_on_or_after=today.isoformat(),
            )
            claim = lambda key: self.database.claim_household_nudge(  # noqa: E731
                user_id=user_id, nudge_key=f"group:{group_id}:{key}",
            )

            tomorrow = today + timedelta(days=1)
            in_evening = self.config.evening_hour <= local_now.hour < self.config.evening_hour + EVENING_WINDOW_HOURS
            tomorrow_gaps = []
            if in_evening and gap_lines(activities_on(activities, tomorrow), members):
                tomorrow_on, _ = self._on_day(
                    user_id=user_id, group_id=group_id, timezone_name=timezone_name, day=tomorrow,
                    activities=activities, exceptions=exceptions,
                )
                tomorrow_gaps = gap_lines(tomorrow_on, members)
            if tomorrow_gaps:
                if claim(f"evening:{tomorrow.isoformat()}"):
                    self._queue_group(
                        user_id=user_id, group_id=group_id, group_name=group_name,
                        now=reference, timezone_name=timezone_name,
                        title="Tomorrow still needs someone",
                        instruction=(
                            "It is the evening before. Write one short message to this group, in the language the "
                            "group writes in, saying what tomorrow still has nobody down for and asking who can take "
                            "it. Ask the room, not any one person, and leave it easy to answer with a name. The facts "
                            "are exact; add none, and use no tool.\nTOMORROW:\n" + "\n".join(tomorrow_gaps)
                        ),
                        fallback="Tomorrow still needs someone - who can take it?\n"
                                 + "\n".join(f"• {line}" for line in tomorrow_gaps),
                    )
                    counts["groupEvening"] += 1

            todays, _ = self._on_day(
                user_id=user_id, group_id=group_id, timezone_name=timezone_name, day=today,
                activities=activities, exceptions=exceptions,
            )
            for ride in rides_due_for_anyone(
                todays, local_now=local_now, lead_minutes=self.config.ride_lead_minutes,
            ):
                activity = ride["activity"]
                if not claim(f"ride:{today.isoformat()}:{activity['id']}:{ride['leg']}"):
                    continue
                verb = "takes" if ride["leg"] == "drop_off" else "collects"
                who = _who(activity) or "them"
                place = normalize_text(activity.get("place"))
                fact = (
                    f"{ride['driver']} {verb} {who} - {activity.get('title')} at {ride['at']}"
                    + (f", {place}" if place else "")
                )
                self._queue_group(
                    user_id=user_id, group_id=group_id, group_name=group_name,
                    now=reference, timezone_name=timezone_name,
                    title="Time to leave soon",
                    instruction=(
                        "Somebody in this group is down for a run shortly. Write one short line to the group, in the "
                        "language it writes in, naming them and what it is, so they have time to leave. The fact is "
                        f"exact; add nothing, and use no tool.\nDRIVE: {fact}"
                    ),
                    fallback=f"Soon: {fact}.",
                )
                counts["groupRides"] += 1
        return {"ok": True, **counts}

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        counts = {"accounts": 0, "morning": 0, "evening": 0, "rides": 0, "birthdays": 0, "askedAgain": 0}
        for user_id in self.database.list_household_nudge_accounts():
            if not account_feature_allowed(self.database, user_id=user_id, feature_id="family_week"):
                continue
            counts["accounts"] += 1
            timezone_name = self._timezone_for_user(user_id)
            try:
                zone = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                zone, timezone_name = ZoneInfo("UTC"), "UTC"
            local_now = reference.astimezone(zone)
            today = local_now.date()
            activities = self.database.list_household_activities(user_id=user_id)
            members = self.database.list_household_members(user_id=user_id)
            exceptions = self.database.list_schedule_exceptions(user_id=user_id, ending_on_or_after=today.isoformat())
            # The whole week on hold - a trip, a holiday at home - is quiet
            # about the family altogether, birthdays and all; they come back
            # when it ends, while there is still time.
            week_paused = family_week_paused(exceptions, today)
            owner_names = self._owner_names(user_id)
            claim = lambda key: self.database.claim_household_nudge(user_id=user_id, nudge_key=key)  # noqa: E731

            # Held up against the school calendar every poll: the day is looked
            # up once and kept, so this is the first poll of the day's cost.
            todays, today_calendar = self._on_day(
                user_id=user_id, timezone_name=timezone_name, day=today, activities=activities, exceptions=exceptions,
            )
            if todays and self.config.morning_hour <= local_now.hour < self.config.morning_hour + MORNING_WINDOW_HOURS:
                if claim(f"morning:{today.isoformat()}"):
                    inside_work = during_work_by_activity(todays, members, owner_names, today)
                    lines = [
                        describe_activity_line(activity, owner_names, members, during_work=inside_work.get(int(activity.get("id") or 0)))
                        for activity in todays
                    ]
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name,
                        title="Today in your family's week",
                        instruction=(
                            "It is the morning. Write the person one short WhatsApp message with what today holds for "
                            "their family, in the language they write to you in: one bullet per thing, each a few words "
                            "- its time, who it is for, where, who takes and who collects - and where nobody is down "
                            "for a drop-off or pickup yet, say so in that bullet. Say each fact once: no opening line, "
                            "no sign-off, and no closing line that repeats what the bullets already say. 'you' is the "
                            "person. "
                            + (
                                "Where a drive of theirs is marked as falling inside their own work hours and not "
                                "settled yet, say so in that bullet in a few words and, at the end, ask in one line "
                                "who could take it or whether it is fine as it is. " if inside_work else ""
                            )
                            + (
                                "CALENDAR is what the school calendar says about today: mention it in a few words only "
                                "where it bears on what is listed, such as an earlier finish. " if today_calendar else ""
                            )
                            + "The facts are exact; add none, and use no tool.\nTODAY:\n" + "\n".join(lines)
                            + (f"\nCALENDAR: {describe_day(today, today_calendar)}" if today_calendar else "")
                        ),
                        fallback="Today:\n" + "\n".join(f"• {line}" for line in lines),
                    )
                    counts["morning"] += 1

            tomorrow = today + timedelta(days=1)
            in_evening = self.config.evening_hour <= local_now.hour < self.config.evening_hour + EVENING_WINDOW_HOURS
            tomorrow_gaps: list[str] = []
            tomorrow_clashes: list[str] = []
            tomorrow_work: list[str] = []
            if in_evening:
                usual_tomorrow = activities_on(activities, tomorrow)
                # The calendar is read once an evening, and only when they are
                # the one driving tomorrow: nobody else's meetings are theirs
                # to see, and a day they are not on the road needs no reading.
                wants_calendar = self.calendar_reader is not None and owner_is_driving(usual_tomorrow, owner_names)
                if (
                    gap_lines(usual_tomorrow, members, owner_names)
                    or work_clash_lines(usual_tomorrow, members, owner_names, tomorrow)
                    or wants_calendar
                ):
                    tomorrow_on, _ = self._on_day(
                        user_id=user_id, timezone_name=timezone_name, day=tomorrow, activities=activities,
                        exceptions=exceptions,
                    )
                    tomorrow_gaps = gap_lines(tomorrow_on, members, owner_names)
                    # A drive inside their own working day is the same question
                    # as a meeting, asked from the week itself: every evening
                    # until somebody else takes it or they say it is fine.
                    tomorrow_work = work_clash_lines(tomorrow_on, members, owner_names, tomorrow)
                    if wants_calendar and owner_is_driving(tomorrow_on, owner_names) and claim(f"evening-calendar:{tomorrow.isoformat()}"):
                        tomorrow_clashes = ride_clashes(
                            tomorrow_on, owner_names=owner_names, day=tomorrow, zone=zone,
                            events=self._calendar_day(user_id, tomorrow, timezone_name),
                            lead_minutes=self.config.ride_lead_minutes,
                        )
            if tomorrow_gaps or tomorrow_clashes or tomorrow_work:
                if claim(f"evening:{tomorrow.isoformat()}"):
                    about = []
                    if tomorrow_gaps:
                        about.append("what tomorrow still has nobody down for")
                    if tomorrow_clashes:
                        about.append(
                            "which drive of theirs tomorrow lands inside something already in their calendar - "
                            "name the entry, and ask who could take that drive instead"
                        )
                    if tomorrow_work:
                        about.append(
                            "which drive of theirs tomorrow falls inside their own work hours as they gave them - "
                            "name the hours, and ask who could take it or whether it is fine as it is, since they "
                            "may work close by"
                        )
                    fallback_parts = [
                        part for part in (
                            "Tomorrow still needs someone:\n" + "\n".join(f"• {line}" for line in tomorrow_gaps) if tomorrow_gaps else "",
                            "Tomorrow clashes with your calendar:\n" + "\n".join(f"• {line}" for line in tomorrow_clashes) if tomorrow_clashes else "",
                            "Tomorrow, inside your own work hours:\n" + "\n".join(f"• {line}" for line in tomorrow_work) if tomorrow_work else "",
                        ) if part
                    ]
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name,
                        title="Tomorrow still needs someone",
                        instruction=(
                            "It is the evening. In one or two short sentences, in the language the person writes to you "
                            "in, tell them " + ", and ".join(about) + ", so there is time to sort it out. 'you' is the "
                            "person. The facts are exact; add none, and use no tool."
                            + ("\nTOMORROW:\n" + "\n".join(tomorrow_gaps) if tomorrow_gaps else "")
                            + ("\nCLASHES WITH YOUR CALENDAR:\n" + "\n".join(tomorrow_clashes) if tomorrow_clashes else "")
                            + ("\nINSIDE YOUR OWN WORK HOURS:\n" + "\n".join(tomorrow_work) if tomorrow_work else "")
                        ),
                        fallback="\n".join(fallback_parts),
                    )
                    counts["evening"] += 1

            together = rides_leaving_together(
                todays, owner_names=owner_names, local_now=local_now,
                lead_minutes=self.config.ride_lead_minutes, merge_minutes=self.config.ride_merge_minutes,
                digest_at=self._morning_moment(local_now), digest_gap_minutes=self.config.ride_digest_gap_minutes,
            )
            facts = []
            for ride in together:
                activity = ride["activity"]
                if not claim(f"ride:{today.isoformat()}:{activity['id']}:{ride['leg']}"):
                    continue
                verb = "take" if ride["leg"] == "drop_off" else "collect"
                who = _who(activity) or "them"
                place = normalize_text(activity.get("place"))
                facts.append(f"{verb} {who} - {activity.get('title')} at {ride['at']}" + (f", {place}" if place else ""))
            if len(facts) == 1:
                self._queue(
                    user_id=user_id, now=reference, timezone_name=timezone_name,
                    title="Time to leave soon",
                    instruction=(
                        "The person is the one driving shortly. In one short sentence, in the language they write to "
                        "you in, remind them what it is and when. The fact is exact; add nothing, and use no tool.\n"
                        f"DRIVE: {facts[0]}"
                    ),
                    fallback=f"Soon: {facts[0]}.",
                )
                counts["rides"] += 1
            elif facts:
                self._queue(
                    user_id=user_id, now=reference, timezone_name=timezone_name,
                    title="Time to leave soon",
                    instruction=(
                        "The person is the one driving shortly, and these runs of theirs fall close together, so they "
                        "are one trip. In one or two short sentences, in the language they write to you in, remind "
                        "them of all of them in time order as one plan - at the same time means taking everyone "
                        "together and dropping one, then the other. Say each once. The facts are exact; add nothing, "
                        "and use no tool.\nDRIVES:\n" + "\n".join(facts)
                    ),
                    fallback="Soon, one trip:\n" + "\n".join(f"• {fact}" for fact in facts),
                )
                counts["rides"] += 1

            self._nudge_members(
                user_id=user_id, members=members, activities=activities, exceptions=exceptions, todays=todays,
                local_now=local_now, reference=reference, timezone_name=timezone_name, owner_names=owner_names,
                claim=claim, counts=counts,
            )

            if 10 <= local_now.hour < 19 and not week_paused:
                for member in self.database.list_household_members(user_id=user_id):
                    upcoming = household.next_birthday(member.get("birthday"), today)
                    if upcoming is None:
                        continue
                    days_left = (upcoming - today).days
                    if not BIRTHDAY_EARLIEST_DAYS <= days_left <= household.BIRTHDAY_REMINDER_DAYS:
                        continue
                    if not claim(f"birthday:{member['id']}:{upcoming.isoformat()}"):
                        continue
                    turning = household.age_from_birthday(member.get("birthday"), upcoming)
                    fact = (
                        f"{member['name']} ({member.get('role')}) has a birthday on {upcoming.isoformat()} "
                        f"({upcoming.strftime('%A')}), in {days_left} days"
                        + (f", turning {turning}" if turning is not None else "")
                    )
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name,
                        title="A birthday is coming",
                        instruction=(
                            "In one or two short, warm sentences, in the language the person writes to you in, tell "
                            "them this birthday is coming. The fact is exact; add none, and use no tool.\n"
                            f"BIRTHDAY: {fact}"
                        ),
                        fallback=f"A birthday is coming: {fact}.",
                        offer=(
                            "In a few short, warm sentences, in the language the person writes to you in, tell them this "
                            "birthday is coming, and offer to start a ready-made to-do list to get ready for it - for a "
                            "child the party, for anyone else the celebration and the present - with each step due in "
                            "good time, and to help with some of the steps. Ask one question: shall I make the list? "
                            "The fact is exact; add none, and use no tool.\n"
                            f"BIRTHDAY: {fact}"
                        ),
                    )
                    counts["birthdays"] += 1

            profile = self.database.get_household_profile(user_id=user_id) or {}
            ask_on = normalize_text(profile.get("askAgainOn"))
            if (
                profile.get("accountKind") == "family"
                and profile.get("gettingToKnow") == "postponed"
                and ask_on
                and ask_on <= today.isoformat()
                and 10 <= local_now.hour < 19
                and not week_paused
                and claim(f"ask_again:{ask_on}")
            ):
                self._queue(
                    user_id=user_id, now=reference, timezone_name=timezone_name,
                    title="Getting to know your family",
                    instruction="Nothing to say today: write one short line that you are here when they want to set up their family's week.",
                    fallback="Whenever suits you, I can set up your family's week - just tell me who is at home.",
                    offer=(
                        "A few days ago the person said they would rather get to know each other later, so you could hold "
                        "their family's week for them. In one or two light sentences, in the language they write to you "
                        "in, ask whether now is a good time to carry on, and if it is, ask the next thing household does "
                        "not hold yet. No pressure: make it easy to say not now. Use no tool."
                    ),
                )
                self.database.save_household_profile(user_id=user_id, ask_again_on="")
                counts["askedAgain"] += 1
        return {"ok": True, **counts}

    def _nudge_members(
        self, *, user_id: int, members: list[dict[str, Any]], activities: list[dict[str, Any]],
        exceptions: list[dict[str, Any]], todays: list[dict[str, Any]], local_now: datetime, reference: datetime,
        timezone_name: str, owner_names: list[str], claim: Callable[[str], bool], counts: dict[str, int],
    ) -> None:
        """The same week, on the phones of the family members who joined the
        account. A parent gets the morning plan, the evening before and a
        word before each drive of theirs; anyone else only the drives that
        are theirs. Each goes to that phone and is claimed for that person,
        so the account holder's message and theirs never stand in for one
        another. 'you' in each is the person reading it."""

        today = local_now.date()
        tomorrow = today + timedelta(days=1)
        in_morning = self.config.morning_hour <= local_now.hour < self.config.morning_hour + MORNING_WINDOW_HOURS
        in_evening = self.config.evening_hour <= local_now.hour < self.config.evening_hour + EVENING_WINDOW_HOURS
        for member in members:
            wa_id = normalize_text(member.get("waId"))
            if not wa_id:
                continue
            wants = household.member_nudges(member.get("role"))
            names = [str(member.get("name") or "")]
            first = names[0].split(" ")[0] if names[0] else "the person"
            suffix = f":{member['id']}"
            if "morning" in wants and todays and in_morning and claim(f"morning:{today.isoformat()}{suffix}"):
                lines = [describe_activity_line(activity, owner_names, members, viewer_names=names) for activity in todays]
                self._queue(
                    user_id=user_id, now=reference, timezone_name=timezone_name, recipient_wa_id=wa_id,
                    title="Today in your family's week",
                    instruction=(
                        f"It is the morning, and this message is for {first}, a parent in this family writing from "
                        "their own phone. Write them one short WhatsApp message with what today holds for their "
                        "family, in the language the family writes to you in: one bullet per thing, each a few "
                        "words - its time, who it is for, where, who takes and who collects - and where nobody is "
                        "down for a drop-off or pickup yet, say so in that bullet. Say each fact once: no opening "
                        f"line, no sign-off, and no closing line that repeats the bullets. 'you' is {first}; a name "
                        "is somebody else. The facts are exact; add none, and use no tool.\nTODAY:\n" + "\n".join(lines)
                    ),
                    fallback="Today:\n" + "\n".join(f"• {line}" for line in lines),
                )
                counts["morning"] += 1
            if "evening" in wants and in_evening and gap_lines(activities_on(activities, tomorrow), members, owner_names):
                tomorrow_on, _ = self._on_day(
                    user_id=user_id, timezone_name=timezone_name, day=tomorrow, activities=activities, exceptions=exceptions,
                )
                gaps = gap_lines(tomorrow_on, members, owner_names)
                if gaps and claim(f"evening:{tomorrow.isoformat()}{suffix}"):
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name, recipient_wa_id=wa_id,
                        title="Tomorrow still needs someone",
                        instruction=(
                            f"It is the evening, and this message is for {first}, a parent in this family writing from "
                            "their own phone. In one or two short sentences, in the language the family writes to you "
                            "in, tell them what tomorrow still has nobody down for, so there is time to sort it out. "
                            f"'you' is {first}. The facts are exact; add none, and use no tool.\nTOMORROW:\n" + "\n".join(gaps)
                        ),
                        fallback="Tomorrow still needs someone:\n" + "\n".join(f"• {line}" for line in gaps),
                    )
                    counts["evening"] += 1
            if "rides" not in wants:
                continue
            # A parent who got the morning plan is not told again, a minute
            # after it, about a drive that plan already named; a grandparent
            # who hears only about their own drives is told about each one.
            together = rides_leaving_together(
                todays, owner_names=owner_names, local_now=local_now, driver_names=names,
                lead_minutes=self.config.ride_lead_minutes, merge_minutes=self.config.ride_merge_minutes,
                digest_at=self._morning_moment(local_now) if "morning" in wants else None,
                digest_gap_minutes=self.config.ride_digest_gap_minutes,
            )
            facts = []
            for ride in together:
                activity = ride["activity"]
                if not claim(f"ride:{today.isoformat()}:{activity['id']}:{ride['leg']}{suffix}"):
                    continue
                verb = "take" if ride["leg"] == "drop_off" else "collect"
                who = _who(activity, owner_names, names) or "them"
                place = normalize_text(activity.get("place"))
                facts.append(f"{verb} {who} - {activity.get('title')} at {ride['at']}" + (f", {place}" if place else ""))
            if not facts:
                continue
            self._queue(
                user_id=user_id, now=reference, timezone_name=timezone_name, recipient_wa_id=wa_id,
                title="Time to leave soon",
                instruction=(
                    f"This message is for {first}, who is in this family and is the one driving shortly. "
                    + (
                        "In one short sentence, in the language the family writes to you in, remind them what it is "
                        "and when. The fact is exact; add nothing, and use no tool.\nDRIVE: " + facts[0]
                        if len(facts) == 1 else
                        "These runs of theirs fall close together, so they are one trip. In one or two short sentences, "
                        "in the language the family writes to you in, remind them of all of them in time order as one "
                        "plan. Say each once. The facts are exact; add nothing, and use no tool.\nDRIVES:\n" + "\n".join(facts)
                    )
                ),
                fallback=f"Soon: {facts[0]}." if len(facts) == 1 else "Soon, one trip:\n" + "\n".join(f"• {fact}" for fact in facts),
            )
            counts["rides"] += 1

    def _morning_moment(self, local_now: datetime) -> datetime:
        """When today's morning message goes out on this person's clock."""

        return local_now.replace(hour=self.config.morning_hour, minute=0, second=0, microsecond=0)

    def serve_forever(self, stop_event: threading.Event, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                summary = {**self.run_pending(), **self.run_pending_for_groups()}
                sent = sum(int(summary.get(key) or 0) for key in (
                    "morning", "evening", "rides", "birthdays", "askedAgain", "groupEvening", "groupRides",
                ))
                if sent:
                    logger(f"[family-week] queued={sent} {summary}")
            except Exception as exc:  # noqa: BLE001 - keep the nudger alive
                logger(f"[family-week] error: {exc}")
            stop_event.wait(max(30, int(self.config.poll_seconds)))


__all__ = [
    "FamilyWeekNudgeConfig",
    "FamilyWeekNudger",
    "activities_on",
    "describe_activity_line",
    "gap_lines",
    "load_family_week_nudge_config",
    "rides_due",
    "rides_due_for_anyone",
    "rides_leaving_together",
]
