"""The homework check: offered once, at the first one o'clock.

A new family whose children are at school is asked, once, whether they
would like the children's homework checked for them. The question goes out
at the first 13:00 on their own clock after they joined - school is out or
nearly out, and the day's homework is fresh - and never on a Saturday, when
it waits for Sunday's. It is offered only in Israel for now, where the
school platforms are known, and only to a family with at least one child of
school age: a family of toddlers is never asked.

It goes as plain text or not at all. Anyone who joined has written to us -
the account opens on their first message - so the first 13:00 almost
always falls inside Meta's 24-hour window; when it does not (they joined on
a Friday and Saturday was skipped, say), the question is dropped rather
than sent as a template, and it is never asked again.

A yes is answered with a link to a private page where the parent types the
platform, the username and the password. The login never passes through
the chat: it is encrypted the moment it arrives (credential_vault) and is
never shown again, to the assistant or to anyone. It can be removed in the
chat whenever they like.
"""

from __future__ import annotations

import os
import re
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Iterable

from packages.infrastructure import household

# The homework check is frozen for every account: nothing offers it, the
# tool that hands out the login page is not on offer, and the page itself is
# closed. The code and every kept login stay as they are, so setting this to
# 1 brings all of it back. A login can still be removed while it is frozen.
HOMEWORK_CHECK_SWITCH = "PORTAL_HOMEWORK_CHECK_ENABLED"
# The tools that only make sense while the check is open.
HOMEWORK_OPEN_TOOLS = frozenset({"homework_login_link"})

HOMEWORK_OFFER_HOUR = 13
# How late the question may still go: a poll a little after one still asks.
HOMEWORK_OFFER_WINDOW_HOURS = 2
# Saturday, Python's weekday 5: no homework talk on Shabbat.
HOMEWORK_OFFER_SKIPPED_WEEKDAY = 5
HOMEWORK_OFFER_TIMEZONES = frozenset({"Asia/Jerusalem"})
HOMEWORK_OFFER_NUDGE_KEY = "homework-offer"



