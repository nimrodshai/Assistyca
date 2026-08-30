"""Shared scheduled web monitoring automation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone
from hashlib import sha256
from html import escape
from typing import Any
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.notification_delivery import deliver_portal_notification
from packages.infrastructure.notification_delivery import normalize_email
from packages.infrastructure.notification_delivery import normalize_text
from packages.infrastructure.openai_api import call_openai_response
from packages.infrastructure.openai_api import load_openai_config
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import parse_datetime
from packages.infrastructure.task_complexity import TaskComplexity, model_for_complexity
from packages.infrastructure.tool_model_selection import resolve_tool_model


MONITOR_FEATURE_ID = "scheduled-web-monitor-notifier"
MONITOR_FEATURE_NAME = "Scheduled Web Monitor"
MONITOR_COMPLEXITY = TaskComplexity.IMPORTANT
DEFAULT_MONITOR_MODEL = model_for_complexity(MONITOR_COMPLEXITY)
DEFAULT_MONITOR_POLL_SECONDS = 300
DEFAULT_MONITOR_SEARCH_CONTEXT_SIZE = "high"
DEFAULT_MONITOR_MAX_OUTPUT_TOKENS = 1800
DEFAULT_MONITOR_MAX_ITEMS = 5
RECENT_SENT_RESULTS_LOOKBACK = timedelta(hours=1)

MONITOR_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "matched_watch_item": {"type": "string"},
                    "event_date": {"type": "string"},
                    "source_name": {"type": "string"},
                    "source_url": {"type": "string"},
                    "urgency": {"type": "string"},
                },
                "required": [
                    "id",
                    "title",
                    "summary",
                    "why_it_matters",
                    "matched_watch_item",
                    "event_date",
                    "source_name",
                    "source_url",
                    "urgency",
                ],
            },
        },
    },
    "required": ["summary", "items"],
}

DEFAULT_MONITOR_SETTINGS = {
    "model": DEFAULT_MONITOR_MODEL,
    "watchItems": [],
    "manualOnly": True,
    "runMode": "manual",
    "intervalDays": 7,
    "intervalMinutes": 0,
    "scheduleTimeLocal": "",
    "scheduleTimezone": "",
    "scheduleStartAt": "",
    "deliveryChannel": "portal",
    "telegramChatId": "",
    "actionLifecycleStatus": "active",
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


def normalize_interval_days(value: Any, default: int = DEFAULT_MONITOR_SETTINGS["intervalDays"]) -> int:
    candidate = safe_int(value, default)
    return max(1, min(365, candidate))


# The shortest cadence a monitor can run on. Checking a source every few
# minutes cost far more than it was worth and surfaced nothing a person could
# act on any sooner. The floor lives here rather than only in the picker, so a
# monitor saved on a shorter cadence before this moves up to it on its next
# read instead of quietly carrying on.
MIN_MONITOR_INTERVAL_MINUTES = 60


def normalize_interval_minutes(value: Any, default: int = DEFAULT_MONITOR_SETTINGS["intervalMinutes"]) -> int:
    candidate = safe_int(value, default)
    if candidate <= 0:
        return 0
    return max(MIN_MONITOR_INTERVAL_MINUTES, min(60 * 24, candidate))


def extract_interval_minutes_from_frequency(value: Any) -> int:
    text = normalize_text(value).lower()
    if not text:
        return 0
    match = re.search(r"\bevery\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\b", text)
    if not match:
        return 0
    amount = max(1, safe_int(match.group(1), 0))
    unit = match.group(2)
    if unit.startswith(("hour", "hr")):
        return normalize_interval_minutes(amount * 60)
    return normalize_interval_minutes(amount)


def extract_interval_days_from_frequency(value: Any) -> int:
    text = normalize_text(value).lower()
    if not text:
        return DEFAULT_MONITOR_SETTINGS["intervalDays"]
    match = re.search(r"\bevery\s+(\d+)\s*(days?|weeks?|months?)\b", text)
    if match:
        amount = max(1, safe_int(match.group(1), 0))
        unit = match.group(2)
        if unit.startswith("week"):
            return normalize_interval_days(amount * 7)
        if unit.startswith("month"):
            return normalize_interval_days(amount * 30)
        return normalize_interval_days(amount)
    if text in {"daily", "every day"}:
        return 1
    if text in {"weekly", "every week"}:
        return 7
    if text in {"monthly", "every month"}:
        return 30
    return DEFAULT_MONITOR_SETTINGS["intervalDays"]


def normalize_schedule_time_local(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    match = re.fullmatch(r"(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?", text)
    if not match:
        return ""

    hour = safe_int(match.group("hour"), -1)
    minute = safe_int(match.group("minute") or 0, -1)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


# The moment a monitor first runs. A cadence alone never says which day the
# first check lands on, so the portal names it and the schedule counts from
# there instead of from the moment the settings were saved.
def normalize_schedule_start_at(value: Any) -> str:
    if isinstance(value, datetime):
        moment = value
    else:
        text = normalize_text(value)
        if not text:
            return ""
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def normalize_schedule_timezone(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        return ""
    return text


def normalize_action_lifecycle_status(value: Any) -> str:
    text = normalize_text(value).lower().replace("-", "_")
    if text in {"paused", "stopped", "suspended"}:
        return "paused"
    if text in {"removed", "deleted", "cancelled", "canceled"}:
        return "removed"
    return "active"


def parse_schedule_time_local(value: Any) -> tuple[int, int] | None:
    normalized = normalize_schedule_time_local(value)
    if not normalized:
        return None
    hour_text, minute_text = normalized.split(":", 1)
    return int(hour_text), int(minute_text)


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

    frequency = source.get("frequency") or source.get("cadence") or source.get("schedule")
    run_mode = normalize_text(source.get("runMode") or source.get("run_mode") or source.get("mode")).lower()
    manual_run_mode = run_mode in {"manual", "manual_only", "on_demand", "on-demand"}
    recurring_run_mode = run_mode in {"scheduled", "recurring", "auto", "automatic", "background"}
    manual_only = True
    if recurring_run_mode:
        manual_only = False
    if manual_run_mode:
        manual_only = True
    interval_minutes = normalize_interval_minutes(
        source.get("intervalMinutes")
        or source.get("interval_minutes")
        or extract_interval_minutes_from_frequency(frequency),
    )
    schedule_time_local = "" if manual_only or interval_minutes else normalize_schedule_time_local(
        source.get("scheduleTimeLocal") or source.get("scheduleTime")
    )
    schedule_timezone = "" if manual_only or interval_minutes else normalize_schedule_timezone(
        source.get("scheduleTimezone") or source.get("scheduleTimeZone")
    )

    return {
        "model": resolve_tool_model(source, default=DEFAULT_MONITOR_MODEL),
        "watchItems": normalize_watch_items(source.get("watchItems") or source.get("searchPrompt")),
        "manualOnly": manual_only,
        "runMode": "manual" if manual_only else "recurring",
        "intervalMinutes": interval_minutes,
        "intervalDays": normalize_interval_days(
            source.get("intervalDays")
            or extract_interval_days_from_frequency(frequency)
        ),
        "scheduleTimeLocal": schedule_time_local,
        "scheduleTimezone": schedule_timezone,
        "scheduleStartAt": "" if manual_only else normalize_schedule_start_at(
            source.get("scheduleStartAt") or source.get("schedule_start_at")
        ),
        "deliveryChannel": delivery_channel,
        "telegramChatId": normalize_text(source.get("telegramChatId")),
        "actionLifecycleStatus": normalize_action_lifecycle_status(
            source.get("actionLifecycleStatus") or source.get("action_lifecycle_status")
        ),
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

    # Delivery is always the in-app notification feed, which has no external
    # dependency to validate, so there is nothing left to check here.
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
    if parse_bool(settings.get("manualOnly"), default=False):
        return None

    current_time = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    interval_minutes = normalize_interval_minutes(settings.get("intervalMinutes"))
    interval_days = normalize_interval_days(settings.get("intervalDays"))
    interval = timedelta(minutes=interval_minutes) if interval_minutes else timedelta(days=interval_days)
    schedule_time_local = None if interval_minutes else parse_schedule_time_local(settings.get("scheduleTimeLocal"))
    schedule_timezone = "" if interval_minutes else normalize_schedule_timezone(settings.get("scheduleTimezone"))

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

    schedule_start_at = normalize_schedule_start_at(settings.get("scheduleStartAt") or settings.get("schedule_start_at"))
    start_at = datetime.fromisoformat(schedule_start_at) if schedule_start_at else None
    if start_at is not None and (latest_slot is None or latest_slot < start_at):
        # The chosen start is the first run; once it has passed the cadence
        # counts from it rather than from when the settings were saved.
        if start_at > current_time:
            return start_at
        base_slot = start_at

    if base_slot is None:
        return None

    if schedule_time_local is not None:
        tz = ZoneInfo(schedule_timezone) if schedule_timezone else timezone.utc
        base_local = base_slot.astimezone(tz)
        next_local_date = base_local.date() + timedelta(days=interval_days)
        next_local = datetime.combine(
            next_local_date,
            dt_time(schedule_time_local[0], schedule_time_local[1]),
            tzinfo=tz,
        )
        next_slot = next_local.astimezone(timezone.utc)
        if next_slot > current_time:
            return next_slot

        current_local = current_time.astimezone(tz)
        elapsed_days = max(0, (current_local.date() - next_local.date()).days)
        elapsed_cycles = elapsed_days // interval_days
        candidate_local = next_local + timedelta(days=elapsed_cycles * interval_days)
        if candidate_local <= current_local:
            candidate_local += interval
        return candidate_local.astimezone(timezone.utc)

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
        "matchedWatchItem": normalize_text(payload.get("matched_watch_item") or payload.get("matchedWatchItem")),
        "urgency": normalize_text(payload.get("urgency")).lower() or "medium",
    }


def build_monitor_prompt(
    *,
    target: dict[str, Any],
    settings: dict[str, Any],
    scheduled_for: datetime,
    last_successful_run_at: str,
    max_items: int,
    manual_run: bool = False,
) -> str:
    prompt = target.get("prompt") if isinstance(target.get("prompt"), dict) else {}
    watch_items = normalize_watch_items(settings.get("watchItems"))
    shared_profile_notes = build_shared_profile_notes(target.get("profile"))
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
        '      "summary": "what to know about the upcoming event or deadline",',
        '      "why_it_matters": "why the client should care",',
        '      "matched_watch_item": "the exact saved watch-list entry this result best matches",',
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
        "Do not require the web page to use the exact saved-watch wording. Break broad watch items into practical searches with synonyms, nearby cities, venues, ticketing pages, municipal pages, and local event-listing terms.",
        "For local events, search in both English and likely local-language terms. For Israel, HaSharon, or central Israel searches, include Hebrew/local terms such as השרון, מרכז, רעננה, הרצליה, כפר סבא, הוד השרון, תל אביב, יפו, ילדים, משפחות, אירועים, פעילויות, קיץ, and אוגוסט when they fit the watch item.",
        "If the watch item gives a month or date range without a year, interpret it in the current year from Today unless that would only point to the past; then use the next upcoming occurrence.",
        "For family, kids, or event searches, accept credible event listings, venue pages, municipal pages, ticketing pages, and reputable local guides as source-backed matches.",
        "Prefer concrete events, deadlines, conference announcements, holiday dates, or changes with a source URL.",
        "Prefer future or upcoming events and deadlines. Avoid past dates unless the update still creates a current decision or action for this client.",
        "Never invent a source, URL, event date, or organization.",
        "When you set matched_watch_item, copy the exact saved watch-list entry that best matches the result instead of inventing a new label.",
        "Only include matches that are genuinely useful enough to float up to the client.",
        "Use the shared client context and business context to make why_it_matters specific to the client's real goals, customers, region, timing, or workflow.",
        "Avoid generic why_it_matters lines like 'this helps planning' unless you also explain what planning decision it affects for this client.",
        f"Tone guidance: {normalize_text(prompt.get('toneGuidance')) or 'Clear, useful, and concise.'}",
        f"Prioritization rules: {normalize_text(prompt.get('replyRules')) or 'Only alert when there is a concrete, useful match.'}",
    ]
    if manual_run:
        policy_line = (
            "This is a user-requested manual run. Return the best matches for the saved watch list, ranked by relevance and usefulness, even if they were sent before. Do not filter results by whether they are new."
        )
    else:
        policy_line = (
            "Treat \"new\" as new to this monitor: include useful upcoming or currently relevant items that have not already been sent, even if the source page was published earlier."
        )
    lines.insert(lines.index("If nothing relevant is found, return an empty items array.") + 1, policy_line)
    if shared_profile_notes:
        lines.append("Shared client context:")
        lines.extend(f"- {item}" for item in shared_profile_notes)
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


def build_notification_subject(target: dict[str, Any], item_count: int, *, manual_run: bool = False) -> str:
    if manual_run:
        count_label = "1 best match" if item_count == 1 else f"best {item_count} matches"
        return f"Monitor summary: {count_label}"
    count_label = "1 new match" if item_count == 1 else f"{item_count} new matches"
    return f"Quick monitor update: {count_label}"


def build_no_results_subject(target: dict[str, Any], *, manual_run: bool = False) -> str:
    return "Monitor summary: no relevant matches" if manual_run else "Quick monitor update: nothing new yet"


def parse_event_date(value: Any) -> date | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_checked_timestamp(value: datetime) -> str:
    checked_at = value.astimezone(timezone.utc)
    return f"{checked_at.strftime('%b')} {checked_at.day}, {checked_at.year} at {checked_at.strftime('%H:%M')} UTC"


def format_event_date(value: Any) -> str:
    event_date = parse_event_date(value)
    if event_date is None:
        return normalize_text(value)
    return f"{event_date.strftime('%B')} {event_date.day}, {event_date.year}"


def format_relative_event_date(value: Any, *, scheduled_for: datetime) -> str:
    event_date = parse_event_date(value)
    if event_date is None:
        return ""

    delta_days = (event_date - scheduled_for.astimezone(timezone.utc).date()).days
    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Tomorrow"
    if delta_days > 1:
        return f"In {delta_days} days"
    if delta_days == -1:
        return "Yesterday"
    return f"{abs(delta_days)} days ago"


def format_event_timing(value: Any, *, scheduled_for: datetime) -> str:
    display_date = format_event_date(value)
    relative_date = format_relative_event_date(value, scheduled_for=scheduled_for)
    if display_date and relative_date:
        return f"{display_date} ({relative_date.lower()})"
    return display_date or relative_date


def normalize_urgency(value: Any) -> str:
    urgency = normalize_text(value).lower()
    if urgency in {"high", "medium", "low"}:
        return urgency
    return "medium"


def humanize_urgency(value: Any) -> str:
    return normalize_urgency(value).capitalize()


def sort_alert_items(items: list[dict[str, Any]], *, scheduled_for: datetime) -> list[dict[str, Any]]:
    reference_date = scheduled_for.astimezone(timezone.utc).date()
    urgency_rank = {"high": 0, "medium": 1, "low": 2}

    def sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        event_date = parse_event_date(item.get("eventDate"))
        if event_date is None:
            date_group = 1
            date_rank = 999999
        else:
            delta_days = (event_date - reference_date).days
            if delta_days >= 0:
                date_group = 0
                date_rank = delta_days
            else:
                date_group = 2
                date_rank = abs(delta_days)
        return (
            urgency_rank.get(normalize_urgency(item.get("urgency")), 1),
            date_group,
            date_rank,
            normalize_text(item.get("title")).lower(),
        )

    return sorted(items, key=sort_key)


def count_time_sensitive_items(items: list[dict[str, Any]], *, scheduled_for: datetime) -> int:
    reference_date = scheduled_for.astimezone(timezone.utc).date()
    count = 0
    for item in items:
        if normalize_urgency(item.get("urgency")) == "high":
            count += 1
            continue
        event_date = parse_event_date(item.get("eventDate"))
        if event_date is None:
            continue
        delta_days = (event_date - reference_date).days
        if 0 <= delta_days <= 14:
            count += 1
    return count


def build_notification_overview(
    *,
    target: dict[str, Any],
    items: list[dict[str, Any]],
    scheduled_for: datetime,
    manual_run: bool = False,
) -> str:
    item_count = len(items)
    if item_count <= 0:
        return "Nothing new worth sending right now."

    if manual_run:
        opening = (
            "Here is the best match for your watch list."
            if item_count == 1
            else f"Here are the best {item_count} matches for your watch list."
        )
    else:
        opening = (
            "Found 1 relevant future event or deadline."
            if item_count == 1
            else f"Found {item_count} relevant future events and deadlines."
        )
    parts = [opening]
    time_sensitive_count = count_time_sensitive_items(items, scheduled_for=scheduled_for)
    if time_sensitive_count:
        if time_sensitive_count == item_count and item_count > 1:
            parts.append("All of them need attention soon.")
        elif time_sensitive_count == 1:
            parts.append("1 needs attention soon.")
        else:
            parts.append(f"{time_sensitive_count} need attention soon.")

    prompt = target.get("prompt") if isinstance(target.get("prompt"), dict) else {}
    has_business_context = bool(
        build_shared_profile_notes(target.get("profile"))
        or normalize_text(prompt.get("businessNotes"))
    )
    if manual_run:
        parts.append(
            "Ranked using your saved watch list and business context."
            if has_business_context
            else "Ranked using your saved watch list."
        )
    else:
        parts.append(
            "Prioritized using your saved watch list and business context."
            if has_business_context
            else "Prioritized using your saved watch list."
        )
    return " ".join(parts)


def build_notification_heading(item_count: int, *, manual_run: bool = False) -> str:
    if manual_run:
        return "1 best match for your monitor" if item_count == 1 else f"Top {item_count} matches for your monitor"
    return (
        "1 upcoming update worth tracking"
        if item_count == 1
        else f"{item_count} upcoming updates worth tracking"
    )


def build_source_text(item: dict[str, Any]) -> str:
    source_name = normalize_text(item.get("sourceName"))
    source_url = normalize_text(item.get("sourceUrl"))
    if source_name and source_url:
        return f"{source_name} - {source_url}"
    return source_name or source_url


def build_matched_watch_item_text(item: dict[str, Any]) -> str:
    return normalize_text(item.get("matchedWatchItem"))


def resolve_matched_watch_item(item: dict[str, Any], watch_items: list[str] | None = None) -> str:
    normalized_watch_items = normalize_watch_items(watch_items or [])
    raw_match = normalize_text(item.get("matchedWatchItem") or item.get("matched_watch_item"))
    if not normalized_watch_items:
        return raw_match

    for watch_item in normalized_watch_items:
        if raw_match and raw_match.casefold() == watch_item.casefold():
            return watch_item

    if raw_match:
        return raw_match
    if len(normalized_watch_items) == 1:
        return normalized_watch_items[0]
    return ""


def build_tool_editor_url(target: dict[str, Any]) -> str:
    base_url = normalize_text(os.getenv("PUBLIC_BASE_URL")).rstrip("/")
    feature_id = normalize_text(target.get("featureId")) or MONITOR_FEATURE_ID
    if not base_url or not feature_id:
        return ""

    portal_base = base_url if base_url.endswith("/portal") else f"{base_url}/portal"
    return f"{portal_base}/#features/{quote(feature_id)}/editor"


def escape_html_text(value: Any) -> str:
    return escape(str(value or ""), quote=True)


def build_results_supporting_note(summary: str, overview: str) -> str:
    note = normalize_text(summary)
    if not note:
        return ""
    if len(note) > 180:
        return ""
    if note.casefold() in overview.casefold():
        return ""
    return note


def build_email_shell(
    *,
    eyebrow: str,
    title: str,
    checked_label: str,
    overview: str,
    body_html: str,
    button_label: str = "",
    button_url: str = "",
    supporting_note: str = "",
) -> str:
    action_html = ""
    if button_label and button_url:
        action_html = (
            f'<a class="email-button" href="{escape_html_text(button_url)}">{escape_html_text(button_label)}</a>'
        )

    note_html = ""
    if supporting_note:
        note_html = f'<p class="email-note">{escape_html_text(supporting_note)}</p>'

    return (
        "<!doctype html>"
        "<html>"
        "<head>"
        "<meta charset=\"utf-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />"
        "<style>"
        "body{margin:0;padding:0;background:#eef4fa;color:#223548;font-family:Avenir Next,Segoe UI,Helvetica Neue,sans-serif;}"
        ".email-shell{width:100%;background:#eef4fa;padding:24px 12px;box-sizing:border-box;}"
        ".email-card{max-width:700px;margin:0 auto;background:#ffffff;border:1px solid #dce7f0;border-radius:24px;overflow:hidden;}"
        ".email-header{padding:32px 32px 12px;}"
        ".email-eyebrow{margin:0 0 10px;font-size:12px;line-height:1.4;letter-spacing:0.14em;text-transform:uppercase;color:#6f8296;font-weight:700;}"
        ".email-title{margin:0;font-size:34px;line-height:1.1;letter-spacing:-0.04em;color:#122230;font-weight:800;}"
        ".email-meta{margin:14px 0 0;font-size:13px;line-height:1.5;color:#6b7f92;}"
        ".email-summary{margin:16px 0 0;font-size:17px;line-height:1.7;color:#31465c;}"
        ".email-note{margin:12px 0 0;font-size:14px;line-height:1.6;color:#5a6f84;}"
        ".email-button{display:inline-block;margin-top:20px;padding:12px 18px;border-radius:999px;background:#0f5bd8;color:#ffffff !important;text-decoration:none;font-size:14px;font-weight:700;}"
        ".email-section{padding:0 32px 22px;}"
        ".alert-card{background:#f8fbff;border:1px solid #dbe7f3;border-radius:18px;padding:22px;}"
        ".alert-pill{display:inline-block;margin:0 8px 8px 0;padding:6px 10px;border-radius:999px;background:#e8eef6;color:#445a70;font-size:12px;font-weight:700;line-height:1.2;}"
        ".alert-pill.high{background:#fee7e6;color:#a53b32;}"
        ".alert-pill.medium{background:#fff1d9;color:#9b6513;}"
        ".alert-pill.low{background:#e6f4ea;color:#2d7a43;}"
        ".alert-pill.search{background:#e7f5ef;color:#166b57;max-width:100%;white-space:normal;}"
        ".alert-pill.relative{background:#e4efff;color:#1f5cb7;}"
        ".alert-title{margin:4px 0 0;font-size:24px;line-height:1.35;color:#16304a;font-weight:700;}"
        ".alert-label{margin:16px 0 0;font-size:11px;line-height:1.4;letter-spacing:0.12em;text-transform:uppercase;color:#70869a;font-weight:700;}"
        ".alert-copy{margin:6px 0 0;font-size:16px;line-height:1.7;color:#31465c;}"
        ".alert-meta{margin:16px 0 0;font-size:14px;line-height:1.6;color:#576d82;}"
        ".alert-source a{color:#0f5bd8;text-decoration:none;font-weight:700;}"
        ".email-list{margin:10px 0 0;padding-left:18px;color:#31465c;font-size:16px;line-height:1.7;}"
        ".email-list li{margin:0 0 6px;}"
        ".email-footer{padding:0 32px 32px;font-size:13px;line-height:1.6;color:#71879a;}"
        "@media only screen and (max-width:640px){"
        ".email-shell{padding:16px 10px;}"
        ".email-header{padding:24px 20px 8px;}"
        ".email-section{padding:0 20px 18px;}"
        ".email-footer{padding:0 20px 24px;}"
        ".email-title{font-size:28px;}"
        ".alert-title{font-size:21px;}"
        ".email-summary,.alert-copy,.email-list{font-size:15px;}"
        ".email-button{display:block;text-align:center;}"
        "}"
        "</style>"
        "</head>"
        "<body>"
        "<div class=\"email-shell\">"
        "<div class=\"email-card\">"
        "<div class=\"email-header\">"
        f"<p class=\"email-eyebrow\">{escape_html_text(eyebrow)}</p>"
        f"<h1 class=\"email-title\">{escape_html_text(title)}</h1>"
        f"<p class=\"email-meta\">Checked {escape_html_text(checked_label)}.</p>"
        f"<p class=\"email-summary\">{escape_html_text(overview)}</p>"
        f"{note_html}"
        f"{action_html}"
        "</div>"
        f"{body_html}"
        "<div class=\"email-footer\">"
        "You can update the watch list, timing, and delivery details any time in the tool editor."
        "</div>"
        "</div>"
        "</div>"
        "</body>"
        "</html>"
    )


def build_notification_text(
    *,
    target: dict[str, Any],
    summary: str,
    items: list[dict[str, Any]],
    scheduled_for: datetime,
    manual_run: bool = False,
) -> str:
    sorted_items = sort_alert_items(items, scheduled_for=scheduled_for)
    lines = [
        "Monitor summary" if manual_run else "Quick monitor update",
        "",
        f"Checked {format_checked_timestamp(scheduled_for)}.",
        build_notification_overview(target=target, items=sorted_items, scheduled_for=scheduled_for, manual_run=manual_run),
    ]
    for index, item in enumerate(sorted_items, start=1):
        lines.extend(
            [
                "",
                f"{index}. {item['title']}",
                f"What to know: {item['summary'] or 'Relevant future update found.'}",
            ]
        )
        if item["whyItMatters"]:
            lines.append(f"Why this matters for your business: {item['whyItMatters']}")
        event_timing = format_event_timing(item.get("eventDate"), scheduled_for=scheduled_for)
        if event_timing:
            lines.append(f"When: {event_timing}")
        source = build_source_text(item)
        if source:
            lines.append(f"Source: {source}")
        matched_watch_item = build_matched_watch_item_text(item)
        if matched_watch_item:
            lines.append(f"Search: {matched_watch_item}")
    return "\n".join(lines)


def build_no_results_text(
    *,
    settings: dict[str, Any],
    scheduled_for: datetime,
    status: str = "no_matches",
    recent_results_already_sent: bool = False,
    manual_run: bool = False,
) -> str:
    if manual_run:
        lines = [
            "Monitor summary",
            "",
            f"Checked {format_checked_timestamp(scheduled_for)}.",
            "I did not find a relevant match in this run.",
            "",
            "Here's what I checked:",
        ]
        watch_items = normalize_watch_items(settings.get("watchItems"))
        if watch_items:
            lines.extend(f"- {item}" for item in watch_items)
        else:
            brief = resolve_monitor_brief(settings)
            lines.append(f"- {brief or 'Your saved watch list'}")
        return "\n".join(lines)

    watch_items = normalize_watch_items(settings.get("watchItems"))
    follow_up_message = (
        "I already sent the latest results earlier."
        if normalize_text(status) == "no_matches" and recent_results_already_sent
        else ""
        if normalize_text(status) == "no_matches"
        else "Nothing new to send right now. I already shared the useful matches earlier."
    )
    lines = [
        "Quick monitor update",
        "",
        f"Checked {format_checked_timestamp(scheduled_for)}.",
        "Nothing new worth sending right now.",
        "",
        "Here's what I checked:",
    ]
    if watch_items:
        lines.extend(f"- {item}" for item in watch_items)
    else:
        brief = resolve_monitor_brief(settings)
        lines.append(f"- {brief or 'Your saved watch list'}")

    if follow_up_message:
        lines.extend(["", follow_up_message])
    return "\n".join(lines)


def build_notification_html(
    *,
    target: dict[str, Any],
    summary: str,
    items: list[dict[str, Any]],
    scheduled_for: datetime,
    manual_run: bool = False,
) -> str:
    sorted_items = sort_alert_items(items, scheduled_for=scheduled_for)
    sections: list[str] = []
    for item in sorted_items:
        relative_date = format_relative_event_date(item.get("eventDate"), scheduled_for=scheduled_for)
        event_timing = format_event_timing(item.get("eventDate"), scheduled_for=scheduled_for)
        matched_watch_item = build_matched_watch_item_text(item)
        source_name = normalize_text(item.get("sourceName"))
        source_url = normalize_text(item.get("sourceUrl"))
        source_html = ""
        if source_name and source_url:
            source_html = (
                f"{escape_html_text(source_name)}"
                f" <span aria-hidden=\"true\">&middot;</span> "
                f"<a href=\"{escape_html_text(source_url)}\">View source</a>"
            )
        elif source_url:
            source_html = f"<a href=\"{escape_html_text(source_url)}\">View source</a>"
        elif source_name:
            source_html = escape_html_text(source_name)

        pill_html: list[str] = []
        if matched_watch_item:
            pill_html.append(
                f"<span class=\"alert-pill search\">Search: {escape_html_text(matched_watch_item)}</span>"
            )
        if relative_date:
            pill_html.append(f"<span class=\"alert-pill relative\">{escape_html_text(relative_date)}</span>")

        section_parts = [
            "<div class=\"email-section\">",
            "<div class=\"alert-card\">",
            "".join(pill_html),
            f"<h2 class=\"alert-title\">{escape_html_text(item.get('title'))}</h2>",
            "<p class=\"alert-label\">What to know</p>",
            f"<p class=\"alert-copy\">{escape_html_text(item.get('summary') or 'Relevant future update found.')}</p>",
        ]
        if item.get("whyItMatters"):
            section_parts.extend(
                [
                    "<p class=\"alert-label\">Why this matters for your business</p>",
                    f"<p class=\"alert-copy\">{escape_html_text(item.get('whyItMatters'))}</p>",
                ]
            )
        if event_timing:
            section_parts.extend(
                [
                    "<p class=\"alert-label\">When</p>",
                    f"<p class=\"alert-copy\">{escape_html_text(event_timing)}</p>",
                ]
            )
        if source_html:
            section_parts.append(f"<p class=\"alert-meta alert-source\">Source: {source_html}</p>")
        section_parts.extend(["</div>", "</div>"])
        sections.append("".join(section_parts))

    overview = build_notification_overview(target=target, items=sorted_items, scheduled_for=scheduled_for, manual_run=manual_run)
    return build_email_shell(
        eyebrow="Scheduled Web Monitor",
        title=build_notification_heading(len(sorted_items), manual_run=manual_run),
        checked_label=format_checked_timestamp(scheduled_for),
        overview=overview,
        supporting_note=build_results_supporting_note(summary, overview),
        body_html="".join(sections),
        button_label="Open tool editor",
        button_url=build_tool_editor_url(target),
    )


def build_no_results_html(
    *,
    target: dict[str, Any],
    settings: dict[str, Any],
    scheduled_for: datetime,
    status: str = "no_matches",
    recent_results_already_sent: bool = False,
    manual_run: bool = False,
) -> str:
    watch_items = normalize_watch_items(settings.get("watchItems"))
    if not watch_items:
        watch_items = [resolve_monitor_brief(settings) or "Your saved watch list"]

    supporting_note = (
        "This was a manual run; the next click will search again and return the best available matches."
        if manual_run
        else
        "The latest useful results were already shared earlier."
        if normalize_text(status) != "no_matches" or recent_results_already_sent
        else ""
    )
    body_html = (
        "<div class=\"email-section\">"
        "<div class=\"alert-card\">"
        "<p class=\"alert-label\">Checked topics</p>"
        "<ul class=\"email-list\">"
        + "".join(f"<li>{escape_html_text(item)}</li>" for item in watch_items)
        + "</ul>"
        "</div>"
        "</div>"
    )
    return build_email_shell(
        eyebrow="Scheduled Web Monitor",
        title="No relevant matches found" if manual_run else "Nothing new worth sending yet",
        checked_label=format_checked_timestamp(scheduled_for),
        overview=(
            "I checked your saved watch list and did not find a relevant source-backed match in this run."
            if manual_run
            else "I checked your saved watch list and did not find a new source-backed update worth sending right now."
        ),
        supporting_note=supporting_note,
        body_html=body_html,
        button_label="Open tool editor",
        button_url=build_tool_editor_url(target),
    )


def build_fallback_notification_html(subject: str, text_body: str) -> str:
    body_html = "".join(
        f"<div class=\"email-section\"><div class=\"alert-card\"><p class=\"alert-copy\">{escape_html_text(line)}</p></div></div>"
        for line in text_body.splitlines()
        if line.strip()
    )
    return build_email_shell(
        eyebrow="Scheduled Web Monitor",
        title=subject,
        checked_label="just now",
        overview="Here is the latest monitor message.",
        body_html=body_html,
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
            "profile": user.get("profile") if isinstance(user.get("profile"), dict) else {},
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
            "accessToken": normalize_text(whatsapp_connection.get("accessToken")),
            "ownerWaId": normalize_text(whatsapp_connection.get("ownerWaId")),
            "whatsappConnection": {
                "phoneNumberId": normalize_text(whatsapp_connection.get("phoneNumberId")),
                "accessToken": normalize_text(whatsapp_connection.get("accessToken")),
                "accessTokenConfigured": bool(normalize_text(whatsapp_connection.get("accessToken"))),
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
        manual_run: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        self._raise_if_cancelled(cancel_check)
        last_run = self.database.get_latest_feature_monitor_run(
            user_id=int(target.get("userId") or 0),
            feature_id=MONITOR_FEATURE_ID,
            before_scheduled_for=scheduled_for,
        )
        selected_model = resolve_tool_model(settings, default=self.config.model)
        result_limit = min(DEFAULT_MONITOR_MAX_ITEMS, self.config.max_items_per_run) if manual_run else self.config.max_items_per_run
        prompt = build_monitor_prompt(
            target=target,
            settings=settings,
            scheduled_for=scheduled_for,
            last_successful_run_at=normalize_text(last_run.get("scheduledFor")) if last_run else "",
            max_items=result_limit,
            manual_run=manual_run,
        )
        result = call_openai_response(
            tool_name=MONITOR_FEATURE_NAME,
            tool_id=MONITOR_FEATURE_ID,
            billing_email=normalize_email(target.get("email")),
            prompt=prompt,
            model=selected_model,
            max_output_tokens=self.config.max_output_tokens,
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
            reasoning={"effort": "low"},
            extra_payload={
                "tool_choice": "required",
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "scheduled_monitor_result",
                        "strict": True,
                        "schema": MONITOR_RESPONSE_SCHEMA,
                    },
                },
            },
        )
        payload = extract_json_payload(result.output_text)
        if not payload or not isinstance(payload.get("items"), list):
            raw_response = getattr(result, "raw_response", {})
            response_status = normalize_text(raw_response.get("status")) if isinstance(raw_response, dict) else ""
            incomplete_details = raw_response.get("incomplete_details") if isinstance(raw_response, dict) else None
            detail = normalize_text(incomplete_details.get("reason")) if isinstance(incomplete_details, dict) else ""
            suffix = f" ({detail})" if detail else (f" ({response_status})" if response_status else "")
            raise RuntimeError(f"Web monitor returned an invalid structured search response{suffix}.")
        raw_items = payload["items"]
        watch_items = normalize_watch_items(settings.get("watchItems"))
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized_item = normalize_alert_item(item)
            normalized_item["matchedWatchItem"] = resolve_matched_watch_item(normalized_item, watch_items)
            items.append(normalized_item)
        return (
            normalize_text(payload.get("summary")),
            items[: result_limit],
            {
                "requestId": result.request_id,
                "responseId": result.response_id,
                "model": normalize_text(result.model),
                "promptHash": sha256(prompt.encode("utf-8")).hexdigest()[:24],
                "rawItems": raw_items[: result_limit],
                "rawItemsCount": len(raw_items),
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
        # Monitor findings go to the owner's in-app notification feed. Email,
        # Telegram and WhatsApp alerting were removed in favour of a single
        # durable surface inside the portal.
        user_id = int(target.get("userId") or 0)
        if user_id <= 0:
            raise RuntimeError("Monitor target is missing a user id.")

        notification = deliver_portal_notification(
            self.database,
            user_id=user_id,
            title=subject,
            body=message_text,
            kind="monitor_finding",
            tone="info",
            source="scheduled_monitor",
            feature_id=MONITOR_FEATURE_ID,
            # Carries the "open the tool editor" link the HTML email used to have,
            # rendered by the notification centre as its action button.
            result_url=build_tool_editor_url(target),
            metadata={"deliveryChannel": "portal"},
        )
        delivery_target = normalize_email(target.get("email"))
        return delivery_target, f"portal-notification-{int(notification.get('id') or 0)}"

    def _deliver_items(
        self,
        *,
        target: dict[str, Any],
        settings: dict[str, Any],
        items: list[dict[str, Any]],
        summary: str,
        scheduled_for: datetime,
        manual_run: bool = False,
    ) -> tuple[int, str, str]:
        if not items:
            return 0, "", ""

        message_text = build_notification_text(
            target=target,
            summary=summary,
            items=items,
            scheduled_for=scheduled_for,
            manual_run=manual_run,
        )
        html_body = build_notification_html(
            target=target,
            summary=summary,
            items=items,
            scheduled_for=scheduled_for,
            manual_run=manual_run,
        )
        delivery_target, delivery_message_id = self._deliver_message(
            target={
                **target,
                "telegramChatId": settings.get("telegramChatId"),
            },
            subject=build_notification_subject(target, len(items), manual_run=manual_run),
            message_text=message_text,
            html_body=html_body,
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
        manual_run: bool = False,
    ) -> tuple[bool, str, str]:
        message_text = build_no_results_text(
            settings=settings,
            scheduled_for=scheduled_for,
            status=status,
            recent_results_already_sent=recent_results_already_sent,
            manual_run=manual_run,
        )
        html_body = build_no_results_html(
            target=target,
            settings=settings,
            scheduled_for=scheduled_for,
            status=status,
            recent_results_already_sent=recent_results_already_sent,
            manual_run=manual_run,
        )
        delivery_target, delivery_message_id = self._deliver_message(
            target={
                **target,
                "telegramChatId": settings.get("telegramChatId"),
            },
            subject=build_no_results_subject(target, manual_run=manual_run),
            message_text=message_text,
            html_body=html_body,
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
        manual_run: bool = False,
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
                manual_run=manual_run,
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
            recent_results_batch = [
                notification
                for notification in recent_notifications
                if normalize_text(notification.get("scheduledFor")) == recent_results_sent_at
            ] if recent_results_sent_at else []
            recent_results_count = len(recent_results_batch)
            recent_results_minutes_ago = 0
            if recent_results_sent_at:
                recent_results_minutes_ago = max(
                    0,
                    int(
                        (
                            scheduled_for.astimezone(timezone.utc)
                            - parse_datetime(recent_results_sent_at).astimezone(timezone.utc)
                        ).total_seconds() // 60
                    ),
                )

            new_items: list[dict[str, Any]] = []
            if manual_run:
                # A manual run is an explicit request for the current best
                # matches, not an incremental "what changed" alert.
                new_items = items
            else:
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
            if not items:
                status = "no_matches"
            elif not manual_run and items and not new_items:
                status = "duplicate_matches"

            live_search_status = status
            if (
                not manual_run
                and not persist_run
                and live_search_status == "no_matches"
                and recent_results_count > 0
            ):
                status = "inconsistent_results"

            if new_items:
                self._raise_if_cancelled(cancel_check)
                notifications_sent, delivery_target, delivery_message_id = self._deliver_items(
                    target=target,
                    settings=settings,
                    items=new_items,
                    summary=summary,
                    scheduled_for=scheduled_for,
                    manual_run=manual_run,
                )
            elif status in {"no_matches", "duplicate_matches"} and not persist_run:
                self._raise_if_cancelled(cancel_check)
                no_results_notification_sent, delivery_target, delivery_message_id = self._deliver_no_results_notification(
                    target=target,
                    settings=settings,
                    scheduled_for=scheduled_for,
                    status=status,
                    recent_results_already_sent=recent_results_already_sent if status == "no_matches" else False,
                    manual_run=manual_run,
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
                        manual_run=manual_run,
                    ),
                    metadata={
                        "summary": normalize_text(item.get("summary")),
                        "whyItMatters": normalize_text(item.get("whyItMatters")),
                        "matchedWatchItem": normalize_text(item.get("matchedWatchItem")),
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
                "intervalMinutes": settings.get("intervalMinutes"),
                "intervalDays": settings.get("intervalDays"),
                "manualOnly": parse_bool(settings.get("manualOnly"), default=False),
                "manualRun": manual_run,
                "resultPolicy": "best_matches" if manual_run else "unseen_matches",
                "deliveryChannel": normalize_text(settings.get("deliveryChannel")),
                "settingsSavedAt": normalize_text(target.get("settingsSavedAt")),
                "deliveryTarget": delivery_target,
                "noResultsNotificationSent": no_results_notification_sent,
                "noResultsDeliverySkipped": bool(
                    persist_run
                    and live_search_status in {"no_matches", "duplicate_matches"}
                ),
                "noResultsReason": live_search_status if live_search_status in {"no_matches", "duplicate_matches"} else "",
                "recentResultsAlreadySent": recent_results_already_sent if live_search_status == "no_matches" else False,
                "recentResultsSentAt": recent_results_sent_at if live_search_status == "no_matches" else "",
                "recentResultsCount": recent_results_count if live_search_status == "no_matches" else 0,
                "recentResultsMinutesAgo": recent_results_minutes_ago if live_search_status == "no_matches" else 0,
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
                "intervalMinutes": settings.get("intervalMinutes"),
                "intervalDays": settings.get("intervalDays"),
                "manualOnly": parse_bool(settings.get("manualOnly"), default=False),
                "manualRun": manual_run,
                "resultPolicy": "best_matches" if manual_run else "unseen_matches",
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
        if parse_bool(settings.get("manualOnly"), default=False):
            return {
                "userId": int(target.get("userId") or 0),
                "email": normalize_email(target.get("email")),
                "status": "skipped",
                "reason": "manual_only",
                "notificationsSent": 0,
            }
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
                "intervalMinutes": settings.get("intervalMinutes"),
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

        # Drop claims left behind by a crashed or redeployed worker. The run row is
        # the claim, so a stranded 'running' row makes the slot look already-taken
        # and the monitor silently never runs for that user again.
        try:
            self.database.release_stale_feature_monitor_runs(now=current_time)
        except Exception:  # noqa: BLE001 - recovery must never block the batch
            pass

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
            manual_run=True,
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
    "normalize_action_lifecycle_status",
    "normalize_monitor_settings",
    "normalize_schedule_start_at",
    "resolve_next_monitor_slot",
    "validate_monitor_settings",
]
