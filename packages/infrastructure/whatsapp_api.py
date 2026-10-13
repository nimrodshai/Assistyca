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


# A group holds eight participants, and the business number is one of them, so
# seven people can be in it. Meta enforces this; it is repeated here so a
# caller can say no before the invite goes out rather than after.
WHATSAPP_GROUP_PARTICIPANT_LIMIT = 8
WHATSAPP_GROUP_SUBJECT_LIMIT = 128
WHATSAPP_GROUP_DESCRIPTION_LIMIT = 2048


def create_whatsapp_group(
    *,
    access_token: str,
    phone_number_id: str,
    subject: str,
    description: str = "",
    join_approval_mode: str = "",
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Open a group on the business number and get the link people join by.

    There is no way to put a number into a group that already exists, in either
    direction: the business cannot be added to the family's group, and it
    cannot add the family to its own. A group is created here and everyone
    walks in through the invite link that comes back, which is why the link is
    the only part of the answer a caller really needs.

    Groups need an Official Business Account, so this fails until the business
    is verified. The failure comes back as WhatsAppConnectionError carrying
    Meta's own words, which are worth showing rather than rewriting.
    """

    access_token_value = normalize_text(access_token)
    phone_number_id_value = normalize_text(phone_number_id)
    subject_value = normalize_text(subject)[:WHATSAPP_GROUP_SUBJECT_LIMIT]
    description_value = normalize_text(description)[:WHATSAPP_GROUP_DESCRIPTION_LIMIT]
    approval_value = normalize_text(join_approval_mode).lower()

    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")
    if not phone_number_id_value:
        raise ValueError("WhatsApp Phone Number ID is required.")
    if not subject_value:
        raise ValueError("A group needs a name.")
    if approval_value and approval_value not in {"approval_required", "auto_approve"}:
        raise ValueError("Join approval must be approval_required or auto_approve.")

    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION
    payload: dict[str, str] = {"messaging_product": "whatsapp", "subject": subject_value}
    if description_value:
        payload["description"] = description_value
    if approval_value:
        payload["join_approval_mode"] = approval_value

    return _graph_request(
        url=f"https://graph.facebook.com/{api_version_value}/{phone_number_id_value}/groups",
        method="POST",
        body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token_value}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=timeout,
        failure_message="WhatsApp could not create the group.",
    )


def fetch_whatsapp_group(
    *,
    access_token: str,
    group_id: str,
    fields: Any = ("subject", "description", "participants", "invite_link"),
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """What a group currently is: its name, its link, and who is in it."""

    access_token_value = normalize_text(access_token)
    group_id_value = normalize_text(group_id)
    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")
    if not group_id_value:
        raise ValueError("A group id is required.")

    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION
    wanted = ",".join(normalize_text(field) for field in (fields or ()) if normalize_text(field))
    query = f"?fields={urllib_parse.quote(wanted, safe=',')}" if wanted else ""

    return _graph_request(
        url=(
            f"https://graph.facebook.com/{api_version_value}/"
            f"{urllib_parse.quote(group_id_value, safe='')}{query}"
        ),
        method="GET",
        body=None,
        headers={
            "Authorization": f"Bearer {access_token_value}",
            "Accept": "application/json",
        },
        timeout=timeout,
        failure_message="WhatsApp could not read that group.",
    )


def remove_whatsapp_group_participants(
    *,
    access_token: str,
    group_id: str,
    participants: Any,
    api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Take someone out of a group.

    Joining is the person's own doing, through the link, so leaving must be
    available too - from their side by leaving, and from this side when the
    owner asks for someone to be taken out.
    """

    access_token_value = normalize_text(access_token)
    group_id_value = normalize_text(group_id)
    numbers = [normalize_text(value) for value in (participants or ()) if normalize_text(value)]

    if not access_token_value:
        raise ValueError("WhatsApp connection credentials are required.")
    if not group_id_value:
        raise ValueError("A group id is required.")
    if not numbers:
        raise ValueError("At least one participant is required.")
    if len(numbers) > WHATSAPP_GROUP_PARTICIPANT_LIMIT:
        raise ValueError("A group holds eight participants, so no more than eight can be removed at once.")

    api_version_value = normalize_text(api_version) or DEFAULT_WHATSAPP_API_VERSION
    payload = {"messaging_product": "whatsapp", "participants": [{"user": number} for number in numbers]}

    return _graph_request(
        url=(
            f"https://graph.facebook.com/{api_version_value}/"
            f"{urllib_parse.quote(group_id_value, safe='')}/participants"
        ),
        method="DELETE",
        body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token_value}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=timeout,
        failure_message="WhatsApp could not remove that participant.",
    )
