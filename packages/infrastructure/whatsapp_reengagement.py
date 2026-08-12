"""Shared WhatsApp conversation re-engagement automation."""

from __future__ import annotations

import calendar
import os
import unicodedata
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as time_of_day
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.openai_api import call_openai_response
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.tool_model_selection import resolve_tool_model


REENGAGEMENT_FEATURE_ID = "whatsapp-business-follow-up-outreach-writer"
REENGAGEMENT_FEATURE_NAME = "WhatsApp Re-engagement Assistant"
DEFAULT_REENGAGEMENT_WEEKDAY = 6
DEFAULT_REENGAGEMENT_HOUR = 9
DEFAULT_REENGAGEMENT_MINUTE = 0
DEFAULT_REENGAGEMENT_MONTHS = 6
DEFAULT_REENGAGEMENT_POLL_SECONDS = 300
DEFAULT_REENGAGEMENT_MODEL = "gpt-5.5"
DEFAULT_REENGAGEMENT_INTERVAL_DAYS = 7
DEFAULT_REENGAGEMENT_INACTIVITY_UNIT = "months"
DEFAULT_REENGAGEMENT_INACTIVITY_VALUE = 6
DEFAULT_MAX_CONTEXT_MESSAGES = 100
MAX_CONTEXT_MESSAGES = 100
REENGAGEMENT_INACTIVITY_UNITS = frozenset({"minutes", "hours", "days", "months"})
SCRIPT_LABELS = {
    "arabic": "Arabic",
    "cyrillic": "Cyrillic",
    "hebrew": "Hebrew",
    "latin": "Latin-script",
}


@dataclass
class WhatsAppReengagementConfig:
    enabled: bool = True
    timezone_name: str = ""
    schedule_weekday: int = DEFAULT_REENGAGEMENT_WEEKDAY
    schedule_hour: int = DEFAULT_REENGAGEMENT_HOUR
    schedule_minute: int = DEFAULT_REENGAGEMENT_MINUTE
    inactivity_months: int = DEFAULT_REENGAGEMENT_MONTHS
    poll_seconds: int = DEFAULT_REENGAGEMENT_POLL_SECONDS
    model: str = DEFAULT_REENGAGEMENT_MODEL
    max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    parsed = safe_int(value, default)
    return max(minimum, min(maximum, parsed))


def parse_weekday(value: Any, default: int = DEFAULT_REENGAGEMENT_WEEKDAY) -> int:
    text = normalize_text(value).lower()
    mapping = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }
    if text in mapping:
        return mapping[text]
    try:
        parsed = int(text)
    except ValueError:
        return default
    return parsed if 0 <= parsed <= 6 else default


