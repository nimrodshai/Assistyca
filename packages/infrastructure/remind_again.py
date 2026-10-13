"""One more word, five minutes before.

The word before a drive of their own goes out half an hour ahead, and ends
by asking whether they want to hear it once more five minutes before -
with a button to say yes, so it costs one tap. Inside Meta's service window
the question and the button ride under the message itself; outside it the
reminder template made for this carries the same question in its own
closing line and the same button (notification_templates).

The button carries the queued action's id. The tap comes back as the
button's payload, and this is where it is read: the drive, its time and the
phone it was for are taken from the action that sent it, a second one-off
is queued for five minutes before the drive, and the tap is answered. The
second word is claimed like every nudge, so a button tapped twice sends one
message. The words of the question and of the button are fixed, like the
template that holds them, so they are kept here in both languages beside
the template's name.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.message_language import DEFAULT_MESSAGE_LANGUAGE
from packages.infrastructure.message_language import normalize_message_language
from packages.infrastructure.notification_templates import TEMPLATE_KIND_PAYLOAD_KEY
from packages.infrastructure.notification_templates import TEMPLATE_KIND_REMINDER
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE

REMIND_AGAIN_MINUTES = 5
# The button's payload: this prefix and the id of the action that sent it.
REMIND_AGAIN_PREFIX = "remindagain:"
REMIND_AGAIN_PAYLOAD_KEY = "remindAgain"
# The source the family nudger writes on what it queues
# (family_week_nudges.NUDGE_SOURCE); not imported, since that module
# imports the chat and the chat imports this.
NUDGE_SOURCE = "family_week"

# The closing question, word for word what the template made for it says
# under the message, and the button under both.
REMIND_AGAIN_QUESTION = {
    "en": "Want me to remind you again 5 minutes before?",
    "he": "רוצה שאזכיר שוב 5 דקות לפני?",
}
# A reply button's title takes 20 characters on an interactive message.
REMIND_AGAIN_BUTTON_LABEL = {
    "en": "Yes, 5 min before",
    "he": "כן, 5 דקות לפני",
}


def _language(value: Any) -> str:
    return normalize_message_language(value) or DEFAULT_MESSAGE_LANGUAGE


def remind_again_question(language: Any) -> str:
    return REMIND_AGAIN_QUESTION.get(_language(language), REMIND_AGAIN_QUESTION["en"])


def remind_again_button_label(language: Any) -> str:
    return REMIND_AGAIN_BUTTON_LABEL.get(_language(language), REMIND_AGAIN_BUTTON_LABEL["en"])


def remind_again_offer(rides: list[dict[str, Any]], *, local_now: datetime, facts: list[str], reader: str = "") -> dict[str, Any]:
    """What a ride word keeps so the tap can be answered later: when the
    drive is (the earliest of the trip, as a UTC moment), the facts as the
    reminder had them, and the first name of a family member reading it on
    their own phone."""

    moments = []
    for ride in rides:
        clock = normalize_text(ride.get("at"))
        if not clock or ":" not in clock:
            continue
        hour, minute = (int(part) for part in clock.split(":")[:2])
        moments.append(local_now.replace(hour=hour, minute=minute, second=0, microsecond=0))
    if not moments:
        return {}
    due = min(moments)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return {
        "dueAt": due.astimezone(timezone.utc).isoformat(),
        "minutesBefore": REMIND_AGAIN_MINUTES,
        "facts": [str(fact) for fact in facts],
        **({"reader": normalize_text(reader)} if reader else {}),
    }


def remind_again_button(action: dict[str, Any], language: Any) -> dict[str, str]:
    """The button and the question that go under this action's message, or
    nothing: only a word that kept an offer carries them."""

    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    offer = payload.get(REMIND_AGAIN_PAYLOAD_KEY)
    action_id = int(action.get("id") or 0)
    if not isinstance(offer, dict) or not normalize_text(offer.get("dueAt")) or action_id <= 0:
        return {}
    return {
        "id": f"{REMIND_AGAIN_PREFIX}{action_id}",
        "label": remind_again_button_label(language),
        "question": remind_again_question(language),
    }


def parse_remind_again_id(interactive_id: Any) -> int:
    """The action id a tap names, or 0 for a tap that is not this button's."""

    text = normalize_text(interactive_id)
    if not text.startswith(REMIND_AGAIN_PREFIX):
        return 0
    try:
        return max(0, int(text[len(REMIND_AGAIN_PREFIX):]))
    except ValueError:
        return 0


