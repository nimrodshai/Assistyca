"""Small Gmail read-only helpers for OAuth validation and digest groundwork."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

GMAIL_MESSAGES_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_TIMEOUT_SECONDS = 20
GMAIL_MAX_DIGEST_MESSAGES = 10


class GmailAuthorizationError(RuntimeError):
    """Raised when a saved Google credential cannot read Gmail."""

    code = "gmail_authorization_failed"


class GmailSummaryError(RuntimeError):
    """Raised when Gmail cannot be reached or returns an unusable response."""

    def __init__(self, message: str, *, code: str = "gmail_summary_failed") -> None:
        super().__init__(message)
        self.code = code


class GmailAccessValidator:
    """Validate a Gmail read-only grant without reading message bodies."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = GMAIL_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def validate(
        self,
        access_token: str,
        *,
        query: str = "in:inbox newer_than:1d",
    ) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            raise GmailAuthorizationError(
                "Gmail access needs attention: no usable access token was returned. Reconnect Gmail with read-only access, then try again."
            )

        params = urllib_parse.urlencode({
            "maxResults": "1",
            "q": str(query or "in:inbox newer_than:1d").strip()[:200],
        })
        request = urllib_request.Request(
            f"{GMAIL_MESSAGES_API_URL}?{params}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise GmailAuthorizationError(
                    "Gmail access needs attention: Google rejected the saved credential or its permissions. Reconnect Gmail with read-only access, then try again."
                ) from exc
            raise GmailSummaryError(
                f"Gmail returned an error ({exc.code}). Try again or reconnect Gmail.",
                code="gmail_provider_error",
            ) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise GmailSummaryError(
                "I couldn't reach Gmail. Check the connection and try again.",
                code="gmail_network_error",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GmailSummaryError(
                "Gmail returned an unreadable response.",
                code="gmail_provider_error",
            ) from exc

        if not isinstance(payload, dict):
            raise GmailSummaryError(
                "Gmail returned an invalid response.",
                code="gmail_provider_error",
            )
        messages = payload.get("messages")
        if messages is not None and not isinstance(messages, list):
            raise GmailSummaryError(
                "Gmail returned an invalid message list.",
                code="gmail_provider_error",
            )
        return {
            "messageCount": len(messages or []),
            "resultSizeEstimate": int(payload.get("resultSizeEstimate") or 0),
        }


def _header_value(message: dict[str, Any], name: str) -> str:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    normalized_name = name.lower()
    for header in headers:
        if not isinstance(header, dict):
            continue
        if str(header.get("name") or "").strip().lower() == normalized_name:
            return str(header.get("value") or "").strip()
    return ""


def _format_digest_item(index: int, item: dict[str, str]) -> str:
    subject = item.get("subject") or "(no subject)"
    sender = item.get("from") or "Unknown sender"
    date = item.get("date") or ""
    snippet = item.get("snippet") or ""
    heading = f"{index}. {subject} - {sender}"
    if date:
        heading = f"{heading} - {date}"
    return f"{heading}\n   {snippet}" if snippet else heading


class GmailDigestRunner:
    """Build a lightweight digest from Gmail metadata and snippets."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = GMAIL_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def _get_json(self, url: str, access_token: str) -> dict[str, Any]:
        request = urllib_request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise GmailAuthorizationError(
                    "Gmail access needs attention: Google rejected the saved credential or its permissions. Reconnect Gmail with read-only access, then try again."
                ) from exc
            raise GmailSummaryError(
                f"Gmail returned an error ({exc.code}). Try again or reconnect Gmail.",
                code="gmail_provider_error",
            ) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise GmailSummaryError(
                "I couldn't reach Gmail. Check the connection and try again.",
                code="gmail_network_error",
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GmailSummaryError(
                "Gmail returned an unreadable response.",
                code="gmail_provider_error",
            ) from exc

        if not isinstance(payload, dict):
            raise GmailSummaryError(
                "Gmail returned an invalid response.",
                code="gmail_provider_error",
            )
        return payload

    def fetch_message_summaries(
        self,
        access_token: str,
        *,
        query: str = "in:inbox newer_than:1d",
        max_results: int = GMAIL_MAX_DIGEST_MESSAGES,
    ) -> list[dict[str, str]]:
        token = str(access_token or "").strip()
        if not token:
            raise GmailAuthorizationError(
                "Gmail access needs attention: no usable access token is saved. Reconnect Gmail with read-only access, then try again."
            )
        safe_query = str(query or "in:inbox newer_than:1d").strip()[:200]
        safe_max = max(1, min(GMAIL_MAX_DIGEST_MESSAGES, int(max_results or GMAIL_MAX_DIGEST_MESSAGES)))
        list_params = urllib_parse.urlencode({
            "maxResults": str(safe_max),
            "q": safe_query,
        })
        list_payload = self._get_json(f"{GMAIL_MESSAGES_API_URL}?{list_params}", token)
        raw_messages = list_payload.get("messages") if isinstance(list_payload.get("messages"), list) else []
        summaries: list[dict[str, str]] = []
        for raw_message in raw_messages[:safe_max]:
            if not isinstance(raw_message, dict):
                continue
            message_id = str(raw_message.get("id") or "").strip()
            if not message_id:
                continue
            encoded_message_id = urllib_parse.quote(message_id, safe="")
            detail_params = urllib_parse.urlencode([
                ("format", "metadata"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Subject"),
                ("metadataHeaders", "Date"),
            ])
            message = self._get_json(f"{GMAIL_MESSAGES_API_URL}/{encoded_message_id}?{detail_params}", token)
            summaries.append({
                "id": str(message.get("id") or message_id).strip(),
                "threadId": str(message.get("threadId") or raw_message.get("threadId") or "").strip(),
                "from": _header_value(message, "From"),
                "subject": _header_value(message, "Subject"),
                "date": _header_value(message, "Date"),
                "snippet": str(message.get("snippet") or "").strip(),
            })
        return summaries

    def run(
        self,
        access_token: str,
        *,
        query: str = "in:inbox newer_than:1d",
        max_results: int = GMAIL_MAX_DIGEST_MESSAGES,
    ) -> dict[str, Any]:
        items = self.fetch_message_summaries(
            access_token,
            query=query,
            max_results=max_results,
        )
        header = "Gmail digest"
        if not items:
            return {
                "ok": True,
                "message": f"{header}\n\nNo Gmail messages found for `{query}`.",
                "summary": header,
                "messageCount": 0,
                "items": [],
            }
        lines = [header, "", f"{len(items)} recent message{'s' if len(items) != 1 else ''}:"]
        for index, item in enumerate(items, start=1):
            lines.append(_format_digest_item(index, item))
        return {
            "ok": True,
            "message": "\n".join(lines),
            "summary": f"{header} - {len(items)} message{'s' if len(items) != 1 else ''}",
            "messageCount": len(items),
            "items": items,
        }
