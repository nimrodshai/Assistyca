"""Shared scheduled web monitoring automation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from hashlib import sha256
from typing import Any
from typing import Callable

from packages.infrastructure.notification_delivery import email_delivery_available
from packages.infrastructure.notification_delivery import load_mail_delivery_config
from packages.infrastructure.notification_delivery import normalize_email
from packages.infrastructure.notification_delivery import normalize_text
from packages.infrastructure.notification_delivery import send_email_notification
from packages.infrastructure.notification_delivery import send_telegram_notification
from packages.infrastructure.notification_delivery import send_whatsapp_notification
from packages.infrastructure.notification_delivery import telegram_delivery_available
from packages.infrastructure.notification_delivery import whatsapp_delivery_available
from packages.infrastructure.openai_api import call_openai_response
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import parse_datetime
from packages.infrastructure.tool_model_selection import resolve_tool_model


MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier"
MONITOR_FEATURE_NAME = "Scheduled Web Monitor"
DEFAULT_MONITOR_MODEL = "gpt-5.5"
DEFAULT_MONITOR_POLL_SECONDS = 300
DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_MONITOR_MAX_OUTPUT_TOKENS = 1800
DEFAULT_MONITOR_MAX_ITEMS = 5
RECENT_SENT_RESULTS_LOOKBACK = timedelta(hours=1)

DEFAULT_MONITOR_SETTINGS = {
    "model": DEFAULT_MONITOR_MODEL,
    "watchItems": [],
    "intervalDays": 7,
    "deliveryChannel": "email",
    "telegramChatId": "",
}

SUPPORTED_DELIVERY_CHANNELS = frozenset({"email", "telegram", "whatsapp"})


class ManualRunCancelledError(RuntimeError):
    """Raised when a user cancels a manual monitor test before delivery starts."""


@dataclass
class ScheduledMonitorConfig:
    enabled: bool = True
    poll_seconds: int = DEFAULT_MONITOR_POLL_SECONDS
    model: str = DEFAULT_MONITOR_MODEL
    search_context_size: str = DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE
    max_output_tokens: int = DEFAULT_MONITOR_MAX_OUTPUT_TOKENS
    max_items_per_run: int = DEFAULT_MONITOR_MAX_ITEMS


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


def load_scheduled_monitor_config() -> ScheduledMonitorConfig:
    return ScheduledMonitorConfig(
        enabled=parse_bool(os.getenv("PORTAL_SCHEDULED_MONITOR_ENABLED"), default=True),
        poll_seconds=max(30, safe_int(os.getenv("PORTAL_SCHEDULED_MONITOR_POLL_SECONDS"), DEFAULT_MONITOR_POLL_SECONDS)),
        model=normalize_text(os.getenv("PORTAL_SCHEDULED_MONITOR_MODEL")) or DEFAULT_MONITOR_MODEL,
        search_context_size=normalize_search_context_size(
            os.getenv("PORTAL_SCHEDULED_MONITOR_SEARCH_CONTEXT_SIZE") or DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE
        ),
        max_output_tokens=max(
            400,
            safe_int(os.getenv("PORTAL_SCHEDULED_MONITOR_MAX_OUTPUT_TOKENS"), DEFAULT_MONITOR_MAX_OUTPUT_TOKENS),
        ),
        max_items_per_run=max(
            1,
            safe_int(os.getenv("PORTAL_SCHEDULED_MONITOR_MAX_ITEMS_PER_RUN"), DEFAULT_MONITOR_MAX_ITEMS),
        ),
    )


def normalize_search_context_size(value: Any) -> str:
    normalized = normalize_text(value).lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    return DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE


def normalize_watch_items(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        text = normalize_text(value)
        raw_items = re.split(r"(?:\r?\n|;)+", text) if text else []

    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", normalize_text(item))
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_items.append(cleaned)
    return normalized_items


def normalize_interval_days(value: Any, default: int = DEFAULT_MONITOR_SETTINGS["intervalDays"]) -> int:
    candidate = safe_int(value, default)
    return max(1, min(365, candidate))


def resolve_monitor_brief(settings: dict[str, Any]) -> str:
    watch_items = normalize_watch_items(settings.get("watchItems"))
    if watch_items:
        return "\n".join(f"- {item}" for item in watch_items)
    return normalize_text(settings.get("searchPrompt"))


def normalize_monitor_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    delivery_channel = normalize_text(source.get("deliveryChannel")).lower()
    if delivery_channel not in SUPPORTED_DELIVERY_CHANNELS:
        delivery_channel = DEFAULT_MONITOR_SETTINGS["deliveryChannel"]

    return {
        "model": resolve_tool_model(source, default=DEFAULT_MONITOR_MODEL),
        "watchItems": normalize_watch_items(source.get("watchItems") or source.get("searchPrompt")),
        "intervalDays": normalize_interval_days(
            source.get("intervalDays")
            or (
                1 if normalize_text(source.get("cadence")).lower() == "daily"
                else 7 if normalize_text(source.get("cadence")).lower() == "weekly"
                else 30 if normalize_text(source.get("cadence")).lower() == "monthly"
                else DEFAULT_MONITOR_SETTINGS["intervalDays"]
            )
        ),
        "deliveryChannel": delivery_channel,
        "telegramChatId": normalize_text(source.get("telegramChatId")),
    }


def validate_monitor_settings(
    settings: dict[str, Any] | None,
    *,
    user_email: str = "",
    email_available: bool | None = None,
    telegram_available: bool | None = None,
    whatsapp_available: bool | None = None,
    openai_available: bool | None = None,
    whatsapp_connection: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    normalized = normalize_monitor_settings(settings)
    issues: list[dict[str, str]] = []
    if not normalized["watchItems"]:
        issues.append({"field": "watchItems", "message": "Add at least one thing this monitor should check."})

    openai_enabled = (
        bool(normalize_text(load_openai_config(strict_tracking=False).api_key))
        if openai_available is None
        else bool(openai_available)
    )
    if not openai_enabled:
        issues.append({
            "field": "watchItems",
            "message": "Scheduled Web Monitor is not configured on the backend yet. Add OPENAI_API_KEY to enable searches.",
        })

    delivery_channel = normalized["deliveryChannel"]
    email_enabled = email_delivery_available(load_mail_delivery_config()) if email_available is None else bool(email_available)
    telegram_enabled = telegram_delivery_available() if telegram_available is None else bool(telegram_available)
    whatsapp_enabled = whatsapp_delivery_available() if whatsapp_available is None else bool(whatsapp_available)
    connection = whatsapp_connection if isinstance(whatsapp_connection, dict) else {}
    recipient_email = normalize_email(user_email)

    if delivery_channel == "email":
        if not recipient_email:
            issues.append({"field": "deliveryChannel", "message": "This workspace does not have a valid account email for alerts yet."})
        if not email_enabled:
            issues.append({"field": "deliveryChannel", "message": "Email delivery is not configured on the backend yet."})
    elif delivery_channel == "telegram":
        if not normalized["telegramChatId"]:
            issues.append({"field": "telegramChatId", "message": "Add the Telegram chat id that should receive alerts."})
        if not telegram_enabled:
            issues.append({"field": "deliveryChannel", "message": "Telegram delivery is not configured on the backend yet."})
    elif delivery_channel == "whatsapp":
        if not whatsapp_enabled:
            issues.append({"field": "deliveryChannel", "message": "WhatsApp delivery is not configured on the backend yet."})
        if (
            normalize_text(connection.get("connectionStatus")) != "connected"
            or not normalize_text(connection.get("phoneNumberId"))
            or not normalize_text(connection.get("ownerWaId"))
        ):
            issues.append({"field": "deliveryChannel", "message": "Connect WhatsApp before using WhatsApp alerts."})

    return issues


def build_monitor_setup_status(
    settings: dict[str, Any] | None,
    *,
    user_email: str = "",
    openai_available: bool | None = None,
    whatsapp_connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_monitor_settings(settings)
    issues = validate_monitor_settings(
        normalized,
        user_email=user_email,
        openai_available=openai_available,
        whatsapp_connection=whatsapp_connection,
    )
    if not issues:
        return {
            "required": True,
            "ready": True,
            "requirementKey": "requiresScheduledMonitorConfig",
            "message": "",
            "issues": [],
            "settings": normalized,
        }

    message = issues[0]["message"] if issues else "Finish the monitor settings before activating this tool."
    return {
        "required": True,
        "ready": False,
        "requirementKey": "requiresScheduledMonitorConfig",
        "message": message,
        "issues": issues,
        "settings": normalized,
    }


def resolve_due_monitor_slot(
    *,
    now: datetime,
    settings: dict[str, Any],
    activated_at: str,
    settings_saved_at: str = "",
    last_scheduled_for: str,
) -> datetime | None:
    next_slot = resolve_next_monitor_slot(
        now=now,
        settings=settings,
        activated_at=activated_at,
        settings_saved_at=settings_saved_at,
        last_scheduled_for=last_scheduled_for,
    )
    if next_slot is None:
        return None

    current_time = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    if next_slot > current_time:
        return None
    return next_slot


def resolve_next_monitor_slot(
    *,
    now: datetime,
    settings: dict[str, Any],
    activated_at: str = "",
    settings_saved_at: str = "",
    last_scheduled_for: str = "",
) -> datetime | None:
    current_time = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    interval_days = normalize_interval_days(settings.get("intervalDays"))
    interval = timedelta(days=interval_days)

    anchor_candidates = []
    if normalize_text(activated_at):
        anchor_candidates.append(parse_datetime(activated_at).astimezone(timezone.utc))
    if normalize_text(settings_saved_at):
        anchor_candidates.append(parse_datetime(settings_saved_at).astimezone(timezone.utc))

    reset_anchor = max(anchor_candidates) if anchor_candidates else None
    latest_slot = parse_datetime(last_scheduled_for).astimezone(timezone.utc) if normalize_text(last_scheduled_for) else None
    if latest_slot is not None and (reset_anchor is None or latest_slot >= reset_anchor):
        base_slot = latest_slot
    else:
        base_slot = reset_anchor

    if base_slot is None:
        return None

    next_slot = base_slot + interval
    if next_slot > current_time:
        return next_slot

    elapsed_cycles = (current_time - next_slot) // interval
    return next_slot + (elapsed_cycles * interval)


def extract_json_payload(text: str) -> dict[str, Any]:
    raw = normalize_text(text)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_alert_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    title = normalize_text(payload.get("title"))
    source_url = normalize_text(payload.get("source_url") or payload.get("sourceUrl"))
    event_date = normalize_text(payload.get("event_date") or payload.get("eventDate"))
    signature_basis = "|".join(
        [
            title.lower(),
            source_url.lower(),
            event_date,
            normalize_text(payload.get("source_name") or payload.get("sourceName")).lower(),
        ]
    )
    item_key = normalize_text(payload.get("id")) or sha256(signature_basis.encode("utf-8")).hexdigest()[:24]
    return {
        "id": item_key,
        "title": title or "Untitled alert",
        "summary": normalize_text(payload.get("summary")),
        "whyItMatters": normalize_text(payload.get("why_it_matters") or payload.get("whyItMatters")),
        "eventDate": event_date,
        "sourceName": normalize_text(payload.get("source_name") or payload.get("sourceName")),
        "sourceUrl": source_url,
        "urgency": normalize_text(payload.get("urgency")).lower() or "medium",
    }


def notification_to_alert_item(notification: dict[str, Any]) -> dict[str, Any]:
    payload = notification if isinstance(notification, dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "id": normalize_text(payload.get("itemKey")) or normalize_text(payload.get("id")),
        "title": normalize_text(payload.get("title")) or "Untitled alert",
        "summary": normalize_text(metadata.get("summary")),
        "whyItMatters": normalize_text(metadata.get("whyItMatters")),
        "eventDate": normalize_text(payload.get("eventDate")),
        "sourceName": normalize_text(payload.get("sourceName")),
        "sourceUrl": normalize_text(payload.get("sourceUrl")),
        "urgency": normalize_text(metadata.get("urgency")).lower() or "medium",
    }


def build_monitor_prompt(
    *,
    target: dict[str, Any],
    settings: dict[str, Any],
    scheduled_for: datetime,
    last_successful_run_at: str,
    max_items: int,
) -> str:
    prompt = target.get("prompt") if isinstance(target.get("prompt"), dict) else {}
    watch_items = normalize_watch_items(settings.get("watchItems"))
    lines = [
        "Search the public web and find only relevant, real-world updates for this business monitor.",
        "Return valid JSON only.",
        "",
        "Required JSON shape:",
        '{',
        '  "summary": "short plain-language summary",',
        '  "items": [',
        '    {',
        '      "id": "stable-unique-id-or-empty",',
        '      "title": "item title",',
        '      "summary": "what happened",',
        '      "why_it_matters": "why the client should care",',
        '      "event_date": "YYYY-MM-DD or empty",',
        '      "source_name": "publisher name",',
        '      "source_url": "https://...",',
        '      "urgency": "low|medium|high"',
        "    }",
        "  ]",
        "}",
        "",
        f"Today is {scheduled_for.astimezone(timezone.utc).date().isoformat()} UTC.",
        f"Only include at most {max_items} items.",
        "If nothing relevant is found, return an empty items array.",
        "Prefer concrete events, deadlines, conference announcements, holiday dates, or changes with a source URL.",
        "Never invent a source, URL, event date, or organization.",
        "Only include matches that are genuinely useful enough to float up to the client.",
        f"Tone guidance: {normalize_text(prompt.get('toneGuidance')) or 'Clear, useful, and concise.'}",
        f"Prioritization rules: {normalize_text(prompt.get('replyRules')) or 'Only alert when there is a concrete, useful match.'}",
    ]
    business_notes = normalize_text(prompt.get("businessNotes"))
    if business_notes:
        lines.append(f"Business context: {business_notes}")
    escalation = normalize_text(prompt.get("escalationGuidance"))
    if escalation:
        lines.append(f"Escalation guidance: {escalation}")
    example_replies = normalize_text(prompt.get("exampleReplies"))
    if example_replies:
        lines.append(f"Example alert style: {example_replies}")
    if normalize_text(last_successful_run_at):
        lines.append(f"Last successful run: {normalize_text(last_successful_run_at)}")
    lines.append("Things to check:")
    if watch_items:
        lines.extend(f"- {item}" for item in watch_items)
    else:
        lines.append(f"- {resolve_monitor_brief(settings)}")
    return "\n".join(lines).strip()


def build_notification_subject(target: dict[str, Any], item_count: int) -> str:
    count_label = "1 new match" if item_count == 1 else f"{item_count} new matches"
    return f"Quick monitor update: {count_label}"


def build_manual_replay_subject() -> str:
    return "Quick monitor test: latest results"


def build_no_results_subject(target: dict[str, Any]) -> str:
    return "Quick monitor update: nothing new yet"


def build_notification_text(
    *,
    target: dict[str, Any],
    summary: str,
    items: list[dict[str, Any]],
    scheduled_for: datetime,
) -> str:
    lines = [
        "Quick monitor update",
        "",
        f"Checked on {scheduled_for.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        summary or "I found a few new things you may want to look at.",
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                "",
                f"{index}. {item['title']}",
                item["summary"] or "Relevant update found.",
            ]
        )
        if item["whyItMatters"]:
            lines.append(f"Why it matters: {item['whyItMatters']}")
        if item["eventDate"]:
            lines.append(f"Date: {item['eventDate']}")
        if item["sourceName"] or item["sourceUrl"]:
            source = item["sourceName"] or item["sourceUrl"]
            if item["sourceUrl"] and item["sourceUrl"] != source:
                source = f"{source} - {item['sourceUrl']}"
            lines.append(f"Source: {source}")
        if item["urgency"]:
            lines.append(f"Urgency: {item['urgency']}")
    return "\n".join(lines)


def build_no_results_text(
    *,
    settings: dict[str, Any],
    scheduled_for: datetime,
    status: str = "no_matches",
    recent_results_already_sent: bool = False,
) -> str:
    watch_items = normalize_watch_items(settings.get("watchItems"))
    lines = [
        "Quick monitor update",
        "",
        f"Checked on {scheduled_for.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "Here's what I checked:",
    ]
    if watch_items:
        lines.extend(f"- {item}" for item in watch_items)
    else:
        brief = resolve_monitor_brief(settings)
        lines.append(f"- {brief or 'Your saved watch list'}")

    lines.extend(
        [
            "",
            (
                "Nothing new worth sending right now. I already sent the latest results earlier."
                if normalize_text(status) == "no_matches" and recent_results_already_sent
                else "Nothing new worth sending right now."
                if normalize_text(status) == "no_matches"
                else "Nothing new to send right now. I already shared the useful matches earlier."
            ),
        ]
    )
    return "\n".join(lines)


def build_notification_html(subject: str, text_body: str) -> str:
    safe_subject = subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_body = text_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br />")
    return (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;background:#f4f7fb;padding:24px;\">"
        "<div style=\"max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #dce7f0;border-radius:20px;padding:24px;\">"
        f"<h1 style=\"margin:0 0 18px;font-size:24px;line-height:1.2;color:#122230;\">{safe_subject}</h1>"
        f"<div style=\"font-size:15px;line-height:1.6;color:#334155;\">{safe_body}</div>"
        "</div></body></html>"
    )


class ScheduledMonitorScheduler:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        config: ScheduledMonitorConfig | None = None,
    ) -> None:
        self.database = database
        self.config = config or load_scheduled_monitor_config()

    def _normalize_now(self, now: datetime | None = None) -> datetime:
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        return current_time.astimezone(timezone.utc)

    def _raise_if_cancelled(self, cancel_check: Callable[[], bool] | None = None) -> None:
        if callable(cancel_check) and bool(cancel_check()):
            raise ManualRunCancelledError("Manual run cancelled.")

    def _build_target_for_email(self, email: str) -> dict[str, Any] | None:
        normalized_email = normalize_email(email)
        if not normalized_email:
            return None

        feature = self.database.get_assigned_feature(normalized_email, MONITOR_FEATURE_ID)
        if feature is None:
            return None

        activation = self.database.get_feature_activation(normalized_email, MONITOR_FEATURE_ID) or {}
        assignment = feature.get("assignment") if isinstance(feature.get("assignment"), dict) else {}
        assignment_metadata = assignment.get("metadata") if isinstance(assignment.get("metadata"), dict) else {}
        saved_prompt = assignment_metadata.get("prompt") if isinstance(assignment_metadata.get("prompt"), dict) else {}
        saved_settings = assignment_metadata.get("settings") if isinstance(assignment_metadata.get("settings"), dict) else {}
        default_prompt = feature.get("prompt") if isinstance(feature.get("prompt"), dict) else {}
        whatsapp_connection = self.database.get_whatsapp_connection(normalized_email) or {}
        user = self.database.get_user(normalized_email) or {}

        return {
            "userId": int(activation.get("userId") or user.get("id") or 0),
            "email": normalized_email,
            "displayName": normalize_text(user.get("displayName")),
            "featureId": MONITOR_FEATURE_ID,
            "prompt": {
                **default_prompt,
                **saved_prompt,
            },
            "settings": saved_settings if isinstance(saved_settings, dict) else {},
            "settingsSavedAt": normalize_text(assignment_metadata.get("settingsSavedAt")),
            "activatedAt": activation.get("activatedAt"),
            "activationUpdatedAt": activation.get("updatedAt"),
            "activationMetadata": activation.get("metadata") if isinstance(activation.get("metadata"), dict) else {},
            "phoneNumberId": normalize_text(whatsapp_connection.get("phoneNumberId")),
            "ownerWaId": normalize_text(whatsapp_connection.get("ownerWaId")),
            "whatsappConnection": {
                "phoneNumberId": normalize_text(whatsapp_connection.get("phoneNumberId")),
                "ownerWaId": normalize_text(whatsapp_connection.get("ownerWaId")),
                "connectionStatus": normalize_text(whatsapp_connection.get("connectionStatus")),
            },
        }

    def _run_search(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        scheduled_for: datetime,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        self._raise_if_cancelled(cancel_check)
        last_run = self.database.get_latest_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
            before_scheduled_for=scheduled_for,
        )
        selected_model = resolve_tool_model(settings, default=self.config.model)
        prompt = build_monitor_prompt(
            target=target,
            settings=settings,
            scheduled_for=scheduled_for,
            last_successful_run_at=normalize_text(last_run.get("scheduledFor")) if last_run else "",
            max_items=self.config.max_items_per_run,
        )
        result = call_openai_response(
            tool_name=MONITOR_FEATURE_NAME,
            tool_id=MONITOR_FEATURE_ID,
            billing_email=normalize_email(target.get("email")),
            prompt=prompt,
            model=selected_model,
            max_output_tokens=self.config.max_output_tokens,
            temperature=0,
            usage_recorder=self.database,
            price_resolver=self.database.get_model_price,
            config=load_openai_config(strict_tracking=False),
            metadata={
                "featureId": MONITOR_FEATURE_ID,
                "deliveryChannel": settings.get("deliveryChannel"),
                "intervalDays": settings.get("intervalDays"),
                "selectedModel": selected_model,
            },
            tools=[{"type": "web_search", "search_context_size": self.config.search_context_size}],
        )
        payload = extract_json_payload(result.output_text)
        raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        items = [
            normalize_alert_item(item)
            for item in raw_items
            if isinstance(item, dict)
        ]
        return (
            normalize_text(payload.get("summary")),
            items[: self.config.max_items_per_run],
            {
                "requestId": result.request_id,
                "responseId": result.response_id,
                "model": normalize_text(result.model),
            },
        )

    def _deliver_message(
        self,
        *,
        target: dict[str, Any],
        subject: str,
        message_text: str,
        html_body: str = "",
        channel: str = "",
    ) -> tuple[str, str]:
        resolved_channel = normalize_text(channel or target.get("deliveryChannel")).lower()
        delivery_target = ""
        delivery_message_id = ""
        if resolved_channel == "email":
            delivery_target = normalize_email(target.get("email"))
            send_email_notification(
                to_email=delivery_target,
                subject=subject,
                text_body=message_text,
                html_body=html_body or build_notification_html(subject, message_text),
            )
        elif resolved_channel == "telegram":
            delivery_target = normalize_text(target.get("telegramChatId"))
            response = send_telegram_notification(chat_id=delivery_target, text=message_text)
            result = response.get("result") if isinstance(response.get("result"), dict) else {}
            delivery_message_id = normalize_text(result.get("message_id"))
        elif resolved_channel == "whatsapp":
            delivery_target = normalize_text(target.get("ownerWaId"))
            delivery_message_id = send_whatsapp_notification(
                phone_number_id=normalize_text(target.get("phoneNumberId")),
                recipient_wa_id=delivery_target,
                message_text=message_text,
            )
        else:
            raise RuntimeError(f"Unsupported delivery channel: {resolved_channel}")

        return delivery_target, delivery_message_id

    def _deliver_items(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        items: list[dict[str, Any]],
        summary: str,
        scheduled_for: datetime,
        subject: str = "",
    ) -> tuple[int, str, str]:
        if not items:
            return 0, "", ""

        message_text = build_notification_text(
            target=target,
            summary=summary,
            items=items,
            scheduled_for=scheduled_for,
        )
        delivery_target, delivery_message_id = self._deliver_message(
            target={
                **target,
                "telegramChatId": settings.get("telegramChatId"),
            },
            subject=subject or build_notification_subject(target, len(items)),
            message_text=message_text,
            channel=normalize_text(settings.get("deliveryChannel")),
        )

        return len(items), delivery_target, delivery_message_id

    def _deliver_no_results_notification(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        scheduled_for: datetime,
        status: str,
        recent_results_already_sent: bool = False,
    ) -> tuple[bool, str, str]:
        message_text = build_no_results_text(
            settings=settings,
            scheduled_for=scheduled_for,
            status=status,
            recent_results_already_sent=recent_results_already_sent,
        )
        delivery_target, delivery_message_id = self._deliver_message(
            target={
                **target,
                "telegramChatId": settings.get("telegramChatId"),
            },
            subject=build_no_results_subject(target),
            message_text=message_text,
            channel=normalize_text(settings.get("deliveryChannel")),
        )
        return True, delivery_target, delivery_message_id

    def _execute_target(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        scheduled_for: datetime,
        persist_run: bool,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        summary = ""
        items: list[dict[str, Any]] = []
        search_metadata: dict[str, Any] = {}
        try:
            self._raise_if_cancelled(cancel_check)
            summary, items, search_metadata = self._run_search(
                target=target,
                settings=settings,
                scheduled_for=scheduled_for,
                cancel_check=cancel_check,
            )
            self._raise_if_cancelled(cancel_check)

            recent_notifications = self.database.list_feature_monitor_notifications(
                user_id=int(target.get("userId") or 0),
                feature_id=MONITOR_FEATURE_ID,
                since_scheduled_for=scheduled_for - RECENT_SENT_RESULTS_LOOKBACK,
                limit=self.config.max_items_per_run,
            )
            settings_saved_at = normalize_text(target.get("settingsSavedAt"))
            if settings_saved_at:
                settings_saved_moment = parse_datetime(settings_saved_at).astimezone(timezone.utc)
                recent_notifications = [
                    notification
                    for notification in recent_notifications
                    if parse_datetime(notification.get("scheduledFor")).astimezone(timezone.utc) >= settings_saved_moment
                ]
            recent_results_already_sent = bool(recent_notifications)
            recent_results_sent_at = normalize_text(recent_notifications[0].get("scheduledFor")) if recent_notifications else ""
            recent_items: list[dict[str, Any]] = []
            for notification in recent_notifications:
                recent_item = notification_to_alert_item(notification)
                if recent_item.get("id"):
                    recent_items.append(recent_item)

            new_items: list[dict[str, Any]] = []
            for item in items:
                if self.database.get_feature_monitor_notification(
                    user_id=int(target.get("userId") or 0),
                    feature_id=MONITOR_FEATURE_ID,
                    item_key=normalize_text(item.get("id")),
                ):
                    continue
                new_items.append(item)

            notifications_sent = 0
            delivery_target = ""
            delivery_message_id = ""
            no_results_notification_sent = False
            status = "completed"
            replayed_recent_results = False
            if not items:
                status = "no_matches"
            elif items and not new_items:
                status = "duplicate_matches"

            live_search_status = status

            if new_items:
                self._raise_if_cancelled(cancel_check)
                notifications_sent, delivery_target, delivery_message_id = self._deliver_items(
                    target=target,
                    settings=settings,
                    items=new_items,
                    summary=summary,
                    scheduled_for=scheduled_for,
                )
            elif not persist_run and recent_items and status in {"no_matches", "duplicate_matches"}:
                self._raise_if_cancelled(cancel_check)
                replayed_recent_results = True
                summary = "Here are the latest results again from your recent monitor test."
                items = recent_items
                notifications_sent, delivery_target, delivery_message_id = self._deliver_items(
                    target=target,
                    settings=settings,
                    items=recent_items,
                    summary=summary,
                    scheduled_for=scheduled_for,
                    subject=build_manual_replay_subject(),
                )
                status = "completed"
            elif status in {"no_matches", "duplicate_matches"}:
                self._raise_if_cancelled(cancel_check)
                no_results_notification_sent, delivery_target, delivery_message_id = self._deliver_no_results_notification(
                    target=target,
                    settings=settings,
                    scheduled_for=scheduled_for,
                    status=status,
                    recent_results_already_sent=recent_results_already_sent if status == "no_matches" else False,
                )

            for item in new_items:
                self.database.save_feature_monitor_notification(
                    user_id=int(target.get("userId") or 0),
                    feature_id=MONITOR_FEATURE_ID,
                    item_key=normalize_text(item.get("id")),
                    scheduled_for=scheduled_for,
                    delivery_channel=normalize_text(settings.get("deliveryChannel")),
                    delivery_target=delivery_target,
                    title=normalize_text(item.get("title")),
                    event_date=normalize_text(item.get("eventDate")),
                    source_url=normalize_text(item.get("sourceUrl")),
                    source_name=normalize_text(item.get("sourceName")),
                    message_text=build_notification_text(
                        target=target,
                        summary=summary,
                        items=[item],
                        scheduled_for=scheduled_for,
                    ),
                    metadata={
                        "summary": normalize_text(item.get("summary")),
                        "whyItMatters": normalize_text(item.get("whyItMatters")),
                        "urgency": normalize_text(item.get("urgency")),
                        "deliveryMessageId": delivery_message_id,
                        **search_metadata,
                    },
                )

            run_metadata = {
                "summary": summary,
                "items": items,
                "newItemIds": [normalize_text(item.get("id")) for item in new_items],
                "watchItems": settings.get("watchItems"),
                "intervalDays": settings.get("intervalDays"),
                "deliveryChannel": normalize_text(settings.get("deliveryChannel")),
                "settingsSavedAt": normalize_text(target.get("settingsSavedAt")),
                "deliveryTarget": delivery_target,
                "noResultsNotificationSent": no_results_notification_sent,
                "noResultsReason": live_search_status if live_search_status in {"no_matches", "duplicate_matches"} else "",
                "recentResultsAlreadySent": recent_results_already_sent if live_search_status == "no_matches" else False,
                "recentResultsSentAt": recent_results_sent_at if live_search_status == "no_matches" else "",
                "replayedRecentResults": replayed_recent_results,
                "liveSearchStatus": live_search_status,
                "deliveryMessageId": delivery_message_id,
                **search_metadata,
            }
            if persist_run:
                run_record = self.database.save_feature_monitor_run(
                    user_id=int(target.get("userId") or 0),
                    feature_id=MONITOR_FEATURE_ID,
                    scheduled_for=scheduled_for,
                    findings_count=len(items),
                    notifications_sent=notifications_sent,
                    status=status,
                    metadata=run_metadata,
                )
            else:
                run_record = {
                    "id": 0,
                    "userId": int(target.get("userId") or 0),
                    "featureId": MONITOR_FEATURE_ID,
                    "scheduledFor": scheduled_for.isoformat(),
                    "findingsCount": len(items),
                    "notificationsSent": notifications_sent,
                    "status": status,
                    "metadata": run_metadata,
                    "createdAt": scheduled_for.isoformat(),
                    "updatedAt": scheduled_for.isoformat(),
                }
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": status,
                "scheduledFor": scheduled_for.isoformat(),
                "findingsCount": len(items),
                "notificationsSent": notifications_sent,
                "run": run_record,
            }
        except ManualRunCancelledError:
            cancelled_metadata = {
                "summary": summary,
                "items": items,
                "newItemIds": [],
                "watchItems": settings.get("watchItems"),
                "intervalDays": settings.get("intervalDays"),
                "deliveryChannel": normalize_text(settings.get("deliveryChannel")),
                "settingsSavedAt": normalize_text(target.get("settingsSavedAt")),
                "deliveryTarget": "",
                "noResultsNotificationSent": False,
                "cancelled": True,
                **search_metadata,
            }
            run_record = {
                "id": 0,
                "userId": int(target.get("userId") or 0),
                "featureId": MONITOR_FEATURE_ID,
                "scheduledFor": scheduled_for.isoformat(),
                "findingsCount": len(items),
                "notificationsSent": 0,
                "status": "cancelled",
                "metadata": cancelled_metadata,
                "createdAt": scheduled_for.isoformat(),
                "updatedAt": scheduled_for.isoformat(),
            }
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "cancelled",
                "scheduledFor": scheduled_for.isoformat(),
                "findingsCount": len(items),
                "notificationsSent": 0,
                "run": run_record,
            }

    def _process_target(self, *, target: dict[str, Any], now: datetime) -> dict[str, Any]:
        settings = normalize_monitor_settings(target.get("settings"))
        setup_status = build_monitor_setup_status(
            settings,
            user_email=normalize_email(target.get("email")),
            whatsapp_connection=target.get("whatsappConnection"),
        )
        if not setup_status["ready"]:
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "skipped",
                "reason": setup_status["message"],
                "notificationsSent": 0,
            }

        last_run = self.database.get_latest_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
        )
        scheduled_for = resolve_due_monitor_slot(
            now=now,
            settings=settings,
            activated_at=normalize_text(target.get("activatedAt") or target.get("activationUpdatedAt")),
            settings_saved_at=normalize_text(target.get("settingsSavedAt")),
            last_scheduled_for=normalize_text(last_run.get("scheduledFor")) if last_run else "",
        )
        if scheduled_for is None:
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "skipped",
                "reason": "not_due",
                "notificationsSent": 0,
            }

        existing_run = self.database.get_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for=scheduled_for,
        )
        if existing_run is not None:
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "skipped",
                "reason": "already_ran",
                "scheduledFor": scheduled_for.isoformat(),
                "notificationsSent": 0,
            }

        claim = self.database.claim_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for=scheduled_for,
            metadata={
                "claimedAt": self._normalize_now().isoformat(),
                "watchItems": settings.get("watchItems"),
                "intervalDays": settings.get("intervalDays"),
                "deliveryChannel": normalize_text(settings.get("deliveryChannel")),
                "settingsSavedAt": normalize_text(target.get("settingsSavedAt")),
            },
        )
        if claim is None:
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "skipped",
                "reason": "already_claimed",
                "scheduledFor": scheduled_for.isoformat(),
                "notificationsSent": 0,
            }

        try:
            return self._execute_target(
                target=target,
                settings=settings,
                scheduled_for=scheduled_for,
                persist_run=True,
            )
        except Exception as exc:
            self.database.save_feature_monitor_run(
                user_id=int(target.get("userId") or 0),
                feature_id=MONITOR_FEATURE_ID,
                scheduled_for=scheduled_for,
                findings_count=0,
                notifications_sent=0,
                status="failed",
                metadata={
                    "error": str(exc),
                    "claimedAt": claim.get("createdAt"),
                    "settingsSavedAt": normalize_text(target.get("settingsSavedAt")),
                },
            )
            raise

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": True, "ran": False, "reason": "disabled"}

        current_time = self._normalize_now(now)

        targets = self.database.list_active_feature_monitor_targets(MONITOR_FEATURE_ID)
        runs = [self._process_target(target=target, now=current_time) for target in targets]
        completed_runs = [run for run in runs if normalize_text(run.get("status")) != "skipped"]
        return {
            "ok": True,
            "ran": bool(completed_runs),
            "targets": len(targets),
            "runs": runs,
        }

    def run_for_email(
        self,
        email: str,
        *,
        now: datetime | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "ok": False,
                "error": "disabled",
                "message": "Scheduled web monitor is not enabled on the backend right now.",
            }

        normalized_email = normalize_email(email)
        if not normalized_email:
            return {
                "ok": False,
                "error": "invalid_email",
                "message": "A valid email is required.",
            }

        feature = self.database.get_assigned_feature(normalized_email, MONITOR_FEATURE_ID)
        if feature is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        activation = self.database.get_feature_activation(normalized_email, MONITOR_FEATURE_ID) or {}
        if not bool(activation.get("isActive")):
            return {
                "ok": False,
                "error": "activation_required",
                "message": "Activate the tool before running it manually.",
            }

        target = self._build_target_for_email(normalized_email)
        if target is None:
            return {
                "ok": False,
                "error": "feature_not_available",
                "message": "This tool is not available for this account.",
            }

        settings = normalize_monitor_settings(target.get("settings"))
        setup_status = build_monitor_setup_status(
            settings,
            user_email=normalized_email,
            whatsapp_connection=target.get("whatsappConnection"),
        )
        if not setup_status["ready"]:
            return {
                "ok": False,
                "error": "setup_required",
                "message": setup_status["message"],
                "setupStatus": setup_status,
            }

        run = self._execute_target(
            target=target,
            settings=settings,
            scheduled_for=self._normalize_now(now),
            persist_run=False,
            cancel_check=cancel_check,
        )
        return {
            "ok": True,
            "run": run,
        }

    def serve_forever(self, stop_event: Any, *, log: Any | None = None) -> None:
        logger = log or (lambda message: None)
        while not getattr(stop_event, "is_set", lambda: False)():
            try:
                summary = self.run_pending()
                if summary.get("ran"):
                    sent = sum(int(run.get("notificationsSent") or 0) for run in summary.get("runs", []))
                    logger(f"[scheduled-monitor] targets={summary.get('targets')} sent={sent}")
            except Exception as exc:  # noqa: BLE001 - keep background loop alive
                logger(f"[scheduled-monitor] error: {exc}")
            if getattr(stop_event, "wait", None) is None:
                break
            stop_event.wait(self.config.poll_seconds)


__all__ = [
    "DEFAULT_MONITOR_SETTINGS",
    "MONITOR_FEATURE_ID",
    "MONITOR_FEATURE_NAME",
    "ScheduledMonitorConfig",
    "ScheduledMonitorScheduler",
    "build_monitor_setup_status",
    "load_scheduled_monitor_config",
    "normalize_monitor_settings",
    "resolve_next_monitor_slot",
    "validate_monitor_settings",
]
