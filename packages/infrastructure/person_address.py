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

Most people never write a sentence the word list below can read, and a
reply model left to guess afresh each turn addresses the same partner as a
woman in one message and a man in the next. So the model reads it once,
from the context a person would read it from (learn_address_forms): how
the writer speaks of themselves, how the others in the conversation speak
of them, and the names - their own, and their partner's, since the holder
whose partner is called Moshe is most likely a woman. Being wrong is
allowed; guessing again is not. What it read is kept with what it rests
on (the basis), and a weaker reading never replaces a stronger one:
a name is the weakest, then what others say of them, then how they speak
of themselves, and strongest of all the person saying it outright - "I'm
a woman", "תפנה אליי בלשון נקבה", or correcting a form the assistant used.
That one is confirmed, and only another word of their own changes it.
Nobody is ever asked.
"""

from __future__ import annotations

import json
import re
from typing import Any
from typing import Callable
from typing import Iterable

from packages.infrastructure.openai_api import call_openai_response
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.task_complexity import TaskComplexity
from packages.infrastructure.task_complexity import resolve_task_model
from packages.infrastructure.task_complexity import resolve_task_reasoning

ADDRESS_FEMININE = "f"
ADDRESS_MASCULINE = "m"
ADDRESS_FORMS = (ADDRESS_FEMININE, ADDRESS_MASCULINE)

# What the model is told, in the words it reads the context in.
ADDRESS_WORDS = {ADDRESS_FEMININE: "a woman", ADDRESS_MASCULINE: "a man"}

# What a kept form rests on, weakest first. The first three were read from
# the conversation (inferred); the last is the person's own word on it.
ADDRESS_BASIS_NAME = "name"
ADDRESS_BASIS_OTHERS = "others"
ADDRESS_BASIS_SELF = "self"
ADDRESS_BASIS_CONFIRMED = "confirmed"
ADDRESS_BASES = ("", ADDRESS_BASIS_NAME, ADDRESS_BASIS_OTHERS, ADDRESS_BASIS_SELF, ADDRESS_BASIS_CONFIRMED)
_BASIS_RANK = {ADDRESS_BASIS_NAME: 1, ADDRESS_BASIS_OTHERS: 2, ADDRESS_BASIS_SELF: 3, ADDRESS_BASIS_CONFIRMED: 4}
# The words the reader answers in, mapped to the basis kept.
_READER_BASES = {
    "said": ADDRESS_BASIS_CONFIRMED, "self": ADDRESS_BASIS_SELF,
    "others": ADDRESS_BASIS_OTHERS, "name": ADDRESS_BASIS_NAME,
}

# Reading a person's gender from names and phrasing is a judgement, but a
# small one in a fixed shape.
ADDRESS_READER_COMPLEXITY = TaskComplexity.MEDIUM
ADDRESS_READER_MAX_OUTPUT_TOKENS = 1500
ADDRESS_READER_HISTORY = 6
HOLDER_REF = "holder"
_HEBREW_LETTER = re.compile(r"[א-ת]")

ADDRESS_READER_INSTRUCTIONS = (
    "You read, from a family's WhatsApp conversation with their assistant, whether each grown-up in it "
    "should be addressed in Hebrew as a woman (f) or as a man (m). Nobody is ever asked; you work it out "
    "the way a person would, and a wrong guess is fine because they can correct it. Evidence, strongest "
    "first: said - the writer tells the assistant outright how to address them or what they are ('I'm a "
    "woman', 'תפנה אליי בלשון נקבה', 'אני בחור'), or corrects a gendered form the assistant used for them; "
    "self - the writer's own gendered verbs and adjectives about themselves ('אני עייפה', 'הלכתי ואני "
    "בטוח', 'אני אמא של'); others - how someone else in the conversation refers to a person ('אורי אמרה', "
    "'בעלי', 'אשתי', 'he'll take her'); name - the person's own name, or, for a couple, what one partner's "
    "name says about the other: a holder whose partner is called Moshe is most likely a woman. Only the "
    "writer can give said or self, and only about themselves. Use the names and roles in people and the "
    "conversation; judge every name yourself, in any language. For each person, give the strongest evidence "
    "the message and conversation hold. Leave out a person when there is no evidence at all, and when the "
    "only evidence is a name that is as common for women as for men with nothing else to tip it. kept is "
    "what is already held for them and what it rests on; report what you read regardless. Return exactly "
    'one JSON object: {"people":[{"ref":"...","form":"f|m","basis":"said|self|others|name"}]}.'
)

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
    them, read from the word list. A message that says nothing changes
    nothing; the last clear word wins, as with the language, except over
    what they have confirmed outright (keep_address_form)."""

    form = detect_address_form(text)
    if not form or int(user_id or 0) <= 0:
        return ""
    keep_address_form(database, user_id=user_id, member_id=member_id, form=form, basis=ADDRESS_BASIS_SELF)
    return form


