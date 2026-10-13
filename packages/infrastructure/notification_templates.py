"""The approved templates that carry a scheduled message outside Meta's window.

Inside the 24-hour service window a scheduled message goes as plain text.
Outside it only a template Meta has approved gets through, and the template
is chosen by what the message is, not by one generic wrapper: a morning
digest opens with "Good morning", a reminder with "Heads-up", the evening
look at tomorrow with "Tomorrow at a glance", and the week ahead with the
week's picture on top. Each kind exists in Hebrew and in English under the
same template name, so only the language code changes between people
(see message_language). The assistant's words ride in the single body
variable, one line, as before.

A queued action names its kind in the payload under TEMPLATE_KIND_PAYLOAD_KEY;
one that names nothing is a reminder. The week-ahead template carries the
week as its picture header and nothing else, so a message with no picture
never rides it.
"""

from __future__ import annotations

from typing import Any

from packages.infrastructure.message_language import DEFAULT_MESSAGE_LANGUAGE
from packages.infrastructure.message_language import normalize_message_language

TEMPLATE_KIND_MORNING_DIGEST = "morning_digest"
TEMPLATE_KIND_REMINDER = "reminder"
TEMPLATE_KIND_EVENING_GLANCE = "evening_glance"
TEMPLATE_KIND_WEEK_AHEAD = "week_ahead"
DEFAULT_TEMPLATE_KIND = TEMPLATE_KIND_REMINDER
TEMPLATE_KINDS = (
    TEMPLATE_KIND_MORNING_DIGEST,
    TEMPLATE_KIND_REMINDER,
    TEMPLATE_KIND_EVENING_GLANCE,
    TEMPLATE_KIND_WEEK_AHEAD,
)
TEMPLATE_KIND_PAYLOAD_KEY = "templateKind"

# The names as Meta holds them, each approved in `en` and `he`.
TEMPLATE_NAMES = {
    TEMPLATE_KIND_MORNING_DIGEST: "assistyca_morning_digest",
    TEMPLATE_KIND_REMINDER: "assistyca_reminder",
    TEMPLATE_KIND_EVENING_GLANCE: "assistyca_evening_glance",
    TEMPLATE_KIND_WEEK_AHEAD: "assistyca_week_ahead",
}
# Kinds whose template opens with a picture: sent only with one.
IMAGE_TEMPLATE_KINDS = frozenset({TEMPLATE_KIND_WEEK_AHEAD})


def normalize_template_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in TEMPLATE_KINDS else DEFAULT_TEMPLATE_KIND


def template_language(language: Any) -> str:
    return normalize_message_language(language) or DEFAULT_MESSAGE_LANGUAGE


def template_for(kind: Any, language: Any, *, with_image: bool = False) -> tuple[str, str]:
    """The template name and language code that carry a message of this
    kind, or an empty name when no template of the kind fits the message:
    the week-ahead template takes a picture and cannot go without one."""

    resolved_kind = normalize_template_kind(kind)
    if resolved_kind in IMAGE_TEMPLATE_KINDS and not with_image:
        return "", ""
    return TEMPLATE_NAMES[resolved_kind], template_language(language)


def image_template_for(language: Any) -> tuple[str, str]:
    """The template that carries a picture with one line under it."""

    return TEMPLATE_NAMES[TEMPLATE_KIND_WEEK_AHEAD], template_language(language)


__all__ = [
    "DEFAULT_TEMPLATE_KIND",
    "IMAGE_TEMPLATE_KINDS",
    "TEMPLATE_KINDS",
    "TEMPLATE_KIND_EVENING_GLANCE",
    "TEMPLATE_KIND_MORNING_DIGEST",
    "TEMPLATE_KIND_PAYLOAD_KEY",
    "TEMPLATE_KIND_REMINDER",
    "TEMPLATE_KIND_WEEK_AHEAD",
    "TEMPLATE_NAMES",
    "image_template_for",
    "normalize_template_kind",
    "template_for",
    "template_language",
]
