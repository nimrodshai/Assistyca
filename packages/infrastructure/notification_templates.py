"""The approved templates that carry a scheduled message outside Meta's window.

Inside the 24-hour service window a scheduled message goes as plain text.
Outside it only a template Meta has approved gets through, and the template
is chosen by what the message is, not by one generic wrapper: a morning
digest opens with "Good morning", a reminder with "Heads-up", the evening
look at tomorrow with "Tomorrow at a glance", and the week ahead with the
week's picture on top. The word before a drive of their own is a reminder
with a button under it, offering one more word five minutes before
(remind_again), so it has a template of its own. Each kind exists in Hebrew and in English under the
same template name, so only the language code changes between people
(see message_language). The assistant's words ride in the single body
variable, one line, as before.

Those templates were moved to Marketing by Meta, and Meta stops a marketing
template to anyone who has not written to us lately (131049) - after the send
has been accepted, so no fallback catches it. Each kind therefore has a
Utility template too, tried first (UTILITY_TEMPLATE_NAMES). The fixed text of
those names the thing itself - whose drive, where, when, how many - with the
facts in small slots, because a body that is one open line is what Meta files
as Marketing. Where the slots are not there, the kind's own template carries
the message as before.

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
# The reminder with a button under it offering one more word five minutes
# before (remind_again): the ride word rides this one.
TEMPLATE_KIND_REMINDER_AGAIN = "reminder_again"
DEFAULT_TEMPLATE_KIND = TEMPLATE_KIND_REMINDER
TEMPLATE_KINDS = (
    TEMPLATE_KIND_MORNING_DIGEST,
    TEMPLATE_KIND_REMINDER,
    TEMPLATE_KIND_EVENING_GLANCE,
    TEMPLATE_KIND_WEEK_AHEAD,
    TEMPLATE_KIND_REMINDER_AGAIN,
)
TEMPLATE_KIND_PAYLOAD_KEY = "templateKind"
# A message that goes as plain text inside the 24-hour window or not at all:
# no template is tried for it.
WINDOW_ONLY_PAYLOAD_KEY = "windowOnly"

# The names as Meta holds them, each approved in `en` and `he`.
TEMPLATE_NAMES = {
    TEMPLATE_KIND_MORNING_DIGEST: "assistyca_morning_digest",
    TEMPLATE_KIND_REMINDER: "assistyca_reminder",
    TEMPLATE_KIND_EVENING_GLANCE: "assistyca_evening_glance",
    TEMPLATE_KIND_WEEK_AHEAD: "assistyca_week_ahead",
    TEMPLATE_KIND_REMINDER_AGAIN: "assistyca_reminder_again",
}
# The same kinds with a picture on top: the morning's day, tomorrow's for
# the evening, the week for Saturday. A kind not here that carries a
# picture rides the week-ahead one, which takes any picture and a line.
PICTURE_TEMPLATE_NAMES = {
    TEMPLATE_KIND_MORNING_DIGEST: "assistyca_morning_digest_picture",
    TEMPLATE_KIND_EVENING_GLANCE: "assistyca_evening_glance_picture",
    TEMPLATE_KIND_WEEK_AHEAD: "assistyca_week_ahead",
}
# The Utility templates, tried before the kind's own. The reminders take the
# assistant's line in their one slot ("Here's the reminder you asked for:");
# the morning and the evening take the day's figures (schedule_parameters)
# and are skipped without them.
UTILITY_TEMPLATE_NAMES = {
    TEMPLATE_KIND_MORNING_DIGEST: "assistyca_schedule_today",
    TEMPLATE_KIND_REMINDER: "assistyca_reminder_set",
    TEMPLATE_KIND_EVENING_GLANCE: "assistyca_schedule_tomorrow",
    TEMPLATE_KIND_REMINDER_AGAIN: "assistyca_reminder_set_again",
}
SCHEDULE_TEMPLATE_KINDS = frozenset({TEMPLATE_KIND_MORNING_DIGEST, TEMPLATE_KIND_EVENING_GLANCE})
# The day's figures for those two: its date, how many activities, how many
# drives, and how many of those drives have nobody yet.
SCHEDULE_SLOTS_PAYLOAD_KEY = "scheduleSlots"
# The Utility templates for the pictures, tried before the kind's own picture
# template: the plain one first ("Here's what your family's routine looks
# like today."), with no variable at all, and then the one that also says
# where the pick-ups stand (pickup_status). Both were submitted on
# 2026-10-15 to see which Meta keeps as Utility: a body that is the same for
# everyone may be filed as Marketing, and then only the second is of use.
ROUTINE_PICTURE_TEMPLATE_NAMES = {
    TEMPLATE_KIND_MORNING_DIGEST: ("assistyca_routine_today", "assistyca_routine_today_status"),
    TEMPLATE_KIND_EVENING_GLANCE: ("assistyca_routine_tomorrow", "assistyca_routine_tomorrow_status"),
    TEMPLATE_KIND_WEEK_AHEAD: ("assistyca_routine_week", "assistyca_routine_week_status"),
}
# Of those, the ones Meta filed as Marketing in one language (2026-10-16).
# A Marketing template to someone who has not written lately is accepted and
# then dropped (131049), so a fallback behind it never fires: these are not
# tried at all, and the one with the pick-ups goes first instead.
ROUTINE_PICTURES_FILED_AS_MARKETING = frozenset({("assistyca_routine_today", "en")})
# How many pick-ups the picture's day or week still has nobody for, kept with
# the day's figures. Drop-offs are not counted: the line says "Pick-ups".
OPEN_PICKUPS_SLOT = "openPickups"
PICKUP_STATUS_WORDS = {
    "en": {"none": "all covered", "one": "1 still needs someone", "many": "{count} still need someone"},
    "he": {"none": "כולם מכוסים", "one": "אחד עוד בלי אחראי", "many": "{count} עוד בלי אחראי"},
}
# Kinds whose only template opens with a picture: sent only with one.
IMAGE_TEMPLATE_KINDS = frozenset({TEMPLATE_KIND_WEEK_AHEAD})

# The word before a drive of their own, with its own slots - the kids, the
# place, the time - and the remind-again button under it: one template for a
# trip that is all pickups ("you're picking up Noa from ballet") and one for
# a trip that is all drop-offs ("you're dropping Noa off at ballet"). A trip
# with both, or a refusal while Meta reviews them, rides the reminder
# templates with the assistant's line in their one variable.
PICKUP_REMINDER_TEMPLATE_NAME = "assistyca_pickup_reminder"
DROP_OFF_REMINDER_TEMPLATE_NAME = "assistyca_drop_off_reminder"
RIDE_SLOTS_PAYLOAD_KEY = "rideSlots"
# What a ride word queued before drop-offs had slots was kept under.
PICKUP_SLOTS_PAYLOAD_KEY = "pickupSlots"
LIST_JOINER = {"en": " and ", "he": " ו"}


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
    if with_image:
        return image_template_for(resolved_kind, language)
    if resolved_kind in IMAGE_TEMPLATE_KINDS:
        return "", ""
    return TEMPLATE_NAMES[resolved_kind], template_language(language)


def image_template_for(kind: Any, language: Any) -> tuple[str, str]:
    """The template that carries a picture of this kind with one line under
    it: the kind's own, or the week-ahead one for a kind without one."""

    resolved_kind = normalize_template_kind(kind)
    name = PICTURE_TEMPLATE_NAMES.get(resolved_kind) or PICTURE_TEMPLATE_NAMES[TEMPLATE_KIND_WEEK_AHEAD]
    return name, template_language(language)


