"""The nudges that make a family's week something held for them.

Three moments, each once, on the person's own clock:

* the morning: what today holds, who takes and who collects, and anything
  nobody is down for yet;
* the evening before: a drop-off or pickup tomorrow that still has nobody,
  while there is time to sort it out;
* the ride: shortly before the account holder is the one driving, a word
  that it is time to leave;
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

import os
import threading
from dataclasses import dataclass
from datetime import date
from datetime import datetime
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
DEFAULT_POLL_SECONDS = 120
# How late a moment may still be told. A poll that runs a little after the
# hour still counts; one that runs hours later has missed it.
MORNING_WINDOW_HOURS = 3
EVENING_WINDOW_HOURS = 2
# A birthday is raised a month ahead. One learned later is still raised
# while there is a little time, but not in its last days.
BIRTHDAY_EARLIEST_DAYS = 3


@dataclass(frozen=True)
class FamilyWeekNudgeConfig:
    enabled: bool = True
    morning_hour: int = DEFAULT_MORNING_HOUR
    evening_hour: int = DEFAULT_EVENING_HOUR
    ride_lead_minutes: int = DEFAULT_RIDE_LEAD_MINUTES
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
        poll_seconds=max(30, _parse_int(os.getenv("PORTAL_FAMILY_NUDGE_POLL_SECONDS"), DEFAULT_POLL_SECONDS)),
        school_calendar=normalize_text(os.getenv("PORTAL_FAMILY_SCHOOL_CALENDAR")).lower()
        not in {"0", "false", "no", "off", "disabled"},
    )


# -- what is due, in code -----------------------------------------------------


def activities_on(activities: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    code = household.weekday_code(day)
    return [activity for activity in activities if code in (activity.get("days") or [])]


def _who(activity: dict[str, Any]) -> str:
    return ", ".join(activity.get("who") or [])


def _ride_word(value: Any, owner_names: list[str]) -> str:
    return "you" if household.is_self(value, owner_names) else normalize_text(value)


def describe_activity_line(activity: dict[str, Any], owner_names: list[str]) -> str:
    """One activity as a plain line: time, what, for whom, who takes and collects."""

    parts = []
    times = normalize_text(activity.get("startTime"))
    if times and normalize_text(activity.get("endTime")):
        times = f"{times}-{activity['endTime']}"
    head = f"{times} {activity.get('title')}".strip()
    if _who(activity):
        head += f" ({_who(activity)})"
    parts.append(head)
    takes = _ride_word(activity.get("dropOffBy"), owner_names)
    collects = _ride_word(activity.get("pickUpBy"), owner_names)
    parts.append(f"takes: {takes}" if takes else "nobody takes them yet")
    parts.append(f"collects: {collects}" if collects else "nobody collects them yet")
    return ", ".join(parts)


def gap_lines(activities: list[dict[str, Any]]) -> list[str]:
    lines = []
    for activity in activities:
        gaps = household.activity_gaps(activity)
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
    goes into the room and is addressed to them.
    """

    due = []
    for activity in activities_on(activities, local_now.date()):
        for leg, who_key, time_key in (("drop_off", "dropOffBy", "startTime"), ("pick_up", "pickUpBy", "endTime")):
            driver = normalize_text(activity.get(who_key))
            clock = household.normalize_time(activity.get(time_key))
            if not driver or not clock:
                continue
            hour, minute = (int(part) for part in clock.split(":"))
            moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment - timedelta(minutes=lead_minutes) <= local_now < moment:
                due.append({"activity": activity, "leg": leg, "at": clock, "driver": driver})
    return due


def rides_due(
    activities: list[dict[str, Any]],
    *,
    owner_names: list[str],
    local_now: datetime,
    lead_minutes: int,
) -> list[dict[str, Any]]:
    """The drives today the account holder is down for, whose leaving time
    has come: within lead_minutes before it, and not yet past."""

    due = []
    for activity in activities_on(activities, local_now.date()):
        for leg, who_key, time_key in (("drop_off", "dropOffBy", "startTime"), ("pick_up", "pickUpBy", "endTime")):
            if not household.is_self(activity.get(who_key), owner_names):
                continue
            clock = household.normalize_time(activity.get(time_key))
            if not clock:
                continue
            hour, minute = (int(part) for part in clock.split(":"))
            moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment - timedelta(minutes=lead_minutes) <= local_now < moment:
                due.append({"activity": activity, "leg": leg, "at": clock})
    return due


# -- the nudger ----------------------------------------------------------------


