"""Notification delivery for portal-owned automations.

Everything an action produces is delivered to the owner's in-app notification
feed. There is exactly one channel, and it is durable: rows live in the
`notifications` table, so a notification survives a tab close, a redeploy, and
shows up on every device the owner signs in on.

This module used to fan out over email (SMTP/Resend), Telegram, and WhatsApp.
Those channels are gone. Two things they are sometimes confused with are *not*
affected:

* Sign-in codes still go out by email -- that lives in `portal_auth.server`
  (`send_otp_email`) and has its own mail configuration.
* Customer-facing WhatsApp replies still go out over WhatsApp -- that is
  `packages.tools.whatsapp_reply_approval.server.send_whatsapp_message`, called
  from `whatsapp_portal_service`. Only *owner notifications* moved in-app.

The two `resolve_whatsapp_sender_*` helpers remain here because the customer-send
path resolves the Assistyca-owned sender number through them.
"""

from __future__ import annotations

import os
from typing import Any


DEFAULT_PRODUCT_NAME = "Assistyca"
DEFAULT_WHATSAPP_API_VERSION = "v20.0"
DEFAULT_ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID = "1186653017865246"

# Tones the notification centre knows how to render.
NOTIFICATION_TONES = frozenset({"info", "success", "warning", "error"})


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_email(value: Any) -> str:
    return normalize_text(value).lower()


def parse_bool(value: Any, default: bool = False) -> bool:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_tone(value: Any) -> str:
    tone = normalize_text(value).lower()
    return tone if tone in NOTIFICATION_TONES else "info"


def resolve_whatsapp_sender_access_token(fallback: str = "") -> str:
    """Access token for the Assistyca-owned sender number (customer replies)."""

    return (
        normalize_text(os.getenv("ASSISTYCA_WHATSAPP_ACCESS_TOKEN"))
        or normalize_text(os.getenv("WHATSAPP_SENDER_ACCESS_TOKEN"))
        or normalize_text(os.getenv("WHATSAPP_ACCESS_TOKEN"))
        or normalize_text(fallback)
    )


def resolve_whatsapp_sender_phone_number_id() -> str:
    """Phone number id for the Assistyca-owned sender number (customer replies)."""

    return (
        normalize_text(os.getenv("ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID"))
        or normalize_text(os.getenv("WHATSAPP_SENDER_PHONE_NUMBER_ID"))
        or DEFAULT_ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID
    )


def portal_delivery_available() -> bool:
    """In-app delivery has no external dependency, so it is always available."""

    return True


def deliver_portal_notification(
    database: Any,
    *,
    user_id: int,
    title: str,
    body: str = "",
    kind: str = "info",
    tone: str = "info",
    source: str = "",
    feature_id: str = "",
    action_id: str = "",
    result_url: str = "",
    dedupe_key: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a notification to the owner's in-app feed.

    Raises on failure so callers record a failed run rather than reporting a
    delivery that never happened -- the same reason `send_whatsapp_message` no
    longer fabricates a provider message id.
    """

    if database is None:
        raise RuntimeError("A database handle is required to deliver a notification.")

    resolved_user_id = int(user_id or 0)
    if resolved_user_id <= 0:
        raise RuntimeError("A user id is required to deliver a notification.")

    normalized_title = normalize_text(title)
    if not normalized_title:
        raise RuntimeError("A notification title is required.")

    notification = database.save_notification(
        user_id=resolved_user_id,
        title=normalized_title,
        body=body or "",
        kind=normalize_text(kind) or "info",
        tone=normalize_tone(tone),
        source=normalize_text(source),
        feature_id=normalize_text(feature_id),
        action_id=normalize_text(action_id),
        result_url=normalize_text(result_url),
        dedupe_key=normalize_text(dedupe_key),
        metadata=metadata or {},
    )
    if not notification:
        raise RuntimeError("The notification could not be saved.")
    return notification


def resolve_notification_user_id(database: Any, *, user_id: int = 0, email: str = "") -> int:
    """Resolve a user id from an explicit id or an email address."""

    resolved = int(user_id or 0)
    if resolved > 0:
        return resolved

    normalized_email = normalize_email(email)
    if not normalized_email or database is None:
        return 0

    user = database.get_user(normalized_email) or {}
    return int(user.get("id") or 0)


__all__ = [
    "DEFAULT_PRODUCT_NAME",
    "DEFAULT_ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID",
    "DEFAULT_WHATSAPP_API_VERSION",
    "NOTIFICATION_TONES",
    "deliver_portal_notification",
    "normalize_email",
    "normalize_text",
    "normalize_tone",
    "parse_bool",
    "parse_int",
    "portal_delivery_available",
    "resolve_notification_user_id",
    "resolve_whatsapp_sender_access_token",
    "resolve_whatsapp_sender_phone_number_id",
]
