"""Notification delivery for portal-owned automations.

What an action produces is delivered to the owner's in-app notification feed.
It is durable: rows live in the `notifications` table, so a notification
survives a tab close, a redeploy, and shows up on every device the owner signs
in on.

This module used to fan out over email (SMTP/Resend), Telegram, and WhatsApp.
The email and Telegram channels are gone. WhatsApp came back for exactly one
path: a scheduled message the owner asked to receive on WhatsApp -- the
conversational agent flow (docs/whatsapp-agent-chat.md) made "text me at
12:40" a promise this module has to keep on WhatsApp, with the in-app feed as
the fallback when sending is not configured. Two things sometimes confused
with this fan-out are *not* affected:

* Sign-in codes still go out by email -- that lives in `portal_auth.server`
  (`send_otp_email`) and has its own mail configuration.
* Customer-facing WhatsApp replies still go out over WhatsApp -- that is
  `packages.tools.whatsapp_reply_approval.server.send_whatsapp_message`, called
  from `whatsapp_portal_service`.

The two `resolve_whatsapp_sender_*` helpers remain here because both WhatsApp
send paths resolve the Assistyca-owned sender number through them.
"""

from __future__ import annotations

import os
import re
from typing import Any
from typing import Sequence


DEFAULT_PRODUCT_NAME = "Assistyca"
DEFAULT_WHATSAPP_API_VERSION = "v20.0"
DEFAULT_ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID = "1186653017865246"

# Tones the notification centre knows how to render.
NOTIFICATION_TONES = frozenset({"info", "success", "warning", "error"})


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def flatten_template_parameter(value: Any) -> str:
    """One line: a template variable may carry no newline and no tab."""

    return re.sub(r"\s+", " ", normalize_text(value)).strip()


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


def send_whatsapp_notification(
    *,
    phone_number_id: str = "",
    recipient_wa_id: str,
    message_text: str,
    access_token: str | None = None,
    api_version: str | None = None,
    template_name: str | None = None,
    template_language: str | None = None,
    template_parameters: Sequence[Any] | None = None,
    template_header_image_url: str | None = None,
) -> str:
    """Send one owner notification over WhatsApp through the Assistyca sender.

    With a template name this sends the approved template, which works outside
    Meta's 24-hour service window -- the normal case for a message scheduled
    hours ahead, and the only way to speak first to someone who registered on
    the website. The message fills the template's single body variable unless
    the caller passes `template_parameters`, which fill {{1}}, {{2}} and so on
    in order; a template that opens with a picture takes the picture per
    message, so `template_header_image_url` has to be an address Meta can
    fetch. Without a template name it sends plain text. Raises rather than
    pretending, so the caller can fall back to the in-app feed and say which
    channel actually carried the message.
    """

    # Imported here rather than at module top: this module is imported by
    # nearly everything, and the send client lives beside the approval tool.
    from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message

    resolved_phone_number_id = normalize_text(phone_number_id) or resolve_whatsapp_sender_phone_number_id()
    resolved_recipient = normalize_text(recipient_wa_id)
    resolved_access_token = normalize_text(access_token) or resolve_whatsapp_sender_access_token()
    resolved_api_version = (
        normalize_text(api_version)
        or normalize_text(os.getenv("WHATSAPP_API_VERSION"))
        or DEFAULT_WHATSAPP_API_VERSION
    )

    if not resolved_access_token:
        raise RuntimeError(
            "WhatsApp delivery is not configured. Set ASSISTYCA_WHATSAPP_ACCESS_TOKEN or WHATSAPP_ACCESS_TOKEN."
        )
    if not resolved_phone_number_id:
        raise RuntimeError("WhatsApp delivery requires a phone number id.")
    if not resolved_recipient:
        raise RuntimeError("WhatsApp delivery requires a recipient WhatsApp id.")

    resolved_template_name = normalize_text(template_name)
    resolved_template_language = normalize_text(template_language)
    template = None
    if resolved_template_name:
        if not resolved_template_language:
            raise RuntimeError("WhatsApp template delivery requires a language code.")
        raw_parameters = list(template_parameters) if template_parameters is not None else [message_text]
        # A variable carrying a newline, a tab or nothing at all is rejected by
        # Meta, and the message never reaches the phone. The empty one was put
        # to Meta on 2026-09-24 and came back "(#131008) Required parameter is
        # missing", with the header image and without it: an empty variable is
        # a missing variable, so a line cannot be dropped from an approved
        # template by sending "" in its place.
        body_parameters = [flatten_template_parameter(value) for value in raw_parameters]
        if not body_parameters or not all(body_parameters):
            raise RuntimeError("WhatsApp template delivery requires every body variable to have text.")
        components: list[dict[str, Any]] = []
        header_image_url = normalize_text(template_header_image_url)
        if header_image_url:
            components.append({
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": header_image_url}}],
            })
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": value} for value in body_parameters],
        })
        template = {
            "name": resolved_template_name,
            "language": {"code": resolved_template_language},
            "components": components,
        }

    return send_whatsapp_message(
        access_token=resolved_access_token,
        phone_number_id=resolved_phone_number_id,
        api_version=resolved_api_version,
        recipient_wa_id=resolved_recipient,
        message_text=None if template is not None else message_text,
        template=template,
    )


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
    "send_whatsapp_notification",
    "resolve_whatsapp_sender_access_token",
    "resolve_whatsapp_sender_phone_number_id",
]