def utility_template_for(kind: Any, language: Any) -> tuple[str, str]:
    """The Utility template of this kind, or an empty name for a kind that
    has none (the week ahead, which only goes as a picture)."""

    name = UTILITY_TEMPLATE_NAMES.get(normalize_template_kind(kind), "")
    return (name, template_language(language)) if name else ("", "")


def schedule_parameters(slots: Any) -> list[str]:
    """{{1}} the date, {{2}} activities, {{3}} drives, {{4}} drives with
    nobody yet - or nothing when a figure is missing, since a blank variable
    is refused whole by Meta. The figures read the same in both languages."""

    if not isinstance(slots, dict):
        return []
    date_text = str(slots.get("date") or "").strip()
    figures = [slots.get(key) for key in ("activities", "drives", "open")]
    if not date_text or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in figures):
        return []
    return [date_text, *(str(value) for value in figures)]


def routine_picture_templates(kind: Any, language: Any, slots: Any) -> list[tuple[str, str, list[str]]]:
    """The Utility picture templates to try for a picture of this kind, in
    order, each with its variables: the plain one with none, then the one
    with where the pick-ups stand - left out when that is not known."""

    names = ROUTINE_PICTURE_TEMPLATE_NAMES.get(normalize_template_kind(kind))
    if not names:
        return []
    resolved = template_language(language)
    attempts: list[tuple[str, str, list[str]]] = [(names[0], resolved, [])]
    status = pickup_status(slots.get(OPEN_PICKUPS_SLOT) if isinstance(slots, dict) else None, resolved)
    if status:
        attempts.append((names[1], resolved, [status]))
    return [attempt for attempt in attempts if attempt[:2] not in ROUTINE_PICTURES_FILED_AS_MARKETING]