def _kept(database: Any, *, user_id: int, member_id: int = 0) -> tuple[str, str]:
    """The kept form and what it rests on. A form kept before the basis was
    recorded came from the person's own words (remember_address_form)."""

    if int(member_id or 0) > 0:
        getter = getattr(database, "get_household_member", None)
        row = (getter(user_id=int(user_id), member_id=int(member_id)) if callable(getter) else None) or {}
    else:
        row = database.get_household_profile(user_id=int(user_id)) or {}
    form = normalize_address_form(row.get("addressForm"))
    basis = normalize_text(row.get("addressBasis")).lower()
    if form and basis not in _BASIS_RANK:
        basis = ADDRESS_BASIS_SELF
    return form, (basis if form else "")


def address_confirmed(basis: Any) -> bool:
    """Whether the person said it themselves, rather than it being read."""

    return normalize_text(basis).lower() == ADDRESS_BASIS_CONFIRMED


def replaces_kept(kept_form: str, kept_basis: str, form: str, basis: str) -> bool:
    """Whether a new reading takes the place of what is kept: anything over
    nothing, stronger over weaker, and at the same strength only the
    person's own words - the last thing they said of themselves, the last
    correction - so a guess from a name is never guessed over again."""

    form = normalize_address_form(form)
    rank = _BASIS_RANK.get(basis, 0)
    if not form or not rank:
        return False
    if not kept_form:
        return True
    kept_rank = _BASIS_RANK.get(kept_basis, _BASIS_RANK[ADDRESS_BASIS_SELF])
    if form == kept_form:
        return rank > kept_rank
    return rank > kept_rank or (rank == kept_rank and rank >= _BASIS_RANK[ADDRESS_BASIS_SELF])


def keep_address_form(database: Any, *, user_id: int, form: str, basis: str, member_id: int = 0) -> bool:
    """Keep a reading of how this person is addressed when it should replace
    what is kept (replaces_kept). True when something changed."""

    if int(user_id or 0) <= 0:
        return False
    kept_form, kept_basis = _kept(database, user_id=user_id, member_id=member_id)
    if not replaces_kept(kept_form, kept_basis, form, basis):
        return False
    form = normalize_address_form(form)
    if int(member_id or 0) > 0:
        database.save_household_member_address_form(
            user_id=int(user_id), member_id=int(member_id), address_form=form, address_basis=basis,
        )
    else:
        database.save_household_profile(user_id=int(user_id), address_form=form, address_basis=basis)
    return True


def _holder_name(database: Any, user_id: int) -> str:
    user = database.get_user_by_id(int(user_id)) or {}
    name = normalize_text(user.get("displayName") or user.get("display_name"))
    if name:
        return name
    for fact in database.list_account_facts(user_id=int(user_id)):
        if fact.get("key") == "name":
            return normalize_text(fact.get("fact")).removeprefix("Their name is ").rstrip(".")
    return ""


def address_people(database: Any, *, user_id: int, member_id: int = 0) -> list[dict[str, Any]]:
    """The grown-ups whose address form the conversation can say something
    about: the account holder and every family member who is not a child,
    each with what is kept for them. The writer is marked."""

    people: list[dict[str, Any]] = []
    form, basis = _kept(database, user_id=user_id)
    people.append({
        "ref": HOLDER_REF, "memberId": 0, "name": _holder_name(database, user_id), "role": "account holder",
        "form": form, "basis": basis, "writer": int(member_id or 0) <= 0,
    })
    for member in database.list_household_members(user_id=int(user_id)) or []:
        if normalize_text(member.get("role")).lower() == "child":
            continue
        mid = int(member.get("id") or 0)
        form, basis = _kept(database, user_id=user_id, member_id=mid)
        people.append({
            "ref": f"member:{mid}", "memberId": mid, "name": normalize_text(member.get("name")),
            "role": normalize_text(member.get("role")) or "other", "form": form, "basis": basis,
            "writer": mid == int(member_id or 0),
        })
    return people


def address_reading_wanted(text: Any, people: Iterable[dict[str, Any]]) -> bool:
    """Whether a message is worth reading for it: it is in Hebrew, and
    something is still open - someone not known yet, or a writer who has
    not said it outright and so may be correcting a form now."""

    if not _HEBREW_LETTER.search(normalize_text(text)):
        return False
    return any(not person["form"] or (person["writer"] and not address_confirmed(person["basis"])) for person in people)


def build_address_reader_prompt(
    text: Any, people: Iterable[dict[str, Any]], conversation: Iterable[dict[str, Any]] = (),
) -> str:
    people = list(people)
    writer = next((person["ref"] for person in people if person["writer"]), HOLDER_REF)
    context = {
        "writer": writer,
        "message": normalize_text(text)[:1000],
        "people": [
            {
                "ref": person["ref"], "name": person["name"] or None, "role": person["role"],
                "kept": f"{address_word(person['form'])} ({person['basis']})" if person["form"] else None,
            }
            for person in people
        ],
        "recentConversation": [
            {"role": normalize_text(item.get("role")), "text": " ".join(normalize_text(item.get("text")).split())[:300]}
            for item in list(conversation)[-ADDRESS_READER_HISTORY:]
            if isinstance(item, dict)
        ],
    }
    return (
        "message is what writer just sent; recentConversation is what came before it, the user lines written "
        "by writer.\n\nCONTEXT\n" + json.dumps(context, ensure_ascii=False)
    )


