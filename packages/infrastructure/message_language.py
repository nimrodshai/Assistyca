"""Which language a person's messages from Assistyca come in.

Every template Assistyca sends outside Meta's service window exists in
Hebrew and in English under one name, and the person gets the one they
write in. Nobody is asked: the first guess is the script of the name they
registered with, and from then on the script of each message they send is
what decides, so someone who typed "Dana" and writes in Hebrew gets Hebrew
from their second message on. The chat's own replies already follow the
language the person writes in; this keeps the scheduled messages in step.

It is kept per person, like the address form beside it (person_address):
the account holder's on the profile, a family member's on their own row. A
partner who writes in English from their phone gets English, and never
turns the account holder's messages into it.
"""

from __future__ import annotations

import re
from typing import Any

LANGUAGE_HEBREW = "he"
LANGUAGE_ENGLISH = "en"
MESSAGE_LANGUAGES = (LANGUAGE_ENGLISH, LANGUAGE_HEBREW)
DEFAULT_MESSAGE_LANGUAGE = LANGUAGE_ENGLISH

_HEBREW_LETTER = re.compile(r"[֐-׿]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_message_language(value: Any) -> str:
    """A language this module knows, or nothing."""

    text = normalize_text(value).lower()
    return text if text in MESSAGE_LANGUAGES else ""


def detect_message_language(text: Any) -> str:
    """Hebrew when any Hebrew letter is in it, English when it has Latin
    letters and no Hebrew, and nothing when it has neither: a thumbs-up, a
    time or a number says nothing about the language someone writes in."""

    value = normalize_text(text)
    if not value:
        return ""
    if _HEBREW_LETTER.search(value):
        return LANGUAGE_HEBREW
    if _LATIN_LETTER.search(value):
        return LANGUAGE_ENGLISH
    return ""


def resolve_message_language(database: Any, *, user_id: int, member_id: int = 0) -> str:
    """The language one person's messages go out in. For a family member,
    what they have written in from their own phone; until they have, and
    for the account holder, what the holder has written in, else the script
    of their name, else English."""

    resolved_user_id = int(user_id or 0)
    if resolved_user_id <= 0:
        return DEFAULT_MESSAGE_LANGUAGE
    if int(member_id or 0) > 0:
        getter = getattr(database, "get_household_member", None)
        member = getter(user_id=resolved_user_id, member_id=int(member_id)) if callable(getter) else None
        language = normalize_message_language((member or {}).get("language"))
        if language:
            return language
    profile = database.get_household_profile(user_id=resolved_user_id) or {}
    language = normalize_message_language(profile.get("language"))
    if language:
        return language
    user = database.get_user_by_id(resolved_user_id) or {}
    return detect_message_language(user.get("name") or user.get("displayName")) or DEFAULT_MESSAGE_LANGUAGE


def remember_message_language(database: Any, *, user_id: int, text: Any, member_id: int = 0) -> str:
    """Keep the language of a message the person just wrote: on the family
    member's own row when member_id names one, else on the account holder's
    profile. A message that says nothing about it (an emoji, a number)
    changes nothing."""

    language = detect_message_language(text)
    resolved_user_id = int(user_id or 0)
    if not language or resolved_user_id <= 0:
        return ""
    if int(member_id or 0) > 0:
        member = database.get_household_member(user_id=resolved_user_id, member_id=int(member_id)) or {}
        if normalize_message_language(member.get("language")) != language:
            database.save_household_member_language(
                user_id=resolved_user_id, member_id=int(member_id), language=language,
            )
        return language
    profile = database.get_household_profile(user_id=resolved_user_id) or {}
    if normalize_message_language(profile.get("language")) != language:
        database.save_household_profile(user_id=resolved_user_id, language=language)
    return language


__all__ = [
    "DEFAULT_MESSAGE_LANGUAGE",
    "LANGUAGE_ENGLISH",
    "LANGUAGE_HEBREW",
    "MESSAGE_LANGUAGES",
    "detect_message_language",
    "normalize_message_language",
    "remember_message_language",
    "resolve_message_language",
]
