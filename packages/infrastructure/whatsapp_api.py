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

    message = normalize_text(error.get("error_user_msg")) or normalize_text(error.get("message"))
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
        if parsed_message:
            return f"WhatsApp rejected the connection credentials: {parsed_message}"
        return "WhatsApp rejected the connection credentials. Check them and try again."

    if status_code == 404:
        if parsed_message:
            return f"WhatsApp could not find that phone number ID: {parsed_message}"
        return "WhatsApp could not find that phone number ID. Check it and try again."

    if status_code == 400:
        if parsed_message:
            return f"WhatsApp could not confirm those details: {parsed_message}"
        return "WhatsApp could not confirm those details. Check the connection credentials, then try again."

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
        raise ValueError("WhatsApp connection credentials are required.")

    if not phone_number_id_value:
        raise ValueError("WhatsApp phone number ID is required.")

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


def list_whatsapp_business_phone_numbers(
    *,
    access_token: str,
    business_account_id: str,
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> list[dict[str, str]]:
    access_token_value = normalize_text(access_token)
    business_account_id_value = normalize_text(business_account_id)
    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION

    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")

    if not business_account_id_value:
        raise ValueError("WhatsApp Business Account ID is required.")

    url = f"https://graph.facebook.com/{api_version_value}/{business_account_id_value}/phone_numbers"
    query = urllib_parse.urlencode(
        {
            "fields": "id,display_phone_number,verified_name",
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
            extract_graph_error_message(payload) or "WhatsApp could not list phone numbers for that Business Account.",
            details=details,
        )

    items = payload.get("data")
    if not isinstance(items, list):
        raise WhatsAppConnectionError("WhatsApp returned an unexpected phone number list.", details=raw_body)

    phone_numbers: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        phone_number_id = normalize_text(item.get("id"))
        if not phone_number_id:
            continue
        phone_numbers.append(
            {
                "id": phone_number_id,
                "display_phone_number": normalize_text(item.get("display_phone_number")),
                "verified_name": normalize_text(item.get("verified_name")),
            }
        )
    return phone_numbers


def subscribe_whatsapp_business_account(
    *,
    access_token: str,
    business_account_id: str,
    callback_url: str = "",
    verify_token: str = "",
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    access_token_value = normalize_text(access_token)
    business_account_id_value = normalize_text(business_account_id)
    callback_url_value = normalize_text(callback_url).rstrip("/")
    verify_token_value = normalize_text(verify_token)
    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION

    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")

    if not business_account_id_value:
        raise ValueError("WhatsApp Business Account ID is required.")

    if callback_url_value and not verify_token_value:
        raise ValueError("WhatsApp webhook verify token is required to override the callback URL.")

    def post_subscription_request(body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        url = f"https://graph.facebook.com/{api_version_value}/{business_account_id_value}/subscribed_apps"
        request = urllib_request.Request(
            url,
            data=body,
            method="POST",
            headers=headers,
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
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError as exc:
            raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body) from exc

        if not isinstance(payload, dict):
            raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body)

        if isinstance(payload.get("error"), dict):
            details = json.dumps(payload.get("error"), ensure_ascii=True, separators=(",", ":"))
            raise WhatsAppConnectionError(
                extract_graph_error_message(payload) or "WhatsApp could not subscribe the webhook.",
                details=details,
            )

        if payload and payload.get("success") is False:
            raise WhatsAppConnectionError("WhatsApp did not confirm the webhook subscription.", details=raw_body)

        return payload

    base_body = urllib_parse.urlencode({"access_token": access_token_value}).encode("utf-8")
    base_headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if not callback_url_value:
        return post_subscription_request(base_body, base_headers)

    base_payload = post_subscription_request(base_body, base_headers)

    override_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token_value}",
        "Content-Type": "application/json",
    }
    override_body = json.dumps(
        {
            "override_callback_uri": callback_url_value,
            "verify_token": verify_token_value,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    override_payload = post_subscription_request(override_body, override_headers)
    if isinstance(override_payload, dict):
        return {
            **override_payload,
            "baselineSubscription": base_payload,
        }
    return override_payload


def _graph_request(
    *,
    url: str,
    method: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: float,
    failure_message: str,
) -> dict[str, Any]:
    """One Graph call, with the error handling every caller here needs.

    Meta reports failures three different ways -- an HTTP error status, a 200
    carrying an "error" object, and a 200 carrying nothing useful -- so all
    three are turned into WhatsAppConnectionError with the raw body attached
    for the portal to surface.
    """

    request = urllib_request.Request(url, data=body, method=method, headers=headers)

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
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as exc:
        raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body) from exc

    if not isinstance(payload, dict):
        raise WhatsAppConnectionError("WhatsApp returned an unexpected response.", details=raw_body)

    if isinstance(payload.get("error"), dict):
        details = json.dumps(payload.get("error"), ensure_ascii=True, separators=(",", ":"))
        raise WhatsAppConnectionError(
            extract_graph_error_message(payload) or failure_message,
            details=details,
        )

    return payload


def exchange_embedded_signup_code(
    *,
    code: str,
    app_id: str,
    app_secret: str,
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Trade the Embedded Signup popup's one-time code for a business token.

    The token that comes back belongs to the customer's WhatsApp Business
    Account, not to Assistyca, and the customer can revoke it from their own
    Meta settings at any time. It is the only credential the portal needs from
    them, and it never passes through their hands.
    """

    code_value = normalize_text(code)
    app_id_value = normalize_text(app_id)
    app_secret_value = normalize_text(app_secret)
    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION

    if not code_value:
        raise ValueError("The WhatsApp signup code is required.")
    if not app_id_value or not app_secret_value:
        raise ValueError("Meta app credentials are not configured on this server.")

    query = urllib_parse.urlencode({
        "client_id": app_id_value,
        "client_secret": app_secret_value,
        "code": code_value,
    })
    payload = _graph_request(
        url=f"https://graph.facebook.com/{api_version_value}/oauth/access_token?{query}",
        method="GET",
        body=None,
        headers={"Accept": "application/json"},
        timeout=timeout,
        failure_message="WhatsApp could not complete the connection.",
    )

    access_token = normalize_text(payload.get("access_token"))
    if not access_token:
        raise WhatsAppConnectionError(
            "WhatsApp did not return an access token for this connection.",
            details=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )

    return {
        "accessToken": access_token,
        "tokenType": normalize_text(payload.get("token_type")) or "bearer",
        "expiresIn": int(payload.get("expires_in") or 0),
    }


def register_whatsapp_phone_number(
    *,
    access_token: str,
    phone_number_id: str,
    pin: str,
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Register a number onto the Cloud API so it can send and receive.

    Numbers already running on the WhatsApp Business app are registered by the
    signup flow itself; calling this for them fails, so callers should treat a
    rejection here as informational rather than fatal.
    """

    access_token_value = normalize_text(access_token)
    phone_number_id_value = normalize_text(phone_number_id)
    pin_value = normalize_text(pin)

    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")
    if not phone_number_id_value:
        raise ValueError("WhatsApp Phone Number ID is required.")
    if not (pin_value.isdigit() and len(pin_value) == 6):
        raise ValueError("The WhatsApp registration PIN must be six digits.")

    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION
    body = urllib_parse.urlencode({
        "messaging_product": "whatsapp",
        "pin": pin_value,
    }).encode("utf-8")

    return _graph_request(
        url=f"https://graph.facebook.com/{api_version_value}/{phone_number_id_value}/register",
        method="POST",
        body=body,
        headers={
            "Authorization": f"Bearer {access_token_value}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=timeout,
        failure_message="WhatsApp could not register this phone number.",
    )