def parse_address_reading(text: Any) -> list[dict[str, str]]:
    """The reader's JSON as (ref, form, basis), tolerant of packaging, with
    anything it could not have meant left out."""

    raw = normalize_text(text)
    start, end = raw.find("{"), raw.rfind("}")
    try:
        parsed = json.loads(raw[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        parsed = {}
    readings: list[dict[str, str]] = []
    for item in (parsed.get("people") if isinstance(parsed, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        form = normalize_address_form(item.get("form"))
        basis = _READER_BASES.get(normalize_text(item.get("basis")).lower(), "")
        ref = normalize_text(item.get("ref"))
        if form and basis and ref:
            readings.append({"ref": ref, "form": form, "basis": basis})
    return readings


def _ask_address_reader(prompt: str, *, billing_email: str = "", usage_recorder: Any = None) -> str:
    model = resolve_task_model(ADDRESS_READER_COMPLEXITY, "OPENAI_MODEL")
    result = call_openai_response(
        tool_name="address_form_reader",
        tool_id="address_form_reader",
        billing_email=billing_email,
        prompt=prompt,
        model=model,
        instructions=ADDRESS_READER_INSTRUCTIONS,
        reasoning=resolve_task_reasoning(ADDRESS_READER_COMPLEXITY),
        max_output_tokens=ADDRESS_READER_MAX_OUTPUT_TOKENS,
        usage_recorder=usage_recorder,
        price_resolver=getattr(usage_recorder, "get_model_price", None),
        config=load_openai_config(default_model=model, strict_tracking=False, include_prompt_in_metadata=False),
    )
    return normalize_text(getattr(result, "output_text", ""))


def learn_address_forms(
    database: Any,
    *,
    user_id: int,
    text: Any,
    member_id: int = 0,
    conversation: Iterable[dict[str, Any]] = (),
    billing_email: str = "",
    ask: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """Read what the message just written, and the conversation before it,
    say about how each grown-up in the family is addressed, and keep what
    should replace what is kept. Returns what changed, by ref.

    The word list (remember_address_form) runs first and costs nothing; the
    model is asked only while something is still open. Only the writer can
    say it or show it of themselves: the same words about anyone else are
    what others say of them. A reading that cannot be made changes nothing.
    """

    if int(user_id or 0) <= 0:
        return {}
    remember_address_form(database, user_id=user_id, text=text, member_id=member_id)
    people = address_people(database, user_id=user_id, member_id=member_id)
    if not address_reading_wanted(text, people):
        return {}
    prompt = build_address_reader_prompt(text, people, conversation)
    try:
        if ask is not None:
            answer = ask(prompt)
        else:
            answer = _ask_address_reader(prompt, billing_email=billing_email, usage_recorder=database)
    except Exception as exc:  # noqa: BLE001 - a reading that cannot run leaves what is kept
        print(f"person_address.reader_failed user={int(user_id)} error={exc!r}", flush=True)
        return {}
    by_ref = {person["ref"]: person for person in people}
    changed: dict[str, str] = {}
    for reading in parse_address_reading(answer):
        person = by_ref.get(reading["ref"])
        if person is None:
            continue
        basis = reading["basis"]
        if not person["writer"] and _BASIS_RANK[basis] > _BASIS_RANK[ADDRESS_BASIS_OTHERS]:
            basis = ADDRESS_BASIS_OTHERS
        if keep_address_form(
            database, user_id=user_id, member_id=person["memberId"], form=reading["form"], basis=basis,
        ):
            changed[person["ref"]] = reading["form"]
    return changed


def address_word(form: Any) -> str:
    """The form as the model reads it in the context ("a woman", "a man"),
    or nothing when it is not known."""

    return ADDRESS_WORDS.get(normalize_address_form(form), "")


__all__ = [
    "ADDRESS_BASES",
    "ADDRESS_BASIS_CONFIRMED",
    "ADDRESS_BASIS_NAME",
    "ADDRESS_BASIS_OTHERS",
    "ADDRESS_BASIS_SELF",
    "ADDRESS_FEMININE",
    "ADDRESS_FORMS",
    "ADDRESS_MASCULINE",
    "ADDRESS_READER_COMPLEXITY",
    "ADDRESS_READER_INSTRUCTIONS",
    "address_confirmed",
    "address_people",
    "address_reading_wanted",
    "address_word",
    "build_address_reader_prompt",
    "detect_address_form",
    "keep_address_form",
    "learn_address_forms",
    "normalize_address_form",
    "parse_address_reading",
    "remember_address_form",
    "replaces_kept",
    "resolve_address_form",
]
