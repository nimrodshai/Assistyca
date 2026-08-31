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
    "businessNotes": "Service area, hours, pricing hints, and any details the agent should know before replying.",
    "escalationGuidance": "Hand off when the customer is upset, the answer needs a human decision, or the request is urgent.",
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
    whatsapp_store_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_STORE_ID"))
    )
    whatsapp_variant_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_VARIANT_ID"))
    )
    whatsapp_product_id = normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_REPLY_ASSISTANT_PRODUCT_ID"))
    whatsapp_follow_up_store_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_FOLLOW_UP_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_STORE_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_STORE_ID"))
    )
    whatsapp_follow_up_variant_id = (
        normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_FOLLOW_UP_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_ACTIVATION_VARIANT_ID"))
        or normalize_text(os.getenv("LEMON_SQUEEZY_VARIANT_ID"))
    )
    whatsapp_follow_up_product_id = normalize_text(os.getenv("LEMON_SQUEEZY_WHATSAPP_FOLLOW_UP_PRODUCT_ID"))
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
            "featureId": "whatsapp-business-reply-suggestion-assistant",
            "name": "WhatsApp Reply Assistant",
            "description": "Turns incoming WhatsApp questions into quick, human-reviewed replies that help you quote faster and book more work.",
            "channel": "WhatsApp",
            "mode": "Human-reviewed",
            "launchUrl": DEFAULT_LAUNCH_URL,
            "sortOrder": 100,
            "isActive": True,
            "prompt": dict(DEFAULT_PROMPT),
            "pricing": dict(DEFAULT_FEATURE_PRICING),
            "requirements": {
                "requiresWhatsAppConnection": True,
            },
            "billing": {
                "required": True,
                "provider": "lemon_squeezy",
                "storeId": whatsapp_store_id,
                "productId": whatsapp_product_id,
                "variantId": whatsapp_variant_id,
            },
            "metadata": {
                "catalogSource": "default_feature_catalog",
                "deliveryChannels": ["portal", "whatsapp", "telegram"],
            },
        },
        {
            "featureId": "whatsapp-business-follow-up-outreach-writer",
            "name": "WhatsApp Re-engagement Assistant",
            "description": "Helps you reconnect with past customers using ready-to-send WhatsApp follow-ups, so more quiet conversations turn back into active work.",
            "channel": "WhatsApp",
            "mode": "Weekly follow-up",
            "launchUrl": DEFAULT_LAUNCH_URL,
            "sortOrder": 110,
            "isActive": True,
            "prompt": {
                **DEFAULT_PROMPT,
                "replyRules": "Use the saved conversation to write a warm, low-pressure re-engagement message. Keep it concise, specific, and easy to copy into WhatsApp.",
                "businessNotes": "Reference real context from the previous conversation when it helps. Never invent discounts, availability, or promises.",
                "scenario": "reengagement",
            },
            "pricing": dict(DEFAULT_FEATURE_PRICING),
            "requirements": {
                "requiresWhatsAppConnection": True,
            },
            "billing": {
                "required": True,
                "provider": "lemon_squeezy",
                "storeId": whatsapp_follow_up_store_id,
                "productId": whatsapp_follow_up_product_id,
                "variantId": whatsapp_follow_up_variant_id,
            },
            "metadata": {
                "catalogSource": "default_feature_catalog",
                "automation": {
                    "schedule": "sunday_morning",
                    "inactivityMonths": 6,
                },
            },
        },
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