def _parse_moment(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def second_word(facts: list[str], *, reader: str = "", language: str = "the language they write to you in") -> dict[str, str]:
    """The title, instruction and fallback of the word five minutes before,
    from the same facts the first word had."""

    whose = (
        f"This message is for {reader}, who is in this family and is the one driving. " if reader
        else "The person is the one driving. "
    )
    opening = (
        "Half an hour before this drive they were reminded of it and asked for one more word five minutes "
        "before; this is it. "
    )
    if len(facts) == 1:
        instruction = (
            opening + whose + f"In one short sentence, in {language}, say it is time to leave now and what for. "
            "The fact is exact; add nothing, and use no tool.\nDRIVE: " + facts[0]
        )
        fallback = f"Time to leave: {facts[0]}."
    else:
        instruction = (
            opening + whose + f"In one or two short sentences, in {language}, say it is time to leave now for this one "
            "trip, in time order. Say each once. The facts are exact; add nothing, and use no tool.\nDRIVES:\n"
            + "\n".join(facts)
        )
        fallback = "Time to leave, one trip:\n" + "\n".join(f"• {fact}" for fact in facts)
    return {"title": "Time to leave", "instruction": instruction, "fallback": fallback}


def schedule_second_word(
    database: Any, *, user_id: int, interactive_id: Any, now: datetime | None = None,
) -> dict[str, Any]:
    """Answer the tap: queue the word five minutes before the drive the
    tapped reminder was about, once.

    The outcome says what happened - scheduled, already (a second tap on
    the same button), past (the drive's time has come and gone) or unknown
    (no reminder of theirs sent that button) - with the moment the word
    goes, in the person's own zone, where there is one."""

    action_id = parse_remind_again_id(interactive_id)
    action = database.get_scheduled_action(action_id) if action_id else None
    payload = action.get("payload") if isinstance(action, dict) and isinstance(action.get("payload"), dict) else {}
    offer = payload.get(REMIND_AGAIN_PAYLOAD_KEY) if isinstance(payload.get(REMIND_AGAIN_PAYLOAD_KEY), dict) else {}
    due = _parse_moment(offer.get("dueAt"))
    if not action or int(action.get("userId") or 0) != int(user_id) or due is None:
        return {"outcome": "unknown"}
    timezone_name = normalize_text(action.get("timezone")) or "UTC"
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone, timezone_name = ZoneInfo("UTC"), "UTC"
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if due <= reference:
        return {"outcome": "past", "dueAt": due.astimezone(zone)}
    try:
        minutes = int(offer.get("minutesBefore") or REMIND_AGAIN_MINUTES)
    except (TypeError, ValueError):
        minutes = REMIND_AGAIN_MINUTES
    run_at = max(reference, due - timedelta(minutes=max(1, minutes)))
    if not database.claim_household_nudge(user_id=int(user_id), nudge_key=f"remind-again:{action_id}"):
        return {"outcome": "already", "runAt": run_at.astimezone(zone)}
    facts = [str(fact) for fact in (offer.get("facts") or []) if str(fact or "").strip()]
    reader = normalize_text(offer.get("reader"))
    words = second_word(
        facts or [normalize_text(payload.get("fallbackText")) or "your drive"],
        reader=reader,
        language="the language the family writes to you in" if reader else "the language they write to you in",
    )
    recipient_wa_id = normalize_text(payload.get("recipientWaId"))
    second_payload: dict[str, Any] = {
        "title": words["title"],
        "instruction": words["instruction"],
        "fallbackText": words["fallback"],
        "oneOff": True,
        "source": normalize_text(payload.get("source")) or NUDGE_SOURCE,
        TEMPLATE_KIND_PAYLOAD_KEY: TEMPLATE_KIND_REMINDER,
        "remindAgainOf": action_id,
    }
    if recipient_wa_id:
        second_payload["recipientWaId"] = recipient_wa_id
    database.create_scheduled_action(
        user_id=int(user_id),
        action_type=STANDING_TASK_ACTION_TYPE,
        channel="whatsapp",
        recipient_ref=recipient_wa_id or "owner",
        run_at=run_at,
        timezone_name=timezone_name,
        payload=second_payload,
    )
    return {"outcome": "scheduled", "runAt": run_at.astimezone(zone)}


__all__ = [
    "REMIND_AGAIN_BUTTON_LABEL",
    "REMIND_AGAIN_MINUTES",
    "REMIND_AGAIN_PAYLOAD_KEY",
    "REMIND_AGAIN_PREFIX",
    "REMIND_AGAIN_QUESTION",
    "parse_remind_again_id",
    "remind_again_button",
    "remind_again_button_label",
    "remind_again_offer",
    "remind_again_question",
    "schedule_second_word",
    "second_word",
]
