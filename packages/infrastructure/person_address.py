"""Which grammatical gender a person is addressed in.

English speaks to everyone the same way; Hebrew does not. "Do you want" is
רוצה to a man and רוצָה to a woman - the same letters, as it happens - but
"you need" is צריך to one and צריכה to the other, and a message that picks
the wrong one, or dodges by speaking to the person in the plural (רוצים,
as to a crowd), reads as written for nobody in particular. One person is
writing, and they should be spoken to as themselves.

Nobody is asked. The person says it themselves, every time they speak about
themselves in the present tense - "אני לוקחת" is a woman, "אני לוקח" a man -
and the conversation keeps the last clear word on it, beside the language
they write in (message_language). The chat's own replies can also read it
from the conversation in front of them; this is for the words written when
nobody is typing - the morning digest, the word before a drive - and for
the days after the message that said it has scrolled out of the window.

It is kept per person, not per account: the account holder's on their
profile, a family member's on their row, because a partner writing from
their own phone is not the account holder.
"""

from __future__ import annotations

import re
from typing import Any

ADDRESS_FEMININE = "f"
ADDRESS_MASCULINE = "m"
ADDRESS_FORMS = (ADDRESS_FEMININE, ADDRESS_MASCULINE)

# What the model is told, in the words it reads the context in.
ADDRESS_WORDS = {ADDRESS_FEMININE: "a woman", ADDRESS_MASCULINE: "a man"}

# Present-tense words a person uses about themselves whose ending says the
# gender: the masculine form, then the feminine. Only words that are
# plainly about the speaker after "אני"; רוצה, מנסה, מקווה and the like read
# the same for both and are not here.
_GENDERED_PAIRS = (
    ("צריך", "צריכה"), ("יכול", "יכולה"), ("חושב", "חושבת"), ("לוקח", "לוקחת"), ("אוסף", "אוספת"),
    ("מביא", "מביאה"), ("מגיע", "מגיעה"), ("נוסע", "נוסעת"), ("הולך", "הולכת"), ("יוצא", "יוצאת"),
    ("חוזר", "חוזרת"), ("עובד", "עובדת"), ("יודע", "יודעת"), ("מבין", "מבינה"), ("מוכן", "מוכנה"),
    ("בטוח", "בטוחה"), ("עסוק", "עסוקה"), ("מעדיף", "מעדיפה"), ("שמח", "שמחה"), ("מתכוון", "מתכוונת"),
    ("נמצא", "נמצאת"), ("אוהב", "אוהבת"), ("זוכר", "זוכרת"), ("שוכח", "שוכחת"), ("מסיים", "מסיימת"),
    ("מתחיל", "מתחילה"), ("עייף", "עייפה"), ("אמור", "אמורה"), ("חייב", "חייבת"), ("מרגיש", "מרגישה"),
    ("מסכים", "מסכימה"), ("נשאר", "נשארת"), ("מאשר", "מאשרת"), ("משאיר", "משאירה"), ("מוריד", "מורידה"),
    ("מטפל", "מטפלת"), ("דואג", "דואגת"), ("מחליף", "מחליפה"), ("מתלבט", "מתלבטת"), ("מחכה", "מחכה"),
    ("מצליח", "מצליחה"), ("מספיק", "מספיקה"), ("מתכנן", "מתכננת"), ("מעוניין", "מעוניינת"), ("מבקש", "מבקשת"),
    ("אבא", "אמא"),
)
_MASCULINE_WORDS = frozenset(masc for masc, fem in _GENDERED_PAIRS if masc != fem)
_FEMININE_WORDS = frozenset(fem for masc, fem in _GENDERED_PAIRS if masc != fem)
# "אני" as people type it, with the letters that glue onto the front of it.
_I_WORDS = frozenset({"אני", "ואני", "שאני", "כשאני", "ושאני", "וכשאני"})
# Words that sit between "אני" and the verb without changing who it is about.
_BETWEEN_WORDS = frozenset({
    "לא", "כבר", "גם", "עדיין", "תמיד", "בדרך", "כלל", "מחר", "היום", "אולי", "בטח", "ממש", "די", "קצת",
    "עוד", "רק", "כנראה", "פשוט", "באמת", "עכשיו", "הערב", "בבוקר", "מאוד", "בעיקרון", "בינתיים", "תכלס",
})
_HOW_FAR_AFTER_I = 3
_TOKEN = re.compile(r"[א-ת׳״']+")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_address_form(value: Any) -> str:
    """A form this module knows, or nothing."""

    text = normalize_text(value).lower()
    return text if text in ADDRESS_FORMS else ""


def detect_address_form(text: Any) -> str:
    """The gender the writer uses for themselves in this message, read from
    "אני" followed closely by a present-tense word whose ending says it.
    Nothing when the message has no such word, and nothing when it has
    both - a sentence about two people is not a sentence about one."""

    tokens = _TOKEN.findall(normalize_text(text))
    found: set[str] = set()
    for index, token in enumerate(tokens):
        if token not in _I_WORDS:
            continue
        for following in tokens[index + 1:index + 1 + _HOW_FAR_AFTER_I]:
            if following in _FEMININE_WORDS:
                found.add(ADDRESS_FEMININE)
                break
            if following in _MASCULINE_WORDS:
                found.add(ADDRESS_MASCULINE)
                break
            if following not in _BETWEEN_WORDS:
                break
    return next(iter(found)) if len(found) == 1 else ""


def resolve_address_form(database: Any, *, user_id: int, member_id: int = 0) -> str:
    """How this person is addressed, as kept: the family member's own when
    member_id names one, else the account holder's. Empty until they have
    said it."""

    resolved_user_id = int(user_id or 0)
    if resolved_user_id <= 0:
        return ""
    if int(member_id or 0) > 0:
        getter = getattr(database, "get_household_member", None)
        member = getter(user_id=resolved_user_id, member_id=int(member_id)) if callable(getter) else None
        return normalize_address_form((member or {}).get("addressForm"))
    profile = database.get_household_profile(user_id=resolved_user_id) or {}
    return normalize_address_form(profile.get("addressForm"))


def remember_address_form(database: Any, *, user_id: int, text: Any, member_id: int = 0) -> str:
    """Keep what a message the person just wrote says about how to address
    them. A message that says nothing changes nothing; the last clear word
    wins, as with the language."""

    form = detect_address_form(text)
    resolved_user_id = int(user_id or 0)
    if not form or resolved_user_id <= 0:
        return ""
    if int(member_id or 0) > 0:
        if resolve_address_form(database, user_id=resolved_user_id, member_id=int(member_id)) != form:
            database.save_household_member_address_form(
                user_id=resolved_user_id, member_id=int(member_id), address_form=form,
            )
        return form
    if resolve_address_form(database, user_id=resolved_user_id) != form:
        database.save_household_profile(user_id=resolved_user_id, address_form=form)
    return form


def address_word(form: Any) -> str:
    """The form as the model reads it in the context ("a woman", "a man"),
    or nothing when it is not known."""

    return ADDRESS_WORDS.get(normalize_address_form(form), "")


__all__ = [
    "ADDRESS_FEMININE",
    "ADDRESS_FORMS",
    "ADDRESS_MASCULINE",
    "address_word",
    "detect_address_form",
    "normalize_address_form",
    "remember_address_form",
    "resolve_address_form",
]
