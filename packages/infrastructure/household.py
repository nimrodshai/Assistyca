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
from datetime import timedelta
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


_BIRTHDAY_RE = re.compile(r"^\s*(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s*$")
BIRTHDAY_REMINDER_DAYS = 30

# The ready-made birthday list: each step with how many days before the
# birthday it is due. A child's birthday is a party; anyone else's is a
# celebration and a present. The assistant words each step in the person's
# language and leaves out what does not fit; the days come from here.
BIRTHDAY_LIST_TEMPLATES: dict[str, tuple[tuple[str, int], ...]] = {
    "child": (
        ("Decide what kind of party, where, and roughly how many children", 28),
        ("Book the place or the activity", 24),
        ("Put together the guest list", 24),
        ("Send the invitations", 21),
        ("Plan the celebration at kindergarten or school", 10),
        ("Confirm who is coming", 7),
        ("Order or bake the cake", 7),
        ("Buy the present", 7),
        ("Party bags for the guests", 5),
        ("Decorations, candles, plates and drinks", 3),
        ("Charge the phone or camera for photos", 1),
    ),
    "adult": (
        ("Decide how to celebrate: dinner, a trip, a party or a quiet day", 28),
        ("Book the restaurant, place or tickets", 21),
        ("Arrange a babysitter if needed", 14),
        ("Choose and order the present", 14),
        ("Invite whoever should be there", 14),
        ("Order the cake or flowers", 5),
        ("Write the card", 2),
    ),
}


def birthday_template_kind(role: Any) -> str:
    return "child" if normalize_role(role) == "child" else "adult"


def normalize_birthday(value: Any) -> str:
    """"2021-10-12" stays; "10-12" (no year given) becomes "--10-12";
    anything that is not a real day becomes ""."""

    text = str(value or "").strip()
    if text.startswith("--"):
        text = text[2:]
    match = _BIRTHDAY_RE.match(text)
    if not match:
        return ""
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    try:
        date(int(year) if year else 2000, month, day)
    except ValueError:
        return ""
    return f"{year}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"


def _birthday_parts(birthday: Any) -> tuple[int | None, int, int] | None:
    text = normalize_birthday(birthday)
    if not text:
        return None
    if text.startswith("--"):
        return None, int(text[2:4]), int(text[5:7])
    return int(text[:4]), int(text[5:7]), int(text[8:10])


def _on_year(year: int, month: int, day: int) -> date:
    # 29 February is kept on 28 February in a year without it.
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def next_birthday(birthday: Any, today: date) -> date | None:
    """The next time the birthday comes round, today included."""

    parts = _birthday_parts(birthday)
    if parts is None:
        return None
    _year, month, day = parts
    upcoming = _on_year(today.year, month, day)
    return upcoming if upcoming >= today else _on_year(today.year + 1, month, day)


def age_from_birthday(birthday: Any, today: date) -> int | None:
    parts = _birthday_parts(birthday)
    if parts is None or parts[0] is None:
        return None
    year, month, day = parts
    return today.year - year - ((today.month, today.day) < (month, day))


def birthday_list_items(role: Any, birthday_on: date, today: date) -> list[dict[str, Any]]:
    """The template for this person, each step with its due date. A step
    whose day has already gone is due today rather than overdue."""

    return [
        {"step": index, "text": text, "dueOn": max(today, birthday_on - timedelta(days=days)).isoformat()}
        for index, (text, days) in enumerate(BIRTHDAY_LIST_TEMPLATES[birthday_template_kind(role)], start=1)
    ]


def current_age(age: Any, noted_on: Any, today: date, birthday: Any = "") -> int | None:
    """An age said once keeps counting: said as 4 two years ago is 6 now.
    A birthday with its year, when there is one, is the better source."""

    from_birthday = age_from_birthday(birthday, today)
    if from_birthday is not None:
        return from_birthday
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


# What a week has to hold before it can be run for a family. The point of
# the week is the afternoons: a child ends somewhere at a time, and somebody
# has to be there. So a child nobody has told us anything about, an activity
# with no day or no finishing time, and above all a pickup with nobody down
# for it are each something still to ask about - in that order, because a
# person answers the big thing before the small one.
WEEK_GAP_KINDS = ("people", "week", "days", "times", "drop_off", "pick_up")


def _activity_time(activity: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean(activity.get(key))
        if value:
            return value
    return ""


def week_setup_gaps(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """What the week still needs before it can be looked after, in ask order.

    Each gap says what is missing and who or what it is about, so the
    assistant asks the next real question instead of deciding for itself that
    it knows enough. An empty list is a week that is ready: every child has
    their days, and every one of those days has someone down for the pickup.
    """

    people = [member for member in (members or ()) if clean(member.get("name"), MAX_NAME_LENGTH)]
    week = list(activities or ())
    gaps: list[dict[str, Any]] = []
    if not people:
        return [{"missing": "people"}]

    spoken_for = {name_key(name) for activity in week for name in (activity.get("who") or ())}
    for member in people:
        if normalize_role(member.get("role")) != "child":
            continue
        name = clean(member.get("name"), MAX_NAME_LENGTH)
        if name_key(name) not in spoken_for:
            gaps.append({"missing": "week", "who": name})

    for activity in week:
        title = clean(activity.get("title"), MAX_TITLE_LENGTH)
        where = {"activity": title}
        if activity.get("id"):
            where["id"] = activity["id"]
        if not list(activity.get("days") or ()):
            gaps.append({"missing": "days", **where})
        if not _activity_time(activity, "end", "endTime"):
            gaps.append({"missing": "times", **where})
        for missing in activity_gaps({
            "dropOffBy": _activity_time(activity, "dropOffBy"),
            "pickUpBy": _activity_time(activity, "pickUpBy"),
        }):
            gaps.append({"missing": missing, **where})

    order = {kind: index for index, kind in enumerate(WEEK_GAP_KINDS)}
    return sorted(gaps, key=lambda gap: order.get(str(gap.get("missing")), len(WEEK_GAP_KINDS)))


def week_is_ready(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
) -> bool:
    """Whether the week can be run: everyone placed, and every pickup taken."""

    return not week_setup_gaps(members, activities)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


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
                    "age": current_age(member.get("age"), member.get("ageNotedOn"), today, member.get("birthday")),
                    "birthday": member.get("birthday") or None,
                    "nextBirthday": _iso(next_birthday(member.get("birthday"), today)),
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
    "BIRTHDAY_LIST_TEMPLATES",
    "BIRTHDAY_REMINDER_DAYS",
    "activity_gaps",
    "age_from_birthday",
    "birthday_list_items",
    "birthday_template_kind",
    "clean",
    "current_age",
    "describe_household",
    "is_self",
    "name_key",
    "next_birthday",
    "normalize_birthday",
    "normalize_account_kind",
    "normalize_days",
    "normalize_email_address",
    "normalize_role",
    "normalize_time",
    "should_describe_household",
    "weekday_code",
    "week_is_ready",
    "week_setup_gaps",
    "WEEK_GAP_KINDS",
]