def check_open() -> bool:
    """Whether the homework check is open at all (HOMEWORK_CHECK_SWITCH)."""

    return str(os.getenv(HOMEWORK_CHECK_SWITCH) or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


# First grade in Israel starts the year a child turns six; the last year of
# school is twelfth grade, at seventeen or eighteen.
SCHOOL_AGE_FIRST = 6
SCHOOL_AGE_LAST = 18
# Said of a place a child goes, it means they are not at school yet.
_BEFORE_SCHOOL_WORDS = re.compile(
    r"(?:^|[\s\-/,(])(?:gan|kindergarten|kinder garten|preschool|pre-school|nursery|daycare|day care|"
    r"גן|גנון|מעון|פעוטון|משפחתון)(?:$|[\s\-/,)])",
    re.IGNORECASE,
)

HOMEWORK_LINK_PREFIX = "/homework/"
HOMEWORK_LINK_TTL_HOURS = 48
HOMEWORK_PLATFORMS: dict[str, dict[str, str]] = {
    "mashov": {"en": "Mashov", "he": "משו\"ב"},
    "webtop": {"en": "Webtop (Smart School)", "he": "וובטופ (סמארט סקול)"},
    "google_classroom": {"en": "Google Classroom", "he": "Google Classroom"},
    "other": {"en": "Something else", "he": "משהו אחר"},
}
MAX_LOGIN_FIELD_LENGTH = 200
MAX_SCHOOL_CODE_LENGTH = 20
MAX_OTHER_PLATFORM_LENGTH = 80


def first_offer_moment(registered_at: datetime) -> datetime:
    """The first 13:00 after the account opened, on the clock registered_at
    is given in, Saturdays passed over."""

    moment = registered_at.replace(hour=HOMEWORK_OFFER_HOUR, minute=0, second=0, microsecond=0)
    if moment <= registered_at:
        moment += timedelta(days=1)
    while moment.weekday() == HOMEWORK_OFFER_SKIPPED_WEEKDAY:
        moment += timedelta(days=1)
    return moment


def offer_due(registered_at: datetime | None, local_now: datetime) -> bool:
    """Whether now is the account's first 13:00. Both times are on the
    family's own clock. An account that opened before its last 13:00 has
    had its moment, so an account from before this check existed is never
    asked."""

    if registered_at is None:
        return False
    moment = first_offer_moment(registered_at.astimezone(local_now.tzinfo))
    return moment <= local_now < moment + timedelta(hours=HOMEWORK_OFFER_WINDOW_HOURS)


def offered_where(timezone_name: str) -> bool:
    return str(timezone_name or "") in HOMEWORK_OFFER_TIMEZONES


def school_children(members: Iterable[dict[str, Any]] | None, today: date) -> list[str]:
    """The names of the children at school: of school age when their age is
    known, and otherwise any child with a school that is not a kindergarten.
    A child with neither said is not counted - the question is for a family
    we know has a pupil."""

    names: list[str] = []
    for member in members or ():
        if household.normalize_role(member.get("role")) != "child":
            continue
        name = household.clean(member.get("name"), household.MAX_NAME_LENGTH)
        if not name:
            continue
        age = household.current_age(member.get("age"), member.get("ageNotedOn"), today, member.get("birthday"))
        school = household.clean(member.get("school"))
        if age is not None:
            if SCHOOL_AGE_FIRST <= int(age) <= SCHOOL_AGE_LAST:
                names.append(name)
        elif school and not _BEFORE_SCHOOL_WORDS.search(f" {school.lower()} "):
            names.append(name)
    return names


def offer_message(children: list[str]) -> dict[str, str]:
    """The question, as the instruction the assistant writes it from and the
    plain sentence that stands in when it cannot."""

    who = ", ".join(children)
    instruction = (
        "It is one o'clock, and school is out or nearly. Ask the person, once and lightly, in the language they "
        "write to you in, whether they would like you to check the children's homework for them every day "
        "when school ends, so they know what there is without logging in themselves. Name the children. Say "
        "in a few words how it works: they give you the login for the school's platform - Mashov, Webtop or "
        "whatever their school uses - on a private page, and it is kept encrypted and only ever used for this. "
        "Make it easy to say no. One or two short sentences and the question; no list, no link yet. If they "
        "say yes, call homework_login_link and send them the page. Never ask for a username or a password "
        "in the chat. Use no tool now.\n"
        f"CHILDREN AT SCHOOL: {who}"
    )
    fallback = (
        f"Would you like me to check {who}'s homework every day when school ends? "
        "You'd give me the school platform's login on a private page, and it stays encrypted with me."
    )
    return {"title": "Homework check", "instruction": instruction, "fallback": fallback}


def normalize_platform(value: Any) -> str:
    platform = str(value or "").strip().lower()
    return platform if platform in HOMEWORK_PLATFORMS else ""


def platform_label(platform: str, language: str = "en") -> str:
    labels = HOMEWORK_PLATFORMS.get(platform) or {}
    return labels.get(language) or labels.get("en") or platform


def clean_login_form(payload: dict[str, Any]) -> tuple[dict[str, str], str]:
    """What the page sent, checked: the fields to keep, or what is wrong
    with them. The password is kept as typed - spaces and all."""

    platform = normalize_platform(payload.get("platform"))
    if not platform:
        return {}, "platform_required"
    other = household.clean(payload.get("otherPlatform"), MAX_OTHER_PLATFORM_LENGTH) if platform == "other" else ""
    if platform == "other" and not other:
        return {}, "platform_required"
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password.strip():
        return {}, "login_required"
    if len(username) > MAX_LOGIN_FIELD_LENGTH or len(password) > MAX_LOGIN_FIELD_LENGTH:
        return {}, "too_long"
    school_code = re.sub(r"\s+", "", str(payload.get("schoolCode") or ""))
    if len(school_code) > MAX_SCHOOL_CODE_LENGTH:
        return {}, "too_long"
    return {
        "platform": platform,
        "otherPlatform": other,
        "schoolCode": school_code,
        "username": username,
        "password": password,
    }, ""


__all__ = [
    "HOMEWORK_LINK_PREFIX",
    "HOMEWORK_LINK_TTL_HOURS",
    "HOMEWORK_OFFER_HOUR",
    "HOMEWORK_OFFER_NUDGE_KEY",
    "HOMEWORK_PLATFORMS",
    "clean_login_form",
    "first_offer_moment",
    "normalize_platform",
    "offer_due",
    "offer_message",
    "offered_where",
    "platform_label",
    "school_children",
]
