"""Shared WhatsApp conversation re-engagement automation."""

from __future__ import annotations

import calendar
import os
from dataclasses import dataclass
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
DEFAULT_MAX_CONTEXT_MESSAGES = 24


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
        max_context_messages=max(6, safe_int(os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_MAX_CONTEXT_MESSAGES"), DEFAULT_MAX_CONTEXT_MESSAGES)),
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


def build_context_excerpt(messages: list[dict[str, Any]], limit: int = 12) -> str:
    lines: list[str] = []
    for message in messages[-limit:]:
        direction = normalize_text(message.get("direction")).lower()
        role = "Customer" if direction == "inbound" else "Business"
        text = normalize_text(message.get("text"))
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return "\n".join(lines).strip()


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
    last_message_at = normalize_text(conversation.get("lastMessageAt"))
    context = build_context_excerpt(messages)
    customer_name = short_customer_name(conversation)

    sections = [
        "Write one WhatsApp re-engagement message for a business owner to send manually to an old customer.",
        "Keep it low-pressure, natural, and easy to copy.",
        "Do not invent discounts, availability, or facts that are not in the conversation.",
        "Do not add labels, bullets, quotes, or explanation. Return only the message text.",
        f"Tone guidance: {tone_guidance}",
    ]
    if business_notes:
        sections.append(f"Business notes: {business_notes}")
    if shared_profile_notes:
        sections.append("Shared client context:\n" + "\n".join(f"- {item}" for item in shared_profile_notes))
    sections.extend(
        [
            f"Customer name: {customer_name}",
            f"Last recorded message at: {last_message_at}",
            "Conversation context:",
            context or "No saved context.",
        ]
    )
    return "\n\n".join(sections).strip()


def build_fallback_draft(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    customer_name = short_customer_name(conversation)
    latest_inbound = ""
    for message in reversed(messages):
        if normalize_text(message.get("direction")).lower() == "inbound":
            latest_inbound = normalize_text(message.get("text"))
            break

    lowered = latest_inbound.lower()
    greeting = f"Hi {customer_name}," if customer_name != "this client" else "Hi,"
    if any(keyword in lowered for keyword in ("quote", "price", "cost", "estimate")):
        return f"{greeting} just checking in on the quote we discussed. If you still want to move forward, send me a message and I can pick it up from there."
    if any(keyword in lowered for keyword in ("appointment", "schedule", "available", "resched")):
        return f"{greeting} just checking in in case you still want to continue with the appointment we discussed. If you want to pick a time, message me and I’ll help from there."
    if latest_inbound:
        return f"{greeting} just checking in in case you still need help with this. If you’d like to pick it back up, send me a message and I’ll take it from there."
    return f"{greeting} just checking in in case you still need help. If you want to continue, send me a message and I’ll take it from there."


def clean_generated_draft(value: str) -> str:
    text = normalize_text(value)
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        text = text[1:-1].strip()
    return text


def build_owner_notification(
    *,
    conversation: dict[str, Any],
    draft_text: str,
    tz: timezone | ZoneInfo,
) -> str:
    customer_name = short_customer_name(conversation)
    sender_wa_id = normalize_text(conversation.get("senderWaId"))
    last_message_at = format_message_time(normalize_text(conversation.get("lastMessageAt")), tz)
    lines = [
        "This client wasn't reached in a long time, here's a re-engagement message.",
        "",
        f"Client: {customer_name}",
    ]
    if sender_wa_id:
        lines.append(f"WhatsApp: {sender_wa_id}")
    lines.extend(
        [
            f"Last message: {last_message_at}",
            "",
            "Suggested message:",
            draft_text,
        ]
    )
    return "\n".join(lines)


class WhatsAppReengagementScheduler:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        send_owner_message: Callable[[dict[str, Any], str], str],
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
            if draft_text:
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
    ) -> dict[str, Any]:
        user_id = int(connection.get("userId") or 0)
        due_conversations = self.database.list_due_whatsapp_reengagement_conversations(
            user_id=user_id,
            cutoff_at=cutoff_at,
        )
        notifications_sent = 0
        errors: list[str] = []

        for conversation in due_conversations:
            messages = self.database.list_whatsapp_conversation_messages(
                normalize_text(conversation.get("conversationId")),
                user_id=user_id,
                limit=self.config.max_context_messages,
            )
            draft_text, source, model_name, draft_metadata = self._generate_draft(
                connection=connection,
                conversation=conversation,
                messages=messages,
            )
            owner_notification = build_owner_notification(
                conversation=conversation,
                draft_text=draft_text,
                tz=self.timezone,
            )
            try:
                owner_message_id = self.send_owner_message(connection, owner_notification)
            except Exception as exc:  # noqa: BLE001 - log and continue with other threads
                errors.append(
                    f"{normalize_text(conversation.get('conversationId'))}: {exc}"
                )
                continue

            self.database.save_whatsapp_reengagement_notification(
                user_id=user_id,
                conversation_id=normalize_text(conversation.get("conversationId")),
                feature_id=REENGAGEMENT_FEATURE_ID,
                scheduled_for=scheduled_for,
                owner_message_id=owner_message_id,
                draft_text=draft_text,
                source=source,
                model_name=model_name,
                metadata={
                    **draft_metadata,
                    "senderWaId": normalize_text(conversation.get("senderWaId")),
                    "senderName": normalize_text(conversation.get("senderName")),
                },
            )
            notifications_sent += 1

        status = "completed"
        if errors and notifications_sent:
            status = "partial"
        elif errors and not notifications_sent:
            status = "failed"

        run_record = self.database.save_whatsapp_reengagement_run(
            user_id=user_id,
            feature_id=REENGAGEMENT_FEATURE_ID,
            scheduled_for=scheduled_for,
            conversations_checked=len(due_conversations),
            notifications_sent=notifications_sent,
            status=status,
            metadata={
                "cutoffAt": cutoff_at.isoformat(),
                "errors": errors,
            },
        )
        return {
            "userId": user_id,
            "email": normalize_text(connection.get("email")).lower(),
            "conversationsChecked": len(due_conversations),
            "notificationsSent": notifications_sent,
            "errors": errors,
            "run": run_record,
        }

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": True, "ran": False, "reason": "disabled"}

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        scheduled_for = latest_scheduled_slot(current_time, self.config, self.timezone)
        cutoff_at = subtract_calendar_months(current_time.astimezone(self.timezone), self.config.inactivity_months)
        cutoff_at = cutoff_at.astimezone(timezone.utc)

        targets = self.database.list_active_whatsapp_reengagement_targets(REENGAGEMENT_FEATURE_ID)
        runs: list[dict[str, Any]] = []
        skipped = 0
        for connection in targets:
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
                )
            )

        return {
            "ok": True,
            "ran": bool(runs),
            "scheduledFor": scheduled_for.isoformat(),
            "cutoffAt": cutoff_at.isoformat(),
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
