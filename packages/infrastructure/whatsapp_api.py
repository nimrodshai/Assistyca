"""Shared helpers for talking to the WhatsApp Cloud API."""

from __future__ import annotations

import json
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


DEFAULT_WHATSAPP_API_VERSION = "v20.0"


class WhatsAppConnectionError(RuntimeError):
    """Raised when WhatsApp rejects or cannot complete a connection check."""

    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def extract_graph_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""

    message = normalize_text(error.get("message"))
    if message:
        return message

    error_type = normalize_text(error.get("type"))
    if error_type:
        return error_type

    return ""


def format_connection_error(status_code: int, raw_body: str) -> str:
    parsed_message = ""
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        parsed_message = extract_graph_error_message(payload)

    if status_code in {401, 403}:
        return "WhatsApp rejected the access token. Check it and try again."

    if status_code == 404:
        return "WhatsApp could not find that phone number ID. Check it and try again."

    if status_code == 400:
        return "WhatsApp could not confirm those details. Check the access token and phone number ID, then try again."

    if parsed_message:
        return parsed_message

    if raw_body.strip():
        return "WhatsApp could not confirm the connection. Try again in a moment."

    return "WhatsApp could not confirm the connection. Try again in a moment."


def test_whatsapp_connection(
    *,
    access_token: str,
    phone_number_id: str,
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, str]:
    access_token_value = normalize_text(access_token)
    phone_number_id_value = normalize_text(phone_number_id)
    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION

    if not access_token_value:
        raise ValueError("Access token is required.")

    if not phone_number_id_value:
        raise ValueError("Phone number ID is required.")

    url = f"https://graph.facebook.com/{api_version_value}/{phone_number_id_value}"
    query = urllib_parse.urlencode(
        {
            "fields": "display_phone_number,verified_name",
            "access_token": access_token_value,
        }
    )
    request = urllib_request.Request(
        f"{url}?{query}",
        method="GET",
        headers={
            "Accept": "application/json",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise WhatsAppConnectionError(format_connection_error(exc.code, raw_body), details=raw_body) from exc
    except urllib_error.URLError as exc:
        reason = normalize_text(getattr(exc, "reason", "")) or "The network request failed."
        raise WhatsAppConnectionError(
            "WhatsApp did not respond. Check the connection and try again.",
            details=reason,
        ) from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body) from exc

    if not isinstance(payload, dict):
        raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body)

    if isinstance(payload.get("error"), dict):
        details = json.dumps(payload.get("error"), ensure_ascii=True, separators=(",", ":"))
        raise WhatsAppConnectionError(
            extract_graph_error_message(payload) or "WhatsApp could not confirm the connection.",
            details=details,
        )

    response_phone_number_id = normalize_text(payload.get("id"))
    if response_phone_number_id and response_phone_number_id != phone_number_id_value:
        raise WhatsAppConnectionError(
            "WhatsApp returned a different phone number ID than the one you entered.",
            details=raw_body,
        )

    return {
        "phone_number_id": response_phone_number_id or phone_number_id_value,
        "display_phone_number": normalize_text(payload.get("display_phone_number")),
        "verified_name": normalize_text(payload.get("verified_name")),
    }
