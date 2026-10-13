"""Talking to WhatsApp: what Meta delivers to the webhook, and what we send back.

The webhook side reads one delivery into plain events (a message someone sent,
a status Meta reports about a message we sent) and checks Meta's signature on
the body. The sending side posts one message - text, a picture, a template, or
buttons - to one person or one group, and shows "typing..." while a reply is
being written.

Nothing here knows about accounts or conversations; it is the wire format and
the HTTP calls, shared by the chat, the scheduled messages and the group chat.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def get_nested(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current



def normalize_whatsapp_id(value: Any) -> str:
    return re.sub(r"\D", "", normalize_text(value))



def verify_whatsapp_signature(secret: str, body: bytes, header: str | None) -> bool:
    # Fails closed. Without a configured app secret there is no way to tell a
    # genuine Meta delivery from an anonymous POST, and accepting one lets an
    # attacker inject inbound messages into any workspace.
    if not secret:
        return False
    if not header:
        return False
    try:
        prefix, provided = header.split("=", 1)
    except ValueError:
        return False
    if prefix.lower() != "sha256":
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, provided.strip())


def format_whatsapp_send_error(status_code: int, raw_body: str) -> str:
    payload: dict[str, Any] | None = None
    try:
        loaded = json.loads(raw_body) if raw_body else {}
        payload = loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        payload = None

    error_payload = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    error_message = normalize_text(error_payload.get("message"))
    error_code = normalize_text(error_payload.get("code"))

    if error_code == "131058" or "hello world templates" in error_message.lower():
        return (
            "WhatsApp rejected the sample template because the built-in hello_world template only works "
            "with Meta Public Test Numbers. Set WHATSAPP_SAMPLE_TEMPLATE_NAME to your own approved template."
        )

    if error_code == "131047" or "re-engagement message" in error_message.lower():
        return (
            "WhatsApp rejected the message because the 24-hour reply window is closed. "
            "Use an approved template or wait for the customer to reply again."
        )

    if error_message:
        return f"WhatsApp rejected the message: {error_message}"

    if raw_body.strip():
        return f"WhatsApp send failed with status {status_code}."

    return "WhatsApp send failed."


def send_whatsapp_message(
    *,
    access_token: str,
    phone_number_id: str,
    api_version: str,
    recipient_wa_id: str,
    message_text: str | None = None,
    interactive: dict[str, Any] | None = None,
    template: dict[str, Any] | None = None,
    to_group: bool = False,
    image: dict[str, Any] | None = None,
) -> str:
    """Send one message. With to_group, recipient_wa_id is a group id.

    Groups take text, media and templates but not interactive messages: Meta
    does not deliver buttons to a group, so a caller that offers them has to
    write the choice out in words there. An image is {"link": url} or
    {"id": media_id}, with message_text as its caption.
    """

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "group" if to_group else "individual",
        "to": recipient_wa_id,
    }
    if to_group and interactive is not None:
        raise RuntimeError("WhatsApp does not deliver buttons to a group.")
    if template is not None:
        payload["type"] = "template"
        payload["template"] = template
    elif image is not None:
        payload["type"] = "image"
        payload["image"] = {**image, **({"caption": message_text} if message_text else {})}
    elif interactive is not None:
        payload["type"] = "interactive"
        payload["interactive"] = interactive
    else:
        payload["type"] = "text"
        payload["text"] = {"preview_url": False, "body": message_text or ""}
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(format_whatsapp_send_error(exc.code, error_body)) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"WhatsApp send failed: {exc.reason}") from exc

    # Graph can return HTTP 200 with an error body. Treat anything that is not a
    # real provider message id as a failure: fabricating an id here made callers
    # record the send as successful, and the synthetic id never matched a delivery
    # status webhook, so the record was never corrected.
    if isinstance(response_payload, dict) and isinstance(response_payload.get("error"), dict):
        raise RuntimeError(format_whatsapp_send_error(200, json.dumps(response_payload)))

    messages = response_payload.get("messages", []) if isinstance(response_payload, dict) else []
    if messages and isinstance(messages, list):
        first_message = messages[0] or {}
        message_id = normalize_text(first_message.get("id"))
        if message_id:
            return message_id

    raise RuntimeError(
        "WhatsApp send failed: the provider accepted the request but returned no message id."
    )


def send_whatsapp_typing_indicator(
    *,
    access_token: str,
    phone_number_id: str,
    api_version: str,
    message_id: str,
    timeout: float = 10,
) -> None:
    """Show "typing..." to the sender of one inbound message.

    Meta shows the indicator for 25 seconds or until the next message we send,
    whichever comes first, and marks the inbound message read at the same
    time. It needs the inbound message's own id: the indicator is a status on
    that message, not a message of its own, so nothing comes back to record.
    """

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(format_whatsapp_send_error(exc.code, error_body)) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"WhatsApp typing indicator failed: {exc.reason}") from exc
    if isinstance(response_payload, dict) and isinstance(response_payload.get("error"), dict):
        raise RuntimeError(format_whatsapp_send_error(200, json.dumps(response_payload)))



def parse_form_encoded(body: bytes) -> dict[str, Any]:
    parsed = urllib_parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def parse_json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    loaded = json.loads(body.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def extract_message_media(message: dict[str, Any]) -> dict[str, str]:
    """The picture or recording a message carries, as the id Meta will serve
    it under.

    Images and audio: a photo makes a point, a voice note is the message
    spoken instead of typed. The bytes are fetched later, by whoever needs
    them, never here.
    """
    kind = normalize_text(message.get("type"))
    if kind not in {"image", "audio"}:
        return {}
    media = message.get(kind) if isinstance(message.get(kind), dict) else {}
    media_id = normalize_text(media.get("id"))
    if not media_id:
        return {}
    return {
        "kind": kind,
        "id": media_id,
        "mimeType": normalize_text(media.get("mime_type")),
        "sha256": normalize_text(media.get("sha256")),
        "caption": normalize_text(media.get("caption")),
        # Meta marks a recording made in the chat, as opposed to an audio
        # file someone forwarded. Both are transcribed the same way.
        "voice": "true" if bool(media.get("voice")) else "",
    }


def extract_inbound_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if "entry" in payload and isinstance(payload.get("entry"), list):
        for entry in payload.get("entry", []):
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []) or []:
                if not isinstance(change, dict):
                    continue
                field_name = normalize_text(change.get("field")) or "messages"
                if field_name != "messages":
                    # Coexistence traffic (smb_message_echoes, history,
                    # smb_app_state_sync) is handled by
                    # extract_coexistence_events, never as customer inbound.
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                contacts = value.get("contacts", [])
                messages = value.get("messages", [])
                metadata = value.get("metadata", {})
                # In a one-to-one chat the single contact is the sender. A group
                # change carries one message per person who spoke, so the sender
                # is read off each message and the contacts are only a way to put
                # a name to it; taking the first contact for every message would
                # file the whole group under whoever spoke first.
                names_by_wa_id: dict[str, str] = {}
                first_contact_wa_id = ""
                if isinstance(contacts, list):
                    for raw_contact in contacts:
                        contact = raw_contact if isinstance(raw_contact, dict) else {}
                        contact_wa_id = normalize_text(contact.get("wa_id"))
                        if not contact_wa_id:
                            continue
                        profile = contact.get("profile", {}) if isinstance(contact.get("profile", {}), dict) else {}
                        first_contact_wa_id = first_contact_wa_id or contact_wa_id
                        names_by_wa_id[contact_wa_id] = normalize_text(profile.get("name"))
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        message_type = normalize_text(message.get("type")) or "text"
                        if message_type not in {"text", "image", "audio", "video", "document", "interactive", "button", "location"}:
                            continue
                        message_text = extract_message_text(message)
                        reply_to_message_id = extract_message_context_id(message)
                        interactive_reply = extract_interactive_reply(message)
                        sender_wa_id = normalize_text(message.get("from")) or first_contact_wa_id
                        sender_name = names_by_wa_id.get(sender_wa_id) or sender_wa_id
                        # A group is one conversation between several people, so
                        # the thread is the group rather than whoever just spoke.
                        group_id = normalize_text(message.get("group_id"))
                        events.append(
                            {
                                "thread_id": group_id or sender_wa_id,
                                "group_id": group_id,
                                "sender_name": sender_name,
                                "sender_wa_id": sender_wa_id,
                                "message_text": message_text,
                                "message_type": message_type,
                                "source_message_id": normalize_text(message.get("id")),
                                "timestamp": normalize_text(message.get("timestamp")) or now_iso(),
                                "metadata": metadata,
                                "reply_to_message_id": reply_to_message_id,
                                "interactive_reply": interactive_reply,
                                "media": extract_message_media(message),
                                "message_payload": message,
                                "raw_payload": payload,
                            }
                        )
    elif {"sender", "message"}.issubset(payload.keys()):
        sender = payload.get("sender", {}) if isinstance(payload.get("sender", {}), dict) else {}
        group_id = normalize_text(payload.get("group_id"))
        events.append(
            {
                "thread_id": group_id or normalize_text(sender.get("wa_id") or sender.get("phone") or sender.get("id") or "local-dev"),
                "group_id": group_id,
                "sender_name": normalize_text(sender.get("name")) or normalize_text(sender.get("wa_id") or sender.get("phone") or "Customer"),
                "sender_wa_id": normalize_text(sender.get("wa_id") or sender.get("phone") or sender.get("id") or "local-dev"),
                "message_text": normalize_text(payload.get("message")),
                "message_type": normalize_text(payload.get("message_type") or "text"),
                "source_message_id": normalize_text(payload.get("message_id")),
                "timestamp": normalize_text(payload.get("timestamp")) or now_iso(),
                "metadata": {},
                "reply_to_message_id": normalize_text(payload.get("reply_to_message_id")),
                "interactive_reply": {},
                "media": {},
                "message_payload": payload,
                "raw_payload": payload,
            }
        )

    return [event for event in events if event.get("thread_id") and event.get("message_text")]


COEXISTENCE_MESSAGE_TYPES = frozenset(
    {"text", "image", "audio", "video", "document", "interactive", "button", "location", "sticker"}
)



def extract_status_error_message(status_payload: dict[str, Any]) -> str:
    errors = status_payload.get("errors", [])
    if not isinstance(errors, list):
        return ""

    parts: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        code = normalize_text(item.get("code"))
        title = normalize_text(item.get("title") or item.get("message"))
        details = ""
        error_data = item.get("error_data")
        if isinstance(error_data, dict):
            details = normalize_text(error_data.get("details"))
        chunk = " ".join(part for part in [code, title, details] if part).strip()
        if chunk:
            parts.append(chunk)

    return " | ".join(parts)


def extract_status_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if "entry" not in payload or not isinstance(payload.get("entry"), list):
        return events

    for entry in payload.get("entry", []):
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata", {})
            statuses = value.get("statuses", [])
            if not isinstance(statuses, list):
                continue
            for status_payload in statuses:
                if not isinstance(status_payload, dict):
                    continue
                status_name = normalize_text(status_payload.get("status")).lower()
                message_id = normalize_text(status_payload.get("id"))
                if not status_name or not message_id:
                    continue
                events.append(
                    {
                        "message_id": message_id,
                        "status": status_name,
                        "recipient_wa_id": normalize_text(status_payload.get("recipient_id")),
                        "timestamp": normalize_text(status_payload.get("timestamp")) or now_iso(),
                        "metadata": metadata if isinstance(metadata, dict) else {},
                        "error_message": extract_status_error_message(status_payload),
                        "raw_payload": payload,
                    }
                )

    return events


def extract_message_text(message: dict[str, Any]) -> str:
    text = get_nested(message, "text", "body", default="")
    if text:
        return normalize_text(text)

    button_reply = get_nested(message, "interactive", "button_reply", default={})
    if isinstance(button_reply, dict):
        title = normalize_text(button_reply.get("title"))
        if title:
            return title

    button = message.get("button")
    if isinstance(button, dict):
        text = normalize_text(button.get("text") or button.get("title"))
        if text:
            return text

    list_reply = get_nested(message, "interactive", "list_reply", default={})
    if isinstance(list_reply, dict):
        title = normalize_text(list_reply.get("title"))
        if title:
            return title

    caption = get_nested(message, "image", "caption", default="")
    if caption:
        return normalize_text(caption)

    if message.get("type") == "location":
        location = message.get("location", {})
        if isinstance(location, dict):
            name = normalize_text(location.get("name"))
            address = normalize_text(location.get("address"))
            return " ".join(part for part in [name, address] if part)

    return f"[{normalize_text(message.get('type') or 'message')}]"


def extract_message_context_id(message: dict[str, Any]) -> str:
    context = message.get("context", {})
    if isinstance(context, dict):
        return normalize_text(context.get("id"))
    return ""


def extract_interactive_reply(message: dict[str, Any]) -> dict[str, str]:
    interactive = message.get("interactive", {})
    if isinstance(interactive, dict):
        button_reply = interactive.get("button_reply")
        if isinstance(button_reply, dict):
            return {
                "id": normalize_text(button_reply.get("id")),
                "title": normalize_text(button_reply.get("title")),
                "type": "button_reply",
            }

        list_reply = interactive.get("list_reply")
        if isinstance(list_reply, dict):
            return {
                "id": normalize_text(list_reply.get("id")),
                "title": normalize_text(list_reply.get("title")),
                "type": "list_reply",
            }

    button = message.get("button")
    if isinstance(button, dict):
        return {
            "id": normalize_text(button.get("payload") or button.get("id")),
            "title": normalize_text(button.get("text") or button.get("title")),
            "type": "button",
        }

    return {"id": "", "title": "", "type": ""}


__all__ = [
    "extract_inbound_events",
    "extract_interactive_reply",
    "extract_message_context_id",
    "extract_message_media",
    "extract_message_text",
    "extract_status_error_message",
    "extract_status_events",
    "format_whatsapp_send_error",
    "get_nested",
    "normalize_bool",
    "normalize_text",
    "normalize_whatsapp_id",
    "now_iso",
    "parse_form_encoded",
    "parse_json_body",
    "send_whatsapp_message",
    "send_whatsapp_typing_indicator",
    "verify_whatsapp_signature",
]
