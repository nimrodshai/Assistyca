"""The words on a link's button, in the language of the person who taps it.

On WhatsApp a link the assistant hands out rides under the reply as a
button, and the button's words are ours, not the model's. They were written
once in English, so a Hebrew-speaking family read a Hebrew reply with "Open
your week" under it. Each label is kept here by what the link is for, in
every language messages go out in, and picked by the person's language when
the link is offered.

A WhatsApp button takes 20 characters; a label that would not fit is cut
by the sender, so the Hebrew ones are kept short.
"""

from __future__ import annotations

from typing import Any

from packages.infrastructure.message_language import DEFAULT_MESSAGE_LANGUAGE
from packages.infrastructure.message_language import normalize_message_language

LINK_LABELS: dict[str, dict[str, str]] = {
    "open": {"en": "Open", "he": "לפתוח"},
    "week": {"en": "Open your week", "he": "לפתוח את השבוע"},
    "lists": {"en": "Open my lists", "he": "לרשימות"},
    "todos": {"en": "Open my todos", "he": "למשימות"},
    "list": {"en": "Open the list", "he": "לרשימה"},
    "named_list": {"en": "Open {name}", "he": "{name}"},
    "receipts": {"en": "Open receipts", "he": "לקבלות"},
    "connect": {"en": "Connect {provider}", "he": "חיבור {provider}"},
    "reconnect": {"en": "Reconnect {provider}", "he": "חיבור מחדש {provider}"},
    "sign_in": {"en": "Sign in with {provider}", "he": "כניסה עם {provider}"},
    "join_group": {"en": "Join {name}", "he": "הצטרפות ל{name}"},
    "invite": {"en": "Invite {name}", "he": "הזמנה ל{name}"},
    "pay": {"en": "Keep Assistyca", "he": "להמשיך עם Assistyca"},
    "school_login": {"en": "Add the school login", "he": "כניסה לבית הספר"},
    "plan": {"en": "Plan {number}", "he": "תוכנית {number}"},
    "tabu": {"en": "Order Tabu extract", "he": "הזמנת נסח טאבו"},
}

# The words over a button sent with no reply of its own to sit under:
# the whole reply was the link, or it went ahead in a bubble of its own.
BUTTON_ONLY_BODY = {"en": "Tap the button to open it.", "he": "אפשר לפתוח מהכפתור."}
# The words over a second link's button, which needs some body of its own;
# never the label again.
ANOTHER_LINK_BODY = {"en": "And this one.", "he": "וגם זה."}


def _language(language: Any) -> str:
    return normalize_message_language(language) or DEFAULT_MESSAGE_LANGUAGE


def link_label(kind: str, language: Any = "", **values: Any) -> str:
    """The button's words for a link of this kind, in this language."""

    labels = LINK_LABELS.get(kind) or LINK_LABELS["open"]
    template = labels.get(_language(language)) or labels[DEFAULT_MESSAGE_LANGUAGE]
    return template.format(**{key: str(value) for key, value in values.items()})


def in_language(texts: dict[str, str], language: Any = "") -> str:
    return texts.get(_language(language)) or texts[DEFAULT_MESSAGE_LANGUAGE]


__all__ = [
    "ANOTHER_LINK_BODY",
    "BUTTON_ONLY_BODY",
    "LINK_LABELS",
    "in_language",
    "link_label",
]