def pickup_status(count: Any, language: Any) -> str:
    """"all covered", "1 still needs someone", "2 still need someone" - or
    in Hebrew - or nothing when the count is not a number."""

    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return ""
    words = PICKUP_STATUS_WORDS.get(template_language(language), PICKUP_STATUS_WORDS["en"])
    if count == 0:
        return words["none"]
    return words["one"] if count == 1 else words["many"].format(count=count)


def ride_template_name(slots: Any) -> str:
    """The template a trip's slots are for: the drop-off one when the slots
    say so, the pickup one otherwise."""

    leg = str(slots.get("leg") or "") if isinstance(slots, dict) else ""
    return DROP_OFF_REMINDER_TEMPLATE_NAME if leg == "drop_off" else PICKUP_REMINDER_TEMPLATE_NAME


def _joined(items: list[str], language: str) -> str:
    """Noa and Tom; Noa, Tom and Lia - or נועה ותום in Hebrew."""

    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + LIST_JOINER.get(language, LIST_JOINER["en"]) + items[-1]


def pickup_reminder_parameters(slots: Any, language: Any) -> list[str]:
    """{{1}} the kids, {{2}} the place - where from for a pickup, where to for
    a drop-off - {{3}} the time, or nothing when the slots are not all there:
    a blank variable is refused whole by Meta."""

    if not isinstance(slots, dict):
        return []
    resolved = template_language(language)
    kids = [str(name).strip() for name in slots.get("kids") or [] if str(name).strip()]
    places = [str(place).strip() for place in slots.get("from") or [] if str(place).strip()]
    at = str(slots.get("at") or "").strip()
    if not kids or not places or not at:
        return []
    return [_joined(kids, resolved), _joined(places, resolved), at]


__all__ = [
    "DEFAULT_TEMPLATE_KIND",
    "DROP_OFF_REMINDER_TEMPLATE_NAME",
    "IMAGE_TEMPLATE_KINDS",
    "OPEN_PICKUPS_SLOT",
    "PICKUP_REMINDER_TEMPLATE_NAME",
    "PICKUP_SLOTS_PAYLOAD_KEY",
    "PICTURE_TEMPLATE_NAMES",
    "RIDE_SLOTS_PAYLOAD_KEY",
    "ROUTINE_PICTURE_TEMPLATE_NAMES",
    "SCHEDULE_SLOTS_PAYLOAD_KEY",
    "SCHEDULE_TEMPLATE_KINDS",
    "TEMPLATE_KINDS",
    "TEMPLATE_KIND_EVENING_GLANCE",
    "TEMPLATE_KIND_MORNING_DIGEST",
    "TEMPLATE_KIND_PAYLOAD_KEY",
    "WINDOW_ONLY_PAYLOAD_KEY",
    "TEMPLATE_KIND_REMINDER",
    "TEMPLATE_KIND_REMINDER_AGAIN",
    "TEMPLATE_KIND_WEEK_AHEAD",
    "TEMPLATE_NAMES",
    "UTILITY_TEMPLATE_NAMES",
    "image_template_for",
    "normalize_template_kind",
    "pickup_reminder_parameters",
    "pickup_status",
    "ride_template_name",
    "routine_picture_templates",
    "schedule_parameters",
    "template_for",
    "template_language",
    "utility_template_for",
]
