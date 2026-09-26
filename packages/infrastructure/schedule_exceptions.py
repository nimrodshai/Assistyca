"""Exceptions: what the person says is not happening for some days.

"No football this week", "Lahav is sick tomorrow", "we're away over the
holiday", "skip the morning summary while I travel". None of these changes
the usual week or ends a recurring action - it all comes back by itself -
so none of them is an edit. An exception is a stretch of days and the things
it holds: an activity, everything one person does, the family's whole week,
a scheduled action, or all of them. Whatever it covers is not nudged,
reminded or run on those days.

The school calendar (school_days) says when a holiday closes a school for
everybody; an exception is what this family said about itself. Both are
read the same way by the week nudger, and the exceptions also by the
scheduled actions worker: a standing action is skipped on a day an exception
covers, and a reminder due in one waits until the day after it ends, so a
reminder is never lost to a pause.

Dates are the person's own local dates, first and last day both included.
Nothing here reads the database or the network.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Iterable

from packages.infrastructure.household import clean
from packages.infrastructure.household import name_key

# What an exception can hold. The first three are the family's week; the
# last two are what the person has scheduled.
TARGET_KINDS = ("activity", "person", "family_week", "action", "all_actions")
WEEK_TARGET_KINDS = frozenset({"activity", "person", "family_week"})
ACTION_TARGET_KINDS = frozenset({"action", "all_actions"})
# A pause is for days or weeks. A year is far past any holiday or trip, and
# anything longer is something stopping, which is a removal, not a pause.
MAX_EXCEPTION_DAYS = 366
MAX_REASON_LENGTH = 160
MAX_LISTED_EXCEPTIONS = 20


def parse_day(value: Any) -> date | None:
    text = clean(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def normalize_targets(raw: Any) -> list[dict[str, str]]:
    """The targets as they are kept: each a kind and, where it needs one, a ref."""

    targets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        kind = clean(entry.get("kind")).lower()
        ref = clean(entry.get("ref"), 120)
        if kind not in TARGET_KINDS:
            continue
        if kind in {"family_week", "all_actions"}:
            ref = ""
        elif not ref:
            continue
        if kind == "person":
            ref_key = name_key(ref)
        else:
            ref_key = ref
        if (kind, ref_key) in seen:
            continue
        seen.add((kind, ref_key))
        targets.append({"kind": kind, "ref": ref})
    return targets


def covers_day(exception: dict[str, Any], day: date) -> bool:
    starts, ends = parse_day(exception.get("startsOn")), parse_day(exception.get("endsOn"))
    return bool(starts and ends and starts <= day <= ends)


def _targets(exception: dict[str, Any]) -> list[dict[str, str]]:
    return normalize_targets(exception.get("targets"))


def activity_exception(
    activity: dict[str, Any], exceptions: Iterable[dict[str, Any]], day: date,
) -> dict[str, Any] | None:
    """The exception that holds this activity on that day, or None."""

    activity_id = str(activity.get("id") or "")
    people = {name_key(who) for who in (activity.get("who") or [])}
    for exception in exceptions:
        if not covers_day(exception, day):
            continue
        for target in _targets(exception):
            if target["kind"] == "family_week":
                return exception
            if target["kind"] == "activity" and target["ref"] == activity_id:
                return exception
            if target["kind"] == "person" and name_key(target["ref"]) in people:
                return exception
    return None


def activities_not_excepted(
    activities: list[dict[str, Any]], exceptions: Iterable[dict[str, Any]], day: date,
) -> list[dict[str, Any]]:
    held = list(exceptions)
    return [activity for activity in activities if activity_exception(activity, held, day) is None]


def family_week_paused(exceptions: Iterable[dict[str, Any]], day: date) -> bool:
    """Whether the family's whole week is on hold that day: no plan, no
    birthday, nothing about the week at all."""

    return any(
        covers_day(exception, day) and any(target["kind"] == "family_week" for target in _targets(exception))
        for exception in exceptions
    )


def action_exception(
    action_id: int, exceptions: Iterable[dict[str, Any]], day: date,
) -> dict[str, Any] | None:
    """The exception that holds this scheduled action on that day, or None."""

    for exception in exceptions:
        if not covers_day(exception, day):
            continue
        for target in _targets(exception):
            if target["kind"] == "all_actions":
                return exception
            if target["kind"] == "action" and target["ref"] == str(int(action_id or 0)):
                return exception
    return None


def held_until(run_at_local: datetime, exception: dict[str, Any]) -> datetime:
    """When a reminder held by a pause goes instead: the same time on the
    day after the pause ends."""

    ends = parse_day(exception.get("endsOn")) or run_at_local.date()
    return run_at_local.replace(
        year=ends.year, month=ends.month, day=ends.day,
    ) + timedelta(days=1)


def describe_exception(
    exception: dict[str, Any],
    *,
    activities: dict[str, dict[str, Any]] | None = None,
    actions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One exception as the assistant reads it: its days, the person's own
    reason, and what it holds in words."""

    covers = []
    for target in _targets(exception):
        kind, ref = target["kind"], target["ref"]
        if kind == "family_week":
            covers.append("the whole family week")
        elif kind == "all_actions":
            covers.append("every standing action and reminder")
        elif kind == "person":
            covers.append(f"everything {ref} does")
        elif kind == "activity":
            activity = (activities or {}).get(ref) or {}
            title = clean(activity.get("title")) or "an activity no longer in the week"
            who = ", ".join(activity.get("who") or [])
            covers.append(f"{title} ({who}), activity {ref}" if who else f"{title}, activity {ref}")
        elif kind == "action":
            action = (actions or {}).get(ref) or {}
            payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
            name = clean(payload.get("title") or payload.get("messageText") or payload.get("text"), 80)
            covers.append(f"{name or 'a scheduled action no longer set'}, scheduled {ref}")
    described = {
        "id": int(exception.get("id") or 0),
        "from": clean(exception.get("startsOn")),
        "until": clean(exception.get("endsOn")),
        "covers": covers,
    }
    if clean(exception.get("reason")):
        described["reason"] = clean(exception.get("reason"), MAX_REASON_LENGTH)
    return described


__all__ = [
    "ACTION_TARGET_KINDS",
    "MAX_EXCEPTION_DAYS",
    "MAX_LISTED_EXCEPTIONS",
    "MAX_REASON_LENGTH",
    "TARGET_KINDS",
    "WEEK_TARGET_KINDS",
    "action_exception",
    "activities_not_excepted",
    "activity_exception",
    "covers_day",
    "describe_exception",
    "family_week_paused",
    "held_until",
    "normalize_targets",
    "parse_day",
]
