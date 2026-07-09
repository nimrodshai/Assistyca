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
    "exampleReplies": 'Good: "Yes, I can help. What is the address?"\nBad: "Sure, anything is possible."',
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
            "defaultAssigned": True,
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
            },
        }
    ]
