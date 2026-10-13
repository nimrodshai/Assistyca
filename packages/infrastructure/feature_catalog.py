"""Shared feature catalog definitions for the portal and backend services."""

from __future__ import annotations

import os
from typing import Any


DEFAULT_BILLING_MULTIPLIER = 1.5
DEFAULT_BILLING_MINIMUM = 50.0
DEFAULT_LAUNCH_URL = ""

DEFAULT_PROMPT = {
    "toneGuidance": "Warm, direct, and practical. Keep replies human, short, and grounded.",
    "replyRules": "Acknowledge the request first. Ask one clarifying question only when needed. Never guess prices or availability.",
    "businessNotes": "Anything about this family the tool should know before it writes: where they live, the school, who is who.",
    "escalationGuidance": "Stop and ask when the answer needs the person's own decision, or when something looks urgent.",
    "exampleReplies": "",
    "responseStyle": "balanced",
    "scenario": "approval",
}

DEFAULT_FEATURE_PRICING = {
    "billingMultiplier": DEFAULT_BILLING_MULTIPLIER,
    "minimumMonthlyCharge": DEFAULT_BILLING_MINIMUM,
}


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


def load_default_feature_catalog() -> list[dict[str, Any]]:
    scheduled_monitor_store_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_SCHEDULED_MONITOR_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_STORE_ID"))
    )
    scheduled_monitor_variant_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_SCHEDULED_MONITOR_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_VARIANT_ID"))
    )
    scheduled_monitor_product_id = normalize_text(os.getenv("LEMON_SQUEEZY_SCHEDULED_MONITOR_PRODUCT_ID"))

    return [
        {
            "featureId": "scheduled-web-monitor-notifier",
            "name": "Scheduled Web Monitor",
            "description": "Searches the web on a daily, weekly, or monthly schedule and sends source-backed alerts about the events, dates, and opportunities you care about.",
            "channel": "Alerts",
            "mode": "Scheduled search",
            "launchUrl": DEFAULT_LAUNCH_URL,
            "sortOrder": 120,
            "isActive": True,
            "prompt": {
                **DEFAULT_PROMPT,
                "toneGuidance": "Clear, useful, and concise. Make alerts easy to scan and act on.",
                "replyRules": "Only alert when there is a real match with a credible public source. Prefer source-backed specifics over vague mentions.",
                "businessNotes": "Region, niche, timing rules, or context that helps the monitor decide what matters most.",
                "escalationGuidance": "Mark items urgent when a deadline is close, an event is approaching soon, or the result clearly needs quick human follow-up.",
                "exampleReplies": "Good: 'The Israeli Criminal Defense Conference published its 2026 agenda. Registration closes Aug 12. Source: https://example.com'\nBad: 'There might be something interesting online soon.'",
                "scenario": "monitor",
            },
            "pricing": dict(DEFAULT_FEATURE_PRICING),
            "requirements": {
                "requiresScheduledMonitorConfig": True,
            },
            "billing": {
                "required": True,
                "provider": "lemon_squeezy",
                "storeId": scheduled_monitor_store_id,
                "productId": scheduled_monitor_product_id,
                "variantId": scheduled_monitor_variant_id,
            },
            "metadata": {
                "catalogSource": "default_feature_catalog",
                "setupSurface": "editor",
                "deliveryChannels": ["email", "telegram", "whatsapp"],
            },
        }
    ]