def load_whatsapp_reengagement_config() -> WhatsAppReengagementConfig:
    return WhatsAppReengagementConfig(
        enabled=parse_bool(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_ENABLED"), default=True),
        timezone_name=normalize_text(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_TIMEZONE")),
        schedule_weekday=parse_weekday(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_WEEKDAY")),
        schedule_hour=max(0, min(23, safe_int(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_HOUR"), DEFAULT_REENGAGEMENT_HOUR))),
        schedule_minute=max(0, min(59, safe_int(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_MINUTE"), DEFAULT_REENGAGEMENT_MINUTE))),
        inactivity_months=max(1, safe_int(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_INACTIVITY_MONTHS"), DEFAULT_REENGAGEMENT_MONTHS)),
        poll_seconds=max(30, safe_int(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_POLL_SECONDS"), DEFAULT_REENGAGEMENT_POLL_SECONDS)),
        model=normalize_text(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_MODEL")) or DEFAULT_REENGAGEMENT_MODEL,
        max_context_messages=clamp_int(
            os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_MAX_CONTEXT_MESSAGES"),
            default=DEFAULT_MAX_CONTEXT_MESSAGES,
            minimum=1,
            maximum=MAX_CONTEXT_MESSAGES,
        ),
    )


def resolve_timezone(name: str) -> timezone | ZoneInfo:
    normalized_name = normalize_text(name)
    if normalized_name:
        try:
            return ZoneInfo(normalized_name)
        except ZoneInfoNotFoundError:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def subtract_calendar_months(moment: datetime, months: int) -> datetime:
    if months <= 0:
        return moment

    year = moment.year
    month = moment.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def parse_datetime(value: Any) -> datetime | None:
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


def normalize_schedule_time(value: Any, fallback: str = "") -> str:
    text = normalize_text(value)
    if not text:
        text = normalize_text(fallback)
    if not text:
        return ""
    parts = text.split(":", 1)
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return normalize_schedule_time(fallback, "") if fallback and fallback != text else ""
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return normalize_schedule_time(fallback, "") if fallback and fallback != text else ""
    return f"{hour:02d}:{minute:02d}"


def normalize_inactivity_unit(value: Any, fallback: str = DEFAULT_REENGAGEMENT_INACTIVITY_UNIT) -> str:
    text = normalize_text(value).lower()
    aliases = {
        "m": "minutes",
        "min": "minutes",
        "mins": "minutes",
        "minute": "minutes",
        "minutes": "minutes",
        "h": "hours",
        "hr": "hours",
        "hrs": "hours",
        "hour": "hours",
        "hours": "hours",
        "d": "days",
        "day": "days",
        "days": "days",
        "month": "months",
        "months": "months",
    }
    normalized = aliases.get(text, "")
    if normalized in REENGAGEMENT_INACTIVITY_UNITS:
        return normalized
    fallback_normalized = aliases.get(normalize_text(fallback).lower(), "")
    return fallback_normalized if fallback_normalized in REENGAGEMENT_INACTIVITY_UNITS else DEFAULT_REENGAGEMENT_INACTIVITY_UNIT


def default_schedule_time(config: WhatsAppReengagementConfig | None = None) -> str:
    source = config or WhatsAppReengagementConfig()
    return f"{source.schedule_hour:02d}:{source.schedule_minute:02d}"


def normalize_reengagement_settings(
    settings: dict[str, Any] | None = None,
    *,
    config: WhatsAppReengagementConfig | None = None,
) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    resolved_config = config or WhatsAppReengagementConfig()
    inactivity_unit = normalize_inactivity_unit(
        source.get("inactivityUnit") or source.get("inactivity_unit") or source.get("inactivityCadence"),
        DEFAULT_REENGAGEMENT_INACTIVITY_UNIT,
    )
    legacy_months = source.get("inactivityMonths") or source.get("inactivity_months")
    inactivity_default = (
        resolved_config.inactivity_months
        if inactivity_unit == "months"
        else DEFAULT_REENGAGEMENT_INACTIVITY_VALUE
    )
    inactivity_value_source = source.get("inactivityValue")
    if inactivity_value_source in (None, "") and legacy_months not in (None, ""):
        inactivity_value_source = legacy_months
        inactivity_unit = "months"

    return {
        "model": normalize_text(source.get("model")) or resolved_config.model,
        "intervalDays": clamp_int(
            source.get("intervalDays") or source.get("interval_days"),
            default=DEFAULT_REENGAGEMENT_INTERVAL_DAYS,
            minimum=1,
            maximum=365,
        ),
        "scheduleTimeLocal": normalize_schedule_time(
            source.get("scheduleTimeLocal") or source.get("scheduleTime") or source.get("schedule_time"),
            default_schedule_time(resolved_config),
        ),
        "scheduleTimezone": normalize_text(
            source.get("scheduleTimezone") or source.get("scheduleTimeZone") or resolved_config.timezone_name
        ),
        "scheduleWeekday": parse_weekday(
            source.get("scheduleWeekday") or source.get("schedule_weekday"),
            default=resolved_config.schedule_weekday,
        ),
        "inactivityValue": clamp_int(
            inactivity_value_source,
            default=inactivity_default,
            minimum=1,
            maximum=10000,
        ),
        "inactivityUnit": inactivity_unit,
        "maxContextMessages": clamp_int(
            source.get("maxContextMessages") or source.get("max_context_messages"),
            default=resolved_config.max_context_messages,
            minimum=1,
            maximum=MAX_CONTEXT_MESSAGES,
        ),
    }


def reengagement_anchor_date(schedule_weekday: int = DEFAULT_REENGAGEMENT_WEEKDAY) -> date:
    # 1970-01-05 was a Monday. Offsetting from it preserves the previous weekly default.
    return (datetime(1970, 1, 5, tzinfo=timezone.utc) + timedelta(days=schedule_weekday)).date()


def latest_reengagement_scheduled_slot(
    moment: datetime,
    settings: dict[str, Any],
    tz: timezone | ZoneInfo,
) -> datetime:
    local_moment = moment.astimezone(tz)
    schedule_time = normalize_schedule_time(settings.get("scheduleTimeLocal"), DEFAULT_REENGAGEMENT_HOUR)
    if not schedule_time:
        schedule_time = default_schedule_time()
    hour, minute = [int(part) for part in schedule_time.split(":", 1)]
    interval_days = clamp_int(
        settings.get("intervalDays"),
        default=DEFAULT_REENGAGEMENT_INTERVAL_DAYS,
        minimum=1,
        maximum=365,
    )
    candidate_day = local_moment.date()
    candidate = datetime.combine(candidate_day, time_of_day(hour, minute), tzinfo=tz)
    if candidate > local_moment:
        candidate_day -= timedelta(days=1)
        candidate = datetime.combine(candidate_day, time_of_day(hour, minute), tzinfo=tz)

    anchor_day = reengagement_anchor_date(parse_weekday(settings.get("scheduleWeekday")))
    days_since_anchor = (candidate_day - anchor_day).days
    if days_since_anchor >= 0:
        offset_days = days_since_anchor % interval_days
        scheduled_day = candidate_day - timedelta(days=offset_days)
    else:
        offset_days = (-days_since_anchor) % interval_days
        scheduled_day = candidate_day - timedelta(days=(interval_days - offset_days) % interval_days)
    scheduled = datetime.combine(scheduled_day, time_of_day(hour, minute), tzinfo=tz)
    if scheduled > local_moment:
        scheduled -= timedelta(days=interval_days)
    return scheduled.astimezone(timezone.utc)


def resolve_next_reengagement_slot(
    *,
    now: datetime,
    settings: dict[str, Any],
    tz: timezone | ZoneInfo,
) -> datetime:
    current_time = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    latest_slot = latest_reengagement_scheduled_slot(current_time, settings, tz)
    interval_days = clamp_int(
        settings.get("intervalDays"),
        default=DEFAULT_REENGAGEMENT_INTERVAL_DAYS,
        minimum=1,
        maximum=365,
    )
    next_local = latest_slot.astimezone(tz) + timedelta(days=interval_days)
    return next_local.astimezone(timezone.utc)


def resolve_reengagement_cutoff_at(
    *,
    now: datetime,
    settings: dict[str, Any],
    tz: timezone | ZoneInfo,
) -> datetime:
    current_time = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    local_time = current_time.astimezone(tz)
    value = clamp_int(settings.get("inactivityValue"), default=DEFAULT_REENGAGEMENT_INACTIVITY_VALUE, minimum=1, maximum=10000)
    unit = normalize_inactivity_unit(settings.get("inactivityUnit"))
    if unit == "minutes":
        return (local_time - timedelta(minutes=value)).astimezone(timezone.utc)
    if unit == "hours":
        return (local_time - timedelta(hours=value)).astimezone(timezone.utc)
    if unit == "days":
        return (local_time - timedelta(days=value)).astimezone(timezone.utc)
    return subtract_calendar_months(local_time, value).astimezone(timezone.utc)


def latest_scheduled_slot(moment: datetime, config: WhatsAppReengagementConfig, tz: timezone | ZoneInfo) -> datetime:
    local_moment = moment.astimezone(tz)
    days_since_schedule = (local_moment.weekday() - config.schedule_weekday) % 7
    scheduled_day = local_moment.date() - timedelta(days=days_since_schedule)
    scheduled_local = datetime.combine(
        scheduled_day,
        time_of_day(config.schedule_hour, config.schedule_minute),
        tzinfo=tz,
    )
    if scheduled_local > local_moment:
        scheduled_local -= timedelta(days=7)
    return scheduled_local.astimezone(timezone.utc)


def format_message_time(value: str, tz: timezone | ZoneInfo) -> str:
    text = normalize_text(value)
    if not text:
        return "Unknown"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%b %d, %Y")


def short_customer_name(conversation: dict[str, Any]) -> str:
    sender_name = normalize_text(conversation.get("senderName"))
    if sender_name and not sender_name.isdigit():
        return sender_name
    sender_wa_id = normalize_text(conversation.get("senderWaId"))
    return sender_wa_id or "this client"


def detect_character_script(char: str) -> str:
    if not char.isalpha():
        return ""
    name = unicodedata.name(char, "")
    if "HEBREW" in name:
        return "hebrew"
    if "ARABIC" in name:
        return "arabic"
    if "CYRILLIC" in name:
        return "cyrillic"
    if "LATIN" in name:
        return "latin"
    return ""


def dominant_text_script(*values: str) -> str:
    counts = {script: 0 for script in SCRIPT_LABELS}
    for value in values:
        for char in normalize_text(value):
            script = detect_character_script(char)
            if script:
                counts[script] += 1
    script, count = max(counts.items(), key=lambda item: item[1])
    return script if count else ""


def dominant_conversation_script(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    texts = [normalize_text(message.get("text")) for message in messages if normalize_text(message.get("text"))]
    if not texts:
        last_message_text = normalize_text(conversation.get("lastMessageText"))
        if last_message_text:
            texts.append(last_message_text)
    return dominant_text_script(*texts)


def customer_name_matches_conversation_script(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    customer_name: str,
) -> bool:
    conversation_script = dominant_conversation_script(conversation, messages)
    name_script = dominant_text_script(customer_name)
    return not conversation_script or not name_script or conversation_script == name_script


def draft_uses_disallowed_customer_name(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    draft_text: str,
) -> bool:
    customer_name = short_customer_name(conversation)
    if customer_name == "this client" or customer_name_matches_conversation_script(conversation, messages, customer_name):
        return False
    tokens = [token.strip(".,:;!?()[]{}\"'") for token in customer_name.split()]
    blocked_tokens = [token for token in tokens if len(token) > 1]
    return any(token and token in draft_text for token in blocked_tokens)


def draft_matches_conversation_script(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    draft_text: str,
) -> bool:
    conversation_script = dominant_conversation_script(conversation, messages)
    draft_script = dominant_text_script(draft_text)
    return not conversation_script or not draft_script or conversation_script == draft_script


def is_reengagement_draft_compatible(
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    draft_text: str,
) -> bool:
    return draft_matches_conversation_script(
        conversation,
        messages,
        draft_text,
    ) and not draft_uses_disallowed_customer_name(
        conversation,
        messages,
        draft_text,
    ) and not draft_uses_unsupported_generic_reference(
        draft_text,
    )


def draft_uses_unsupported_generic_reference(draft_text: str) -> bool:
    text = normalize_text(draft_text).lower()
    unsupported_phrases = (
        "help with this",
        "help with that",
        "checking in on this",
        "still like to continue",
        "want to continue",
        "pick it up from there",
        "message me here",
        "עזרה עם זה",
        "לעזור עם זה",
        "רלוונטי להמשיך",
        "נמשיך משם",
        "שלחו לי הודעה כאן",
    )
    return any(phrase in text for phrase in unsupported_phrases)


def build_context_excerpt(messages: list[dict[str, Any]], limit: int = DEFAULT_MAX_CONTEXT_MESSAGES) -> str:
    lines: list[str] = []
    for message in messages[-limit:]:
        direction = normalize_text(message.get("direction")).lower()
        role = "Customer" if direction == "inbound" else "Business"
        text = normalize_text(message.get("text"))
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return "\n".join(lines).strip()


def conversation_indicates_completed_work(messages: list[dict[str, Any]]) -> bool:
    text = "\n".join(normalize_text(message.get("text")) for message in messages)
    lowered = text.lower()
    completed_markers = (
        "העבודה הושלמה",
        "העבודה הסתיימה",
        "הסתיימה מבחינתי",
        "הכול סגור",
        "הכל סגור",
        "מבחינתי הכול סגור",
        "מבחינתי הכל סגור",
        "אין צורך בשינויים נוספים",
        "סוגר את הקריאה",
        "תשלום התקבל",
        "קיבלתי את הקבלה",
        "קיבלתי את החשבונית",
        "work is complete",
        "job is complete",
        "everything is closed",
        "all set",
        "no further changes",
        "final payment",
        "payment received",
        "invoice received",
    )
    return any(marker in lowered for marker in completed_markers)


def build_shared_profile_notes(profile: Any) -> list[str]:
    payload = profile if isinstance(profile, dict) else {}
    notes: list[str] = []
    business_summary = normalize_text(payload.get("businessSummary"))
    customer_notes = normalize_text(payload.get("customerNotes"))
    assistant_guidance = normalize_text(payload.get("assistantGuidance"))
    if business_summary:
        notes.append(f"About the client or business: {business_summary}")
    if customer_notes:
        notes.append(f"Typical customers and requests: {customer_notes}")
    if assistant_guidance:
        notes.append(f"Always keep in mind: {assistant_guidance}")
    return notes


def build_reengagement_prompt(
    *,
    connection: dict[str, Any],
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
) -> str:
    assistant_metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    assistant = assistant_metadata.get("assistant") if isinstance(assistant_metadata.get("assistant"), dict) else {}
    tone_guidance = normalize_text(assistant.get("tone_guidance")) or "Warm, direct, and practical."
    business_notes = normalize_text(assistant.get("business_notes"))
    shared_profile_notes = build_shared_profile_notes(connection.get("profile"))
    last_activity_at = reengagement_activity_at(conversation)
    context = build_context_excerpt(messages)
    customer_name = short_customer_name(conversation)
    conversation_script = dominant_conversation_script(conversation, messages)
    conversation_script_label = SCRIPT_LABELS.get(conversation_script, "the conversation language")
    name_script_matches = customer_name_matches_conversation_script(conversation, messages, customer_name)

    sections = [
        "Write one WhatsApp re-engagement message for a business owner to send manually to an old customer.",
        "Write in the main language of the conversation context. Do not choose the language from the customer name.",
        "Keep it low-pressure, natural, and easy to copy.",
        (
            "Mention a concrete topic only when it is clearly present in the conversation. "
            "If the context is thin or unclear, use a neutral check-in that does not point at a task, "
            "problem, quote, appointment, 'this', 'that', or a next step that is not actually in the context."
        ),
        (
            "For thin context, prefer wording like 'היי, רציתי לבדוק אם עדיין רלוונטי מבחינתכם. "
            "אם כן, תגידו לי.' in Hebrew, or 'Hi, just checking whether staying in touch still "
            "makes sense for you. If so, tell me.' in English."
        ),
        (
            "When the conversation clearly says the work was completed, keep the follow-up service-oriented, "
            "for example 'היי, רציתי לבדוק שהכול עדיין בסדר. אם יש משהו לעדכן או לשפר, דברו איתי.'"
        ),
        (
            "Use direct, human phrasing. Avoid passive sign-offs like 'אפשר לשלוח לי הודעה ואמשיך משם'; "
            "prefer casual wording like 'דברו איתי' or 'תגידו לי' when writing Hebrew."
        ),
        "Do not use the customer name by default. Use it only if it naturally fits the conversation.",
        "Never include the customer name when it is written in a different language or script from the conversation.",
        "Do not invent discounts, availability, or facts that are not in the conversation.",
        "Do not add labels, bullets, quotes, or explanation. Return only the message text.",
        f"Tone guidance: {tone_guidance}",
    ]
    if conversation_script:
        sections.append(f"Detected conversation script: {conversation_script_label}.")
    if business_notes:
        sections.append(f"Business notes: {business_notes}")
    if shared_profile_notes:
        sections.append("Shared client context:\n" + "\n".join(f"- {item}" for item in shared_profile_notes))
    if customer_name != "this client":
        customer_name_note = (
            f"Customer display name (optional, use only if natural): {customer_name}"
            if name_script_matches
            else f"Customer display name (do not use in the message; different script from conversation): {customer_name}"
        )
        sections.append(customer_name_note)
    sections.extend(
        [
            f"Last customer activity at: {last_activity_at}",
            "Conversation context:",
            context or "No saved context.",
        ]
    )
    return "\n\n".join(sections).strip()


def build_fallback_draft(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    latest_inbound = ""
    for message in reversed(messages):
        if normalize_text(message.get("direction")).lower() == "inbound":
            latest_inbound = normalize_text(message.get("text"))
            break

    conversation_script = dominant_conversation_script(conversation, messages)
    lowered = latest_inbound.lower()
    if conversation_script == "hebrew":
        if conversation_indicates_completed_work(messages):
            return "היי, רציתי לבדוק שהכול עדיין בסדר. אם יש משהו לעדכן או לשפר, דברו איתי."
        if any(keyword in latest_inbound for keyword in ("הצעת מחיר", "מחיר", "עלות", "כמה", "הערכה", "הצעה")):
            return "היי, רציתי לבדוק אם הצעת המחיר שדיברנו עליה עדיין רלוונטית. אם כן, דברו איתי."
        if any(keyword in latest_inbound for keyword in ("תור", "פגישה", "לקבוע", "לתאם", "זמן", "מתי", "זמין", "זמינות")):
            return "היי, רציתי לבדוק אם עדיין רלוונטי לתאם את מה שדיברנו עליו. אם כן, תגידו לי ונקבע זמן."
        if any(keyword in latest_inbound for keyword in ("עזרה", "לעזור", "סיוע")):
            return "היי, רציתי לבדוק אם עדיין צריך עזרה. אם כן, דברו איתי."
        return "היי, רציתי לבדוק אם עדיין רלוונטי מבחינתכם. אם כן, תגידו לי."

    if conversation_indicates_completed_work(messages):
        return "Hi, just checking that everything is still okay. If there’s anything to update or improve, tell me."
    if any(keyword in lowered for keyword in ("quote", "price", "cost", "estimate")):
        return "Hi, just checking in on the quote we discussed. If it is still relevant, tell me."
    if any(keyword in lowered for keyword in ("appointment", "schedule", "available", "resched")):
        return "Hi, just checking whether the appointment we discussed is still relevant. If so, tell me and we’ll pick a time."
    if any(keyword in lowered for keyword in ("help", "support", "issue", "problem")):
        return "Hi, just checking in case you still need help. If so, tell me."
    return "Hi, just checking whether staying in touch still makes sense for you. If so, tell me."


def clean_generated_draft(value: str) -> str:
    text = normalize_text(value)
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        text = text[1:-1].strip()
    return text


def reengagement_activity_at(conversation: dict[str, Any]) -> str:
    return normalize_text(conversation.get("lastInboundAt")) or normalize_text(conversation.get("lastMessageAt"))


def reengagement_inactive_seconds(activity_at: Any, evaluated_at: datetime) -> int:
    activity_moment = parse_datetime(activity_at)
    if activity_moment is None:
        return 0
    evaluated_moment = evaluated_at if evaluated_at.tzinfo else evaluated_at.replace(tzinfo=timezone.utc)
    evaluated_moment = evaluated_moment.astimezone(timezone.utc)
    return max(0, int((evaluated_moment - activity_moment).total_seconds()))


def latest_inbound_text(messages: list[dict[str, Any]], fallback: str = "") -> str:
    for message in reversed(messages):
        if normalize_text(message.get("direction")).lower() == "inbound":
            return normalize_text(message.get("text"))
    return normalize_text(fallback)


def build_owner_notification(
    *,
    conversation: dict[str, Any],
    draft_text: str,
    tz: timezone | ZoneInfo,
) -> str:
    customer_name = short_customer_name(conversation)
    sender_wa_id = normalize_text(conversation.get("senderWaId"))
    last_message_at = format_message_time(reengagement_activity_at(conversation), tz)
    lines = [
        "This client wasn't reached in a long time, here's a re-engagement message.",
        "",
        f"Client: {customer_name}",
    ]
    if sender_wa_id:
        lines.append(f"WhatsApp: {sender_wa_id}")
    lines.extend(
        [
            f"Last customer activity: {last_message_at}",
            "",
            "Suggested message:",
            draft_text,
        ]
    )
    return "\n".join(lines)


def build_demo_owner_notification(
    *,
    conversation: dict[str, Any],
    draft_text: str,
    tz: timezone | ZoneInfo,
) -> str:
    return "\n".join(
        [
            "Demo result from Assistyca.",
            "No customer message was sent.",
            "",
            build_owner_notification(
                conversation=conversation,
                draft_text=draft_text,
                tz=tz,
            ),
        ]
    )


def build_owner_report(
    *,
    candidates: list[dict[str, Any]],
    tz: timezone | ZoneInfo,
    demo: bool = False,
) -> str:
    if not candidates:
        return ""

    header = [
        "Demo result from Assistyca." if demo else "Assistyca re-engagement report.",
        "No customer message was sent." if demo else "Customers were not contacted.",
        "",
        (
            f"Found {len(candidates)} inactive conversation"
            f"{'' if len(candidates) == 1 else 's'}."
        ),
    ]
    sections: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        sections.append(
            "\n".join(
                [
                    f"Result {index}:",
                    build_owner_notification(
                        conversation=candidate,
                        draft_text=normalize_text(candidate.get("draftText")),
                        tz=tz,
                    ),
                ]
            )
        )
    return "\n\n".join(["\n".join(header), *sections])


def build_demo_no_candidates_notification(
    *,
    settings: dict[str, Any],
    cutoff_at: datetime,
    tz: timezone | ZoneInfo,
) -> str:
    value = clamp_int(
        settings.get("inactivityValue"),
        default=DEFAULT_REENGAGEMENT_INACTIVITY_VALUE,
        minimum=1,
        maximum=10000,
    )
    unit = normalize_inactivity_unit(settings.get("inactivityUnit"))
    unit_label = unit[:-1] if value == 1 and unit.endswith("s") else unit
    cutoff_label = format_message_time(cutoff_at.isoformat(), tz)
    return "\n".join(
        [
            "Demo result from Assistyca.",
            "No customer message was sent.",
            "",
            "No inactive conversations matched the current settings.",
            f"Looking for: no activity for more than {value} {unit_label}.",
            f"Cutoff checked: {cutoff_label}.",
        ]
    )


def is_mock_whatsapp_message_id(value: Any) -> bool:
    return normalize_text(value).startswith("mock-")


def resolve_owner_delivery_mode(message_ids: list[str]) -> str:
    if not message_ids:
        return "none"
    if all(is_mock_whatsapp_message_id(message_id) for message_id in message_ids):
        return "mock"
    if any(is_mock_whatsapp_message_id(message_id) for message_id in message_ids):
        return "mixed"
    return "live"


def normalize_owner_delivery_result(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        message_id = normalize_text(value.get("messageId") or value.get("message_id") or value.get("id"))
        delivery_mode = normalize_text(value.get("deliveryMode") or value.get("delivery_mode")).lower()
        report_id = normalize_text(value.get("reportId") or value.get("report_id"))
    else:
        message_id = normalize_text(value)
        delivery_mode = ""
        report_id = ""
    if not delivery_mode:
        delivery_mode = "mock" if is_mock_whatsapp_message_id(message_id) else "live" if message_id else "none"
    return {
        "messageId": message_id,
        "deliveryMode": delivery_mode,
        "reportId": report_id,
    }


def resolve_owner_delivery_mode_from_results(deliveries: list[dict[str, str]]) -> str:
    modes = {normalize_text(delivery.get("deliveryMode")).lower() for delivery in deliveries}
    modes.discard("")
    modes.discard("none")
    if not modes:
        return resolve_owner_delivery_mode([normalize_text(delivery.get("messageId")) for delivery in deliveries])
    if modes == {"mock"}:
        return "mock"
    if modes == {"template_prompt"}:
        return "template_prompt"
    if modes == {"live"}:
        return "live"
    return "mixed"


class WhatsAppReengagementScheduler:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        send_owner_message: Callable[[dict[str, Any], str], Any],
        config: WhatsAppReengagementConfig | None = None,
    ) -> None:
        self.database = database
        self.send_owner_message = send_owner_message
        self.config = config or load_whatsapp_reengagement_config()
        self.timezone = resolve_timezone(self.config.timezone_name)

    def _generate_draft(
        self,
        *,
        connection: dict[str, Any],
        conversation: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> tuple[str, str, str, dict[str, Any]]:
        settings = connection.get("settings") if isinstance(connection.get("settings"), dict) else {}
        selected_model = resolve_tool_model(settings, default=self.config.model)
        prompt = build_reengagement_prompt(
            connection=connection,
            conversation=conversation,
            messages=messages,
        )
        try:
            result = call_openai_response(
                tool_name=REENGAGEMENT_FEATURE_NAME,
                tool_id=REENGAGEMENT_FEATURE_ID,
                billing_email=normalize_text(connection.get("email")).lower(),
                prompt=prompt,
                model=selected_model,
                max_output_tokens=160,
                usage_recorder=self.database,
                price_resolver=self.database.get_model_price,
                config=load_openai_config(strict_tracking=False),
                metadata={
                    "conversationId": normalize_text(conversation.get("conversationId")),
                    "senderWaId": normalize_text(conversation.get("senderWaId")),
                    "featureId": REENGAGEMENT_FEATURE_ID,
                    "selectedModel": selected_model,
                },
            )
            draft_text = clean_generated_draft(result.output_text)
            if draft_text and is_reengagement_draft_compatible(conversation, messages, draft_text):
                return (
                    draft_text,
                    "openai",
                    normalize_text(result.model),
                    {
                        "requestId": result.request_id,
                        "responseId": result.response_id,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic draft
            fallback = build_fallback_draft(conversation, messages)
            return fallback, "fallback", "", {"error": str(exc)}

        return build_fallback_draft(conversation, messages), "fallback", "", {}

    def _process_target(
        self,
        *,
        connection: dict[str, Any],
        scheduled_for: datetime,
        cutoff_at: datetime,
        settings: dict[str, Any],
        tz: timezone | ZoneInfo,
    ) -> dict[str, Any]:
        user_id = int(connection.get("userId") or 0)
        max_context_messages = clamp_int(
            settings.get("maxContextMessages"),
            default=self.config.max_context_messages,
            minimum=1,
            maximum=MAX_CONTEXT_MESSAGES,
        )
        conversation_scan = self.database.scan_whatsapp_reengagement_conversations(
            user_id=user_id,
            cutoff_at=cutoff_at,
        )
        due_conversations = list(conversation_scan.get("conversations") or [])
        saved_conversations_count = int(conversation_scan.get("savedConversationsCount") or len(due_conversations))
        skipped_conversations = (
            conversation_scan.get("skippedCounts")
            if isinstance(conversation_scan.get("skippedCounts"), dict)
            else {}
        )
        candidates: list[dict[str, Any]] = []
        errors: list[str] = []

        for conversation in due_conversations:
            messages = self.database.list_whatsapp_conversation_messages(
                normalize_text(conversation.get("conversationId")),
                user_id=user_id,
                limit=max_context_messages,
            )
            draft_text, source, model_name, draft_metadata = self._generate_draft(
                connection={**connection, "settings": settings},
                conversation=conversation,
                messages=messages,
            )
            candidates.append(
                {
                    "conversationId": normalize_text(conversation.get("conversationId")),
                    "senderName": normalize_text(conversation.get("senderName")),
                    "senderWaId": normalize_text(conversation.get("senderWaId")),
                    "lastMessageAt": reengagement_activity_at(conversation),
                    "lastMessageText": latest_inbound_text(messages, normalize_text(conversation.get("lastMessageText"))),
                    "messageCount": int(conversation.get("messageCount") or 0),
                    "draftText": draft_text,
                    "source": source,
                    "modelName": model_name,
                    "metadata": draft_metadata,
                }
            )

        notifications_sent = 0
        delivery: dict[str, str] = {"messageId": "", "deliveryMode": "none", "reportId": ""}
        if candidates:
            owner_report = build_owner_report(
                candidates=candidates,
                tz=tz,
                demo=False,
            )
            try:
                delivery = normalize_owner_delivery_result(
                    self.send_owner_message(
                        {
                            **connection,
                            "reengagementReport": {
                                "demo": False,
                                "candidatesCount": len(candidates),
                                "scheduledFor": scheduled_for.isoformat(),
                                "cutoffAt": cutoff_at.isoformat(),
                            },
                        },
                        owner_report,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - log and continue with other threads
                errors.append(str(exc))
            else:
                notifications_sent = 1

        if delivery.get("messageId"):
            for candidate in candidates:
                candidate_metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                self.database.save_whatsapp_reengagement_notification(
                    user_id=user_id,
                    conversation_id=normalize_text(candidate.get("conversationId")),
                    feature_id=REENGAGEMENT_FEATURE_ID,
                    scheduled_for=scheduled_for,
                    owner_message_id=normalize_text(delivery.get("messageId")),
                    draft_text=normalize_text(candidate.get("draftText")),
                    source=normalize_text(candidate.get("source")),
                    model_name=normalize_text(candidate.get("modelName")),
                    metadata={
                        **candidate_metadata,
                        "senderWaId": normalize_text(candidate.get("senderWaId")),
                        "senderName": normalize_text(candidate.get("senderName")),
                        "deliveryMode": normalize_text(delivery.get("deliveryMode")),
                        "reengagementReportId": normalize_text(delivery.get("reportId")),
                    },
                )

        status = "completed"
        if errors and notifications_sent:
            status = "partial"
        elif errors and not notifications_sent:
            status = "failed"

        run_record = self.database.save_whatsapp_reengagement_run(
            user_id=user_id,
            feature_id=REENGAGEMENT_FEATURE_ID,
            scheduled_for=scheduled_for,
            conversations_checked=saved_conversations_count,
            notifications_sent=notifications_sent,
            status=status,
            metadata={
                "cutoffAt": cutoff_at.isoformat(),
                "errors": errors,
                "savedConversationsCount": saved_conversations_count,
                "dueConversationsCount": len(due_conversations),
                "skippedConversations": skipped_conversations,
            },
        )
        return {
            "userId": user_id,
            "email": normalize_text(connection.get("email")).lower(),
            "conversationsChecked": saved_conversations_count,
            "dueConversationsCount": len(due_conversations),
            "skippedConversations": skipped_conversations,
            "notificationsSent": notifications_sent,
            "errors": errors,
            "run": run_record,
        }

    def _build_demo_candidate(
        self,
        *,
        connection: dict[str, Any],
        conversation: dict[str, Any],
        settings: dict[str, Any],
        evaluated_at: datetime,
    ) -> dict[str, Any]:
        user_id = int(connection.get("userId") or 0)
        max_context_messages = clamp_int(
            settings.get("maxContextMessages"),
            default=self.config.max_context_messages,
            minimum=1,
            maximum=MAX_CONTEXT_MESSAGES,
        )
        messages = self.database.list_whatsapp_conversation_messages(
            normalize_text(conversation.get("conversationId")),
            user_id=user_id,
            limit=max_context_messages,
        )
        draft_text, source, model_name, draft_metadata = self._generate_draft(
            connection={**connection, "settings": settings},
            conversation=conversation,
            messages=messages,
        )
        last_message_at = reengagement_activity_at(conversation)
        return {
            "conversationId": normalize_text(conversation.get("conversationId")),
            "senderName": normalize_text(conversation.get("senderName")),
            "senderWaId": normalize_text(conversation.get("senderWaId")),
            "lastMessageAt": last_message_at,
            "inactiveSeconds": reengagement_inactive_seconds(last_message_at, evaluated_at),
            "lastMessageText": latest_inbound_text(messages, normalize_text(conversation.get("lastMessageText"))),
            "messageCount": int(conversation.get("messageCount") or 0),
            "contextMessageCount": len(messages),
            "draftText": draft_text,
            "source": source,
            "modelName": model_name,
            "metadata": draft_metadata,
        }

    def _settings_for_connection(self, connection: dict[str, Any]) -> dict[str, Any]:
        settings = connection.get("settings") if isinstance(connection.get("settings"), dict) else {}
        return normalize_reengagement_settings(settings, config=self.config)

    def _timezone_for_settings(self, settings: dict[str, Any]) -> timezone | ZoneInfo:
        return resolve_timezone(normalize_text(settings.get("scheduleTimezone")) or self.config.timezone_name)

    def _owner_delivery_ready(self, connection: dict[str, Any]) -> bool:
        return bool(
            normalize_text(connection.get("phoneNumberId"))
            and normalize_text(connection.get("ownerWaId"))
            and normalize_text(connection.get("connectionStatus")) == "connected"
            and bool(connection.get("accessTokenConfigured"))
        )

    def run_demo_for_email(
        self,
        email: str,
        *,
        now: datetime | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        connection = self.database.get_whatsapp_reengagement_target(
            email,
            REENGAGEMENT_FEATURE_ID,
            require_active=False,
        )
        if connection is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        user_id = int(connection.get("userId") or 0)
        if user_id <= 0:
            return {
                "ok": False,
                "error": "setup_required",
                "message": "Open WhatsApp details before running a demo.",
            }
        owner_delivery_ready = self._owner_delivery_ready(connection)

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        settings = self._settings_for_connection(connection)
        tz = self._timezone_for_settings(settings)
        scheduled_for = latest_reengagement_scheduled_slot(current_time, settings, tz)
        next_run = resolve_next_reengagement_slot(now=current_time, settings=settings, tz=tz)
        cutoff_at = resolve_reengagement_cutoff_at(now=current_time, settings=settings, tz=tz)
        conversation_scan = self.database.scan_whatsapp_reengagement_conversations(
            user_id=user_id,
            cutoff_at=cutoff_at,
            include_already_notified=True,
        )
        due_conversations = list(conversation_scan.get("conversations") or [])
        saved_conversations_count = int(conversation_scan.get("savedConversationsCount") or len(due_conversations))
        skipped_conversations = (
            conversation_scan.get("skippedCounts")
            if isinstance(conversation_scan.get("skippedCounts"), dict)
            else {}
        )

        candidates: list[dict[str, Any]] = []
        owner_message_ids: list[str] = []
        owner_deliveries: list[dict[str, str]] = []
        delivery_errors: list[str] = []

        def is_cancelled() -> bool:
            return bool(callable(cancel_check) and cancel_check())

        def cancelled_result() -> dict[str, Any]:
            sent_count = len(owner_message_ids)
            report_label = "report" if sent_count == 1 else "reports"
            delivery_mode = resolve_owner_delivery_mode_from_results(owner_deliveries)
            message = (
                f"Demo run cancelled after sending {sent_count} WhatsApp {report_label}. Customers were not contacted."
                if sent_count
                else "Demo run cancelled before any WhatsApp report was sent. Customers were not contacted."
            )
            return {
                "ok": True,
                "demo": True,
                "message": message,
                "run": {
                    "status": "cancelled",
                    "scheduledFor": scheduled_for.isoformat(),
                    "nextRunAt": next_run.isoformat(),
                    "cutoffAt": cutoff_at.isoformat(),
                    "evaluatedAt": current_time.isoformat(),
                    "conversationsChecked": saved_conversations_count,
                    "dueConversationsCount": len(due_conversations),
                    "skippedConversations": skipped_conversations,
                    "candidatesCount": len(candidates),
                    "notificationsSent": sent_count,
                    "ownerWaId": normalize_text(connection.get("ownerWaId")),
                    "deliveryMode": delivery_mode,
                    "portalOnly": not owner_delivery_ready,
                    "settings": settings,
                    "candidates": candidates,
                    "ownerMessageIds": owner_message_ids,
                    "ownerDeliveries": owner_deliveries,
                    "deliveryErrors": delivery_errors,
                },
            }

        for conversation in due_conversations:
            if is_cancelled():
                return cancelled_result()
            candidates.append(
                self._build_demo_candidate(
                    connection=connection,
                    conversation=conversation,
                    settings=settings,
                    evaluated_at=current_time,
                )
            )

        if is_cancelled():
            return cancelled_result()

        if candidates and owner_delivery_ready:
            message_text = build_owner_report(
                candidates=candidates,
                tz=tz,
                demo=True,
            )
            try:
                delivery = normalize_owner_delivery_result(
                    self.send_owner_message(
                        {
                            **connection,
                            "reengagementReport": {
                                "demo": True,
                                "candidatesCount": len(candidates),
                                "scheduledFor": scheduled_for.isoformat(),
                                "cutoffAt": cutoff_at.isoformat(),
                            },
                        },
                        message_text,
                    )
                )
                if delivery.get("messageId"):
                    owner_message_ids.append(normalize_text(delivery.get("messageId")))
                    owner_deliveries.append(delivery)
            except Exception as exc:  # noqa: BLE001 - report delivery failure to the UI
                delivery_errors.append(str(exc))
        elif owner_delivery_ready and saved_conversations_count > 0:
            if is_cancelled():
                return cancelled_result()
            try:
                delivery = normalize_owner_delivery_result(
                    self.send_owner_message(
                        {
                            **connection,
                            "reengagementReport": {
                                "demo": True,
                                "candidatesCount": 0,
                                "scheduledFor": scheduled_for.isoformat(),
                                "cutoffAt": cutoff_at.isoformat(),
                            },
                        },
                        build_demo_no_candidates_notification(
                            settings=settings,
                            cutoff_at=cutoff_at,
                            tz=tz,
                        ),
                    )
                )
                if delivery.get("messageId"):
                    owner_message_ids.append(normalize_text(delivery.get("messageId")))
                    owner_deliveries.append(delivery)
            except Exception as exc:  # noqa: BLE001 - report delivery failure to the UI
                delivery_errors.append(str(exc))

        if is_cancelled():
            return cancelled_result()

        status = "completed" if candidates else "no_candidates"
        if delivery_errors and owner_message_ids:
            status = "partial"
        elif delivery_errors:
            status = "delivery_failed"
        delivery_mode = resolve_owner_delivery_mode_from_results(owner_deliveries)
        if delivery_mode == "mock":
            delivery_action = "simulated the WhatsApp report"
        elif delivery_mode == "template_prompt":
            delivery_action = "sent a WhatsApp template prompt"
        elif delivery_mode == "none":
            delivery_action = "prepared portal results"
        else:
            delivery_action = "sent the results to WhatsApp"
        if not candidates and saved_conversations_count <= 0:
            message = "No saved conversations are available for this demo yet."
        else:
            message = (
                f"Demo found {len(candidates)} inactive conversation"
                f"{'' if len(candidates) == 1 else 's'} and {delivery_action}."
            )
        return {
            "ok": True,
            "demo": True,
            "message": message,
            "run": {
                "status": status,
                "scheduledFor": scheduled_for.isoformat(),
                "nextRunAt": next_run.isoformat(),
                "cutoffAt": cutoff_at.isoformat(),
                "evaluatedAt": current_time.isoformat(),
                "conversationsChecked": saved_conversations_count,
                "dueConversationsCount": len(due_conversations),
                "skippedConversations": skipped_conversations,
                "candidatesCount": len(candidates),
                "notificationsSent": len(owner_message_ids),
                "ownerWaId": normalize_text(connection.get("ownerWaId")),
                "deliveryMode": delivery_mode,
                "portalOnly": not owner_delivery_ready,
                "settings": settings,
                "candidates": candidates,
                "ownerMessageIds": owner_message_ids,
                "ownerDeliveries": owner_deliveries,
                "deliveryErrors": delivery_errors,
            },
        }

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": True, "ran": False, "reason": "disabled"}

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        targets = self.database.list_active_whatsapp_reengagement_targets(REENGAGEMENT_FEATURE_ID)
        runs: list[dict[str, Any]] = []
        skipped = 0
        for connection in targets:
            settings = self._settings_for_connection(connection)
            tz = self._timezone_for_settings(settings)
            scheduled_for = latest_reengagement_scheduled_slot(current_time, settings, tz)
            cutoff_at = resolve_reengagement_cutoff_at(now=current_time, settings=settings, tz=tz)
            existing_run = self.database.get_whatsapp_reengagement_run(
                user_id=int(connection.get("userId") or 0),
                feature_id=REENGAGEMENT_FEATURE_ID,
                scheduled_for=scheduled_for,
            )
            if existing_run is not None:
                skipped += 1
                continue
            runs.append(
                self._process_target(
                    connection=connection,
                    scheduled_for=scheduled_for,
                    cutoff_at=cutoff_at,
                    settings=settings,
                    tz=tz,
                )
            )

        return {
            "ok": True,
            "ran": bool(runs),
            "scheduledFor": runs[-1]["run"]["scheduledFor"] if runs else "",
            "cutoffAt": runs[-1]["run"]["metadata"].get("cutoffAt", "") if runs else "",
            "targets": len(targets),
            "skipped": skipped,
            "runs": runs,
        }

    def serve_forever(self, stop_event: Any, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda message: None)
        while not getattr(stop_event, "is_set", lambda: False)():
            try:
                summary = self.run_pending()
                if summary.get("ran"):
                    total_sent = sum(int(run.get("notificationsSent") or 0) for run in summary.get("runs", []))
                    logger(
                        "[whatsapp-reengagement] "
                        f"scheduled_for={summary.get('scheduledFor')} "
                        f"targets={summary.get('targets')} "
                        f"sent={total_sent}"
                    )
            except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
                logger(f"[whatsapp-reengagement] error: {exc}")
            if getattr(stop_event, "wait", None) is None:
                break
            stop_event.wait(self.config.poll_seconds)
