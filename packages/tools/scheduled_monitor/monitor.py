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


MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier"
MONITOR_FEATURE_NAME = "Scheduled Web Monitor"
DEFAULT_MONITOR_MODEL = "gpt-5.5"
DEFAULT_MONITOR_POLL_SECONDS = 300
DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_MONITOR_MAX_OUTPUT_TOKENS = 1800
DEFAULT_MONITOR_MAX_ITEMS = 5

DEFAULT_MONITOR_SETTINGS = {
    "watchItems": [],
    "intervalDays": 7,
    "deliveryChannel": "email",
    "telegramChatId": "",
}

SUPPORTED_DELIVERY_CHANNELS = frozenset({"email", "telegram", "whatsapp"})


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
    whatsapp_connection: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    normalized = normalize_monitor_settings(settings)
    issues: list[dict[str, str]] = []
    if not normalized["watchItems"]:
        issues.append({"field": "watchItems", "message": "Add at least one thing this monitor should check."})

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
    whatsapp_connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_monitor_settings(settings)
    issues = validate_monitor_settings(normalized, user_email=user_email, whatsapp_connection=whatsapp_connection)
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
    last_scheduled_for: str,
) -> datetime | None:
    current_time = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    interval_days = normalize_interval_days(settings.get("intervalDays"))
    interval = timedelta(days=interval_days)

    if normalize_text(last_scheduled_for):
        latest_slot = parse_datetime(last_scheduled_for).astimezone(timezone.utc)
        next_slot = latest_slot + interval
        if next_slot > current_time:
            return None
        elapsed_cycles = (current_time - next_slot) // interval
        return next_slot + (elapsed_cycles * interval)

    activation_time = parse_datetime(activated_at).astimezone(timezone.utc) if normalize_text(activated_at) else current_time
    first_slot = activation_time + interval
    if first_slot > current_time:
        return None
    elapsed_cycles = (current_time - first_slot) // interval
    return first_slot + (elapsed_cycles * interval)


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
    name = normalize_text(target.get("displayName")) or normalize_text(target.get("email")) or "your workspace"
    count_label = "1 new alert" if item_count == 1 else f"{item_count} new alerts"
    return f"{MONITOR_FEATURE_NAME}: {count_label} for {name}"


def build_notification_text(
    *,
    target: dict[str, Any],
    summary: str,
    items: list[dict[str, Any]],
    scheduled_for: datetime,
) -> str:
    lines = [
        MONITOR_FEATURE_NAME,
        "",
        f"Run: {scheduled_for.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Summary: {summary or 'New matches were found.'}",
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

    def _run_search(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        scheduled_for: datetime,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        last_run = self.database.get_latest_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
        )
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
            model=self.config.model,
            max_output_tokens=self.config.max_output_tokens,
            usage_recorder=self.database,
            price_resolver=self.database.get_model_price,
            config=load_openai_config(strict_tracking=False),
            metadata={
                "featureId": MONITOR_FEATURE_ID,
                "deliveryChannel": settings.get("deliveryChannel"),
                "intervalDays": settings.get("intervalDays"),
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

    def _deliver_items(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        items: list[dict[str, Any]],
        summary: str,
        scheduled_for: datetime,
    ) -> tuple[int, str, str]:
        if not items:
            return 0, "", ""

        message_text = build_notification_text(
            target=target,
            summary=summary,
            items=items,
            scheduled_for=scheduled_for,
        )
        channel = normalize_text(settings.get("deliveryChannel")).lower()
        delivery_target = ""
        delivery_message_id = ""
        if channel == "email":
            delivery_target = normalize_email(target.get("email"))
            subject = build_notification_subject(target, len(items))
            send_email_notification(
                to_email=delivery_target,
                subject=subject,
                text_body=message_text,
                html_body=build_notification_html(subject, message_text),
            )
        elif channel == "telegram":
            delivery_target = normalize_text(settings.get("telegramChatId"))
            response = send_telegram_notification(chat_id=delivery_target, text=message_text)
            result = response.get("result") if isinstance(response.get("result"), dict) else {}
            delivery_message_id = normalize_text(result.get("message_id"))
        elif channel == "whatsapp":
            delivery_target = normalize_text(target.get("ownerWaId"))
            delivery_message_id = send_whatsapp_notification(
                phone_number_id=normalize_text(target.get("phoneNumberId")),
                recipient_wa_id=delivery_target,
                message_text=message_text,
            )
        else:
            raise RuntimeError(f"Unsupported delivery channel: {channel}")

        return len(items), delivery_target, delivery_message_id

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

        summary, items, search_metadata = self._run_search(
            target=target,
            settings=settings,
            scheduled_for=scheduled_for,
        )
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
        if new_items:
            notifications_sent, delivery_target, delivery_message_id = self._deliver_items(
                target=target,
                settings=settings,
                items=new_items,
                summary=summary,
                scheduled_for=scheduled_for,
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

        status = "completed"
        if not items:
            status = "no_matches"
        elif items and not new_items:
            status = "duplicate_matches"

        run_record = self.database.save_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
            scheduled_for=scheduled_for,
            findings_count=len(items),
            notifications_sent=notifications_sent,
            status=status,
            metadata={
                "summary": summary,
                "items": items,
                "newItemIds": [normalize_text(item.get("id")) for item in new_items],
                "watchItems": settings.get("watchItems"),
                "intervalDays": settings.get("intervalDays"),
                "deliveryChannel": normalize_text(settings.get("deliveryChannel")),
                "deliveryTarget": delivery_target,
                **search_metadata,
            },
        )
        return {
            "userId": int(target.get("userId") or 0),
            "email": normalize_email(target.get("email")),
            "status": status,
            "scheduledFor": scheduled_for.isoformat(),
            "findingsCount": len(items),
            "notificationsSent": notifications_sent,
            "run": run_record,
        }

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": True, "ran": False, "reason": "disabled"}

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)

        targets = self.database.list_active_feature_monitor_targets(MONITOR_FEATURE_ID)
        runs = [self._process_target(target=target, now=current_time) for target in targets]
        completed_runs = [run for run in runs if normalize_text(run.get("status")) != "skipped"]
        return {
            "ok": True,
            "ran": bool(completed_runs),
            "targets": len(targets),
            "runs": runs,
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
    "validate_monitor_settings",
]
