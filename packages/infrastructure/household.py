"""The family an account keeps, and the week it runs.

A family account is about the people in it and the afternoons they share:
who the partner is and how to reach them, the children and where they are
each day, which activity is on which day and who drives to it. None of that
is a passing fact. It is kept in its own tables, apart from the short
remembered facts that give way to newer ones, and it goes only when the
person says so.

This module holds the plain rules the store, the chat tools and the page
share: what a role is, how a day and a time are written, who "me" is, and
the compact shape the assistant reads the family in. Nothing here touches
the database or the network.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from typing import Iterable

ACCOUNT_KINDS = ("business", "family")
MEMBER_ROLES = ("partner", "child", "other")
# The week as it is lived where most of these families are: it starts on
# Sunday. Stored as these codes, shown in the person's own words.
WEEKDAY_CODES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
# Python counts Monday as 0; this maps a date's weekday() to a code.
PYTHON_WEEKDAY_TO_CODE = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
GETTING_TO_KNOW_STATUSES = ("not_started", "in_progress", "postponed", "done")

MAX_MEMBERS = 20
MAX_ACTIVITIES = 80
MAX_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_TEXT_LENGTH = 240

# Words a person uses for themselves when saying who drives. The assistant
# is asked to write "me"; the others are here because people type.
_SELF_WORDS = {"me", "myself", "i", "owner", "אני", "אני עצמי"}
_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def name_key(value: Any) -> str:
    """How two spellings of one name are told to be the same person."""

    return clean(value, MAX_NAME_LENGTH).casefold()


def normalize_account_kind(value: Any) -> str:
    return "family" if clean(value).lower() == "family" else "business"


def normalize_role(value: Any) -> str:
    role = clean(value).lower()
    return role if role in MEMBER_ROLES else "other"


def normalize_email_address(value: Any) -> str:
    text = clean(value, 200)
    return text if _EMAIL_RE.match(text) else ""


def normalize_time(value: Any) -> str:
    """"7:30", "07.30", "17" -> "07:30", "07:30", "17:00"; anything else -> ""."""

    match = _TIME_RE.match(str(value or ""))
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def normalize_days(values: Iterable[Any]) -> list[str]:
    """Weekday codes, each once, in week order."""

    wanted = {clean(value).lower()[:3] for value in values or ()}
    return [code for code in WEEKDAY_CODES if code in wanted]


def weekday_code(day: date) -> str:
    return PYTHON_WEEKDAY_TO_CODE[day.weekday()]


def is_self(who: Any, owner_names: Iterable[str] = ()) -> bool:
    """Whether "who drives" names the account holder."""

    text = name_key(who)
    if not text:
        return False
    if text in _SELF_WORDS:
        return True
    names = {name_key(name) for name in owner_names if name_key(name)}
    firsts = {name.split(" ")[0] for name in names}
    return text in names or text in firsts


def current_age(age: Any, noted_on: Any, today: date) -> int | None:
    """An age said once keeps counting: said as 4 two years ago is 6 now."""

    try:
        years = int(age)
    except (TypeError, ValueError):
        return None
    try:
        noted = date.fromisoformat(str(noted_on or "")[:10])
    except ValueError:
        return years
    passed = today.year - noted.year - ((today.month, today.day) < (noted.month, noted.day))
    return years + max(0, passed)


def activity_gaps(activity: dict[str, Any]) -> list[str]:
    """What an activity still has nobody down for."""

    gaps = []
    if not clean(activity.get("dropOffBy")):
        gaps.append("drop_off")
    if not clean(activity.get("pickUpBy")):
        gaps.append("pick_up")
    return gaps


def describe_household(
    *,
    profile: dict[str, Any] | None,
    members: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    """The family as the assistant reads it on every turn."""

    profile = profile or {}
    return {
        "accountKind": normalize_account_kind(profile.get("accountKind")),
        "gettingToKnow": {
            "status": clean(profile.get("gettingToKnow")) or "not_started",
            "askAgainOn": clean(profile.get("askAgainOn")) or None,
        },
        "members": [
            {
                key: value
                for key, value in {
                    "name": member.get("name"),
                    "role": member.get("role"),
                    "age": current_age(member.get("age"), member.get("ageNotedOn"), today),
                    "school": member.get("school") or None,
                    "email": member.get("email") or None,
                    "phone": member.get("phone") or None,
                    "notes": member.get("notes") or None,
                }.items()
                if value not in (None, "")
            }
            for member in members
        ],
        "week": [
            {
                key: value
                for key, value in {
                    "id": activity.get("id"),
                    "title": activity.get("title"),
                    "who": activity.get("who") or None,
                    "days": activity.get("days"),
                    "start": activity.get("startTime") or None,
                    "end": activity.get("endTime") or None,
                    "place": activity.get("place") or None,
                    "dropOffBy": activity.get("dropOffBy") or None,
                    "pickUpBy": activity.get("pickUpBy") or None,
                    "notes": activity.get("notes") or None,
                    "nobodyDownFor": activity_gaps(activity) or None,
                }.items()
                if value not in (None, "", [])
            }
            for activity in activities
        ],
    }


def should_describe_household(profile: dict[str, Any] | None, members: list[Any], activities: list[Any]) -> bool:
    """A family account always has the block; any other account once it
    keeps someone or something, so a business owner's partner is known too."""

    return normalize_account_kind((profile or {}).get("accountKind")) == "family" or bool(members) or bool(activities)


__all__ = [
    "ACCOUNT_KINDS",
    "GETTING_TO_KNOW_STATUSES",
    "MAX_ACTIVITIES",
    "MAX_MEMBERS",
    "MEMBER_ROLES",
    "WEEKDAY_CODES",
    "activity_gaps",
    "clean",
    "current_age",
    "describe_household",
    "is_self",
    "name_key",
    "normalize_account_kind",
    "normalize_days",
    "normalize_email_address",
    "normalize_role",
    "normalize_time",
    "should_describe_household",
    "weekday_code",
]