class FamilyWeekNudger:
    def __init__(
        self,
        database: Any,
        *,
        config: FamilyWeekNudgeConfig | None = None,
        school_calendar: SchoolCalendar | None = None,
    ) -> None:
        """school_calendar is what says whether a day is really on. Without
        one every day is the usual week, which is what a test wants."""

        self.database = database
        self.config = config or load_family_week_nudge_config()
        self.school_calendar = school_calendar

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
        wa_id = normalize_text(connection.get("ownerWaId"))
        if not wa_id:
            linked = self.database.list_user_whatsapp_numbers(user_id=user_id)
            wa_id = normalize_text(linked[0].get("waId")) if linked else ""
        inferred = infer_timezone_from_wa_id(wa_id) if wa_id else ""
        return inferred or "UTC"

    def _owner_names(self, user_id: int) -> list[str]:
        user = self.database.get_user_by_id(user_id) or {}
        names = [normalize_text(user.get("displayName"))]
        for fact in self.database.list_account_facts(user_id=user_id):
            if fact.get("key") == "name":
                names.append(normalize_text(fact.get("fact")).removeprefix("Their name is ").rstrip("."))
        return [name for name in names if name]

    def _queue(self, *, user_id: int, now: datetime, timezone_name: str, title: str, instruction: str, fallback: str, offer: str = "") -> None:
        connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        owner_wa_id = normalize_text(connection.get("ownerWaId"))
        if not owner_wa_id:
            linked = self.database.list_user_whatsapp_numbers(user_id=user_id)
            owner_wa_id = normalize_text(linked[0].get("waId")) if linked else ""
        payload: dict[str, Any] = {
            "title": title,
            "instruction": instruction,
            "fallbackText": fallback,
            "oneOff": True,
            "source": NUDGE_SOURCE,
        }
        if offer:
            payload["offerInstruction"] = offer
        self.database.create_scheduled_action(
            user_id=user_id,
            action_type=STANDING_TASK_ACTION_TYPE,
            channel="whatsapp" if owner_wa_id else "portal",
            recipient_ref="owner",
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
            exceptions = self.database.list_schedule_exceptions(
                user_id=user_id, group_id=group_id, ending_on_or_after=today.isoformat(),
            )
            claim = lambda key: self.database.claim_household_nudge(  # noqa: E731
                user_id=user_id, nudge_key=f"group:{group_id}:{key}",
            )

            tomorrow = today + timedelta(days=1)
            in_evening = self.config.evening_hour <= local_now.hour < self.config.evening_hour + EVENING_WINDOW_HOURS
            tomorrow_gaps = []
            if in_evening and gap_lines(activities_on(activities, tomorrow)):
                tomorrow_on, _ = self._on_day(
                    user_id=user_id, group_id=group_id, timezone_name=timezone_name, day=tomorrow,
                    activities=activities, exceptions=exceptions,
                )
                tomorrow_gaps = gap_lines(tomorrow_on)
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
                    lines = [describe_activity_line(activity, owner_names) for activity in todays]
                    gaps = gap_lines(todays)
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name,
                        title="Today in your family's week",
                        instruction=(
                            "It is the morning. Write the person one short WhatsApp message with what today holds for "
                            "their family, in the language they write to you in: each thing with its time and who takes "
                            "and collects, and, plainly and last, anything nobody is down for yet. 'you' is the person. "
                            + (
                                "CALENDAR is what the school calendar says about today: mention it in a few words only "
                                "where it bears on what is listed, such as an earlier finish. " if today_calendar else ""
                            )
                            + "The facts are exact; add none, and use no tool.\nTODAY:\n" + "\n".join(lines)
                            + ("\nNOBODY DOWN FOR:\n" + "\n".join(gaps) if gaps else "")
                            + (f"\nCALENDAR: {describe_day(today, today_calendar)}" if today_calendar else "")
                        ),
                        fallback="Today:\n" + "\n".join(f"• {line}" for line in lines),
                    )
                    counts["morning"] += 1

            tomorrow = today + timedelta(days=1)
            in_evening = self.config.evening_hour <= local_now.hour < self.config.evening_hour + EVENING_WINDOW_HOURS
            tomorrow_gaps = []
            if in_evening and gap_lines(activities_on(activities, tomorrow)):
                tomorrow_on, _ = self._on_day(
                    user_id=user_id, timezone_name=timezone_name, day=tomorrow, activities=activities,
                    exceptions=exceptions,
                )
                tomorrow_gaps = gap_lines(tomorrow_on)
            if tomorrow_gaps:
                if claim(f"evening:{tomorrow.isoformat()}"):
                    self._queue(
                        user_id=user_id, now=reference, timezone_name=timezone_name,
                        title="Tomorrow still needs someone",
                        instruction=(
                            "It is the evening. In one or two short sentences, in the language the person writes to you "
                            "in, tell them what tomorrow still has nobody down for, so there is time to sort it out. The "
                            "facts are exact; add none, and use no tool.\nTOMORROW:\n" + "\n".join(tomorrow_gaps)
                        ),
                        fallback="Tomorrow still needs someone:\n" + "\n".join(f"• {line}" for line in tomorrow_gaps),
                    )
                    counts["evening"] += 1

            for ride in rides_due(todays, owner_names=owner_names, local_now=local_now, lead_minutes=self.config.ride_lead_minutes):
                activity = ride["activity"]
                if not claim(f"ride:{today.isoformat()}:{activity['id']}:{ride['leg']}"):
                    continue
                verb = "take" if ride["leg"] == "drop_off" else "collect"
                who = _who(activity) or "them"
                place = normalize_text(activity.get("place"))
                fact = f"{verb} {who} - {activity.get('title')} at {ride['at']}" + (f", {place}" if place else "")
                self._queue(
                    user_id=user_id, now=reference, timezone_name=timezone_name,
                    title="Time to leave soon",
                    instruction=(
                        "The person is the one driving shortly. In one short sentence, in the language they write to "
                        "you in, remind them what it is and when. The fact is exact; add nothing, and use no tool.\n"
                        f"DRIVE: {fact}"
                    ),
                    fallback=f"Soon: {fact}.",
                )
                counts["rides"] += 1

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
]
