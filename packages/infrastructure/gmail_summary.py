"""Small Gmail read-only helpers for OAuth validation and digest groundwork."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

GMAIL_MESSAGES_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_TIMEOUT_SECONDS = 20
GMAIL_MAX_DIGEST_MESSAGES = 10
GMAIL_MAX_RECEIPT_ATTACHMENTS_PER_MESSAGE = 10
GMAIL_MAX_RECEIPT_ATTACHMENT_BYTES = 8 * 1024 * 1024
_ATTACHMENT_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._ -]+")
_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_RECEIPT_ATTACHMENT_MIME_TYPES = {"application/pdf"}


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
        include_attachments: bool = False,
        attachment_output_dir: Path | str | None = None,
        attachment_url_prefix: str = "",
    ) -> list[dict[str, Any]]:
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
        summaries: list[dict[str, Any]] = []
        output_dir = Path(attachment_output_dir) if attachment_output_dir else None
        if include_attachments and output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        for raw_message in raw_messages[:safe_max]:
            if not isinstance(raw_message, dict):
                continue
            message_id = str(raw_message.get("id") or "").strip()
            if not message_id:
                continue
            encoded_message_id = urllib_parse.quote(message_id, safe="")
            detail_params = urllib_parse.urlencode(
                [("format", "full")]
                if include_attachments
                else [
                    ("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "Date"),
                ]
            )
            message = self._get_json(f"{GMAIL_MESSAGES_API_URL}/{encoded_message_id}?{detail_params}", token)
            item: dict[str, Any] = {
                "id": str(message.get("id") or message_id).strip(),
                "threadId": str(message.get("threadId") or raw_message.get("threadId") or "").strip(),
                "from": _header_value(message, "From"),
                "subject": _header_value(message, "Subject"),
                "date": _header_value(message, "Date"),
                "snippet": str(message.get("snippet") or "").strip(),
            }
            if include_attachments:
                item["attachments"] = self._save_receipt_attachments(
                    token,
                    message_id=message_id,
                    message=message,
                    output_dir=output_dir,
                    url_prefix=attachment_url_prefix,
                )
            summaries.append(item)
        return summaries

    def _save_receipt_attachments(
        self,
        access_token: str,
        *,
        message_id: str,
        message: dict[str, Any],
        output_dir: Path | None,
        url_prefix: str = "",
    ) -> list[dict[str, Any]]:
        if output_dir is None:
            return []
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        attachments: list[dict[str, Any]] = []
        for part in _iter_payload_parts(payload):
            if len(attachments) >= GMAIL_MAX_RECEIPT_ATTACHMENTS_PER_MESSAGE:
                break
            if not isinstance(part, dict):
                continue
            mime_type = str(part.get("mimeType") or "").strip().lower()
            filename = str(part.get("filename") or "").strip()
            if not _is_receipt_attachment(mime_type, filename):
                continue
            attachment_index = len(attachments) + 1
            body = part.get("body") if isinstance(part.get("body"), dict) else {}
            size = int(body.get("size") or 0)
            safe_name = _safe_attachment_filename(
                filename,
                fallback=f"receipt-{attachment_index:02d}",
                mime_type=mime_type,
                message_id=message_id,
                part_index=attachment_index,
            )
            if size > GMAIL_MAX_RECEIPT_ATTACHMENT_BYTES:
                attachments.append({
                    "filename": safe_name,
                    "mimeType": mime_type,
                    "size": size,
                    "status": "skipped",
                    "reason": "Attachment is too large to include in the receipt bundle.",
                })
                continue
            data_value = str(body.get("data") or "").strip()
            attachment_id = str(body.get("attachmentId") or "").strip()
            if attachment_id:
                encoded_message_id = urllib_parse.quote(message_id, safe="")
                encoded_attachment_id = urllib_parse.quote(attachment_id, safe="")
                attachment_payload = self._get_json(
                    f"{GMAIL_MESSAGES_API_URL}/{encoded_message_id}/attachments/{encoded_attachment_id}",
                    access_token,
                )
                data_value = str(attachment_payload.get("data") or "").strip()
                size = int(attachment_payload.get("size") or size or 0)
            if not data_value:
                continue
            try:
                content = _decode_gmail_attachment_data(data_value)
            except ValueError:
                continue
            if len(content) > GMAIL_MAX_RECEIPT_ATTACHMENT_BYTES:
                attachments.append({
                    "filename": safe_name,
                    "mimeType": mime_type,
                    "size": len(content),
                    "status": "skipped",
                    "reason": "Attachment is too large to include in the receipt bundle.",
                })
                continue
            file_path = _deduplicate_path(output_dir / safe_name)
            file_path.write_bytes(content)
            attachment: dict[str, Any] = {
                "filename": file_path.name,
                "mimeType": mime_type,
                "size": len(content),
                "path": str(file_path),
                "status": "saved",
            }
            if url_prefix:
                attachment["url"] = f"{str(url_prefix).rstrip('/')}/{urllib_parse.quote(file_path.name)}"
            attachments.append(attachment)
        return attachments

    def run(
        self,
        access_token: str,
        *,
        query: str = "in:inbox newer_than:1d",
        max_results: int = GMAIL_MAX_DIGEST_MESSAGES,
        include_attachments: bool = False,
        attachment_output_dir: Path | str | None = None,
        attachment_url_prefix: str = "",
    ) -> dict[str, Any]:
        items = self.fetch_message_summaries(
            access_token,
            query=query,
            max_results=max_results,
            include_attachments=include_attachments,
            attachment_output_dir=attachment_output_dir,
            attachment_url_prefix=attachment_url_prefix,
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


def _iter_payload_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    pending = [payload] if isinstance(payload, dict) else []
    while pending:
        part = pending.pop(0)
        parts.append(part)
        child_parts = part.get("parts") if isinstance(part.get("parts"), list) else []
        pending.extend(child for child in child_parts if isinstance(child, dict))
    return parts


def _is_receipt_attachment(mime_type: str, filename: str) -> bool:
    normalized_mime_type = str(mime_type or "").strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    return (
        normalized_mime_type.startswith("image/")
        or normalized_mime_type in _RECEIPT_ATTACHMENT_MIME_TYPES
        or suffix in _IMAGE_EXTENSIONS
        or suffix == ".pdf"
    )


def _decode_gmail_attachment_data(value: str) -> bytes:
    data = str(value or "").strip()
    if not data:
        raise ValueError("missing Gmail attachment data")
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("invalid Gmail attachment data") from exc


def _safe_attachment_filename(
    filename: str,
    *,
    fallback: str,
    mime_type: str,
    message_id: str,
    part_index: int,
) -> str:
    raw_name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not raw_name:
        extension = mimetypes.guess_extension(str(mime_type or "").split(";", 1)[0].strip()) or ".bin"
        if extension == ".jpe":
            extension = ".jpg"
        raw_name = f"{fallback}{extension}"
    stem = Path(raw_name).stem.strip() or fallback
    suffix = Path(raw_name).suffix.lower() or ".bin"
    stem = _ATTACHMENT_FILENAME_RE.sub("-", stem).strip(" .-_") or fallback
    message_fragment = _ATTACHMENT_FILENAME_RE.sub("-", str(message_id or "message"))[:12].strip(" .-_") or "message"
    return f"{message_fragment}-{part_index:02d}-{stem[:50]}{suffix}"


def _deduplicate_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 100):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{datetime.now().timestamp():.0f}{suffix}")
