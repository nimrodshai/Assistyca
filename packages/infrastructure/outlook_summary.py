"""Outlook and Microsoft 365 mail reading through Microsoft Graph.

This mirrors ``gmail_summary`` on purpose: same constructor arguments, same
``run`` result, same per-message item keys. The receipt bundle and the digest
formatter cannot tell which mailbox a run came from, so neither had to learn
about a second provider.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure import mail_attachments
from packages.infrastructure import mail_body
from packages.infrastructure.mail_search import MailQuery
from packages.infrastructure.mail_search import matches as query_matches
from packages.infrastructure.mail_search import to_graph_search

GRAPH_MESSAGES_API_URL = "https://graph.microsoft.com/v1.0/me/messages"
# Mail.Read does not cover /me, so reading the mailbox address needs User.Read
# alongside it. Without that grant this returns nothing and the connection
# falls back to a label the user types.
GRAPH_ME_API_URL = "https://graph.microsoft.com/v1.0/me"
# Gmail's ``in:inbox`` has no KQL equivalent, so the inbox is a different
# collection instead. Without this a digest would also read Sent and Archive.
GRAPH_INBOX_MESSAGES_API_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
GRAPH_TIMEOUT_SECONDS = 20
GRAPH_MAX_DIGEST_MESSAGES = 10
# A digest shows the newest handful; a receipt search has to see the whole
# month it was asked about, so it may ask for more, up to this ceiling.
GRAPH_MAX_SEARCH_MESSAGES = 100
# One page is plenty for a digest. A receipt month can need more, because the
# client-side date re-check drops whatever the KQL window let through.
GRAPH_MAX_PAGES = 5
GRAPH_PAGE_SIZE = 25
GRAPH_MESSAGE_FIELDS = "id,conversationId,subject,from,receivedDateTime,bodyPreview,hasAttachments"
# A receipt run needs the total, which lives in the body rather than in the
# preview Graph returns by default. Digest runs stay on the lighter select.
GRAPH_RECEIPT_MESSAGE_FIELDS = f"{GRAPH_MESSAGE_FIELDS},body"


class OutlookAuthorizationError(RuntimeError):
    """Raised when a saved Microsoft credential cannot read the mailbox."""

    code = "outlook_authorization_failed"


class OutlookSummaryError(RuntimeError):
    """Raised when Graph cannot be reached or returns an unusable response."""

    def __init__(self, message: str, *, code: str = "outlook_summary_failed") -> None:
        super().__init__(message)
        self.code = code


def _graph_request(
    opener: Callable[..., Any],
    url: str,
    access_token: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib_request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            # Mail search is a KQL search; Graph wants the eventual-consistency
            # header on searched collections.
            "ConsistencyLevel": "eventual",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib_error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: Microsoft rejected the saved credential or its permissions. "
                "Reconnect Outlook with read-only access, then try again."
            ) from exc
        raise OutlookSummaryError(
            f"Outlook returned an error ({exc.code}). Try again or reconnect Outlook.",
            code="outlook_provider_error",
        ) from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        raise OutlookSummaryError(
            "I couldn't reach Outlook. Check the connection and try again.",
            code="outlook_network_error",
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutlookSummaryError(
            "Outlook returned an unreadable response.",
            code="outlook_provider_error",
        ) from exc

    if not isinstance(payload, dict):
        raise OutlookSummaryError(
            "Outlook returned an invalid response.",
            code="outlook_provider_error",
        )
    return payload


def _extract_body_text(message: dict[str, Any]) -> str:
    """Return the readable text of a Graph message body."""

    body = message.get("body") if isinstance(message.get("body"), dict) else {}
    content = body.get("content")
    if str(body.get("contentType") or "").strip().lower() == "html":
        return mail_body.limit_body_text(mail_body.html_to_text(content))
    return mail_body.limit_body_text(content)


def _format_sender(message: dict[str, Any]) -> str:
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    address_block = sender.get("emailAddress") if isinstance(sender.get("emailAddress"), dict) else {}
    name = str(address_block.get("name") or "").strip()
    address = str(address_block.get("address") or "").strip()
    if name and address:
        return f"{name} <{address}>"
    return address or name


def _parse_received(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _format_date_header(received: datetime | None, fallback: Any = "") -> str:
    """Render the date the way a Gmail ``Date:`` header reads.

    The receipt bundle prints this string straight into the Excel and PDF, so
    an Outlook row has to look like a Gmail row next to it.
    """

    if received is None:
        return str(fallback or "").strip()
    return format_datetime(received)


class OutlookAccessValidator:
    """Validate a Microsoft mail read grant without reading message bodies."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = GRAPH_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def validate(self, access_token: str) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: no usable access token was returned. "
                "Reconnect Outlook with read-only access, then try again."
            )

        params = urllib_parse.urlencode({"$top": "1", "$select": "id"})
        payload = _graph_request(
            self._opener,
            f"{GRAPH_MESSAGES_API_URL}?{params}",
            token,
            timeout_seconds=self.timeout_seconds,
        )
        messages = payload.get("value") if isinstance(payload.get("value"), list) else []
        return {
            "outlookValidation": "ok",
            "messageCount": len(messages or []),
            "emailAddress": self.read_mailbox_address(token),
        }

    def read_mailbox_address(self, access_token: str) -> str:
        """Return the connected mailbox's own address, or "" if unavailable.

        Identifying a mailbox is a convenience, not a permission check. An
        Outlook connection made before User.Read was requested still works for
        reading mail, so a rejection here must not fail the connect.
        """

        token = str(access_token or "").strip()
        if not token:
            return ""

        params = urllib_parse.urlencode({"$select": "mail,userPrincipalName"})
        try:
            payload = _graph_request(
                self._opener,
                f"{GRAPH_ME_API_URL}?{params}",
                token,
                timeout_seconds=self.timeout_seconds,
            )
        except (OutlookAuthorizationError, OutlookSummaryError, OSError):
            return ""

        if not isinstance(payload, dict):
            return ""
        address = str(payload.get("mail") or "").strip()
        if not address:
            # A work account without a routable mail attribute still has a UPN,
            # which is an address-shaped identifier good enough to label it.
            address = str(payload.get("userPrincipalName") or "").strip()
        return address.lower()


class OutlookDigestRunner:
    """Build a digest from Graph message metadata and body previews."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = GRAPH_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def _get_json(self, url: str, access_token: str) -> dict[str, Any]:
        return _graph_request(
            self._opener,
            url,
            access_token,
            timeout_seconds=self.timeout_seconds,
        )

    def _first_page_url(self, query: MailQuery, page_size: int, *, include_body: bool = False) -> str:
        search = to_graph_search(query)
        params: list[tuple[str, str]] = [
            ("$select", GRAPH_RECEIPT_MESSAGE_FIELDS if include_body else GRAPH_MESSAGE_FIELDS),
            ("$top", str(page_size)),
        ]
        if search:
            # Graph rejects $orderby together with $search, and rejects
            # $search together with $filter, so the search string carries the
            # whole intent on its own.
            params.append(("$search", f'"{search}"'))
        else:
            params.append(("$orderby", "receivedDateTime desc"))
        base_url = GRAPH_INBOX_MESSAGES_API_URL if query.in_inbox else GRAPH_MESSAGES_API_URL
        return f"{base_url}?{urllib_parse.urlencode(params)}"

    def fetch_message_summaries(
        self,
        access_token: str,
        *,
        query: MailQuery,
        max_results: int = GRAPH_MAX_DIGEST_MESSAGES,
        include_attachments: bool = False,
        attachment_output_dir: Path | str | None = None,
        attachment_url_prefix: str = "",
    ) -> list[dict[str, Any]]:
        token = str(access_token or "").strip()
        if not token:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: no usable credential is saved. "
                "Reconnect Outlook with read-only access, then try again."
            )

        safe_max = max(1, min(GRAPH_MAX_SEARCH_MESSAGES, int(max_results or GRAPH_MAX_DIGEST_MESSAGES)))
        output_dir = Path(attachment_output_dir) if attachment_output_dir else None
        if include_attachments and output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        summaries: list[dict[str, Any]] = []
        url = self._first_page_url(query, GRAPH_PAGE_SIZE, include_body=include_attachments)
        for _ in range(GRAPH_MAX_PAGES):
            payload = self._get_json(url, token)
            raw_messages = payload.get("value") if isinstance(payload.get("value"), list) else []
            for raw_message in raw_messages:
                if len(summaries) >= safe_max:
                    break
                if not isinstance(raw_message, dict):
                    continue
                message_id = str(raw_message.get("id") or "").strip()
                if not message_id:
                    continue
                received = _parse_received(raw_message.get("receivedDateTime"))
                subject = str(raw_message.get("subject") or "").strip()
                sender = _format_sender(raw_message)
                snippet = str(raw_message.get("bodyPreview") or "").strip()
                has_attachment = bool(raw_message.get("hasAttachments"))
                # Graph's KQL window is looser than Gmail's operators, so the
                # month a receipt run asked for is enforced here as well.
                if not query_matches(
                    query,
                    received=received,
                    subject=subject,
                    sender=sender,
                    snippet=snippet,
                    has_attachment=has_attachment,
                ):
                    continue
                item: dict[str, Any] = {
                    "id": message_id,
                    "threadId": str(raw_message.get("conversationId") or "").strip(),
                    "from": sender,
                    "subject": subject,
                    "date": _format_date_header(received, raw_message.get("receivedDateTime")),
                    "snippet": snippet,
                }
                if include_attachments:
                    item["bodyText"] = _extract_body_text(raw_message)
                    item["attachments"] = (
                        self._save_receipt_attachments(
                            token,
                            message_id=message_id,
                            output_dir=output_dir,
                            url_prefix=attachment_url_prefix,
                        )
                        if has_attachment
                        else []
                    )
                summaries.append(item)

            next_link = str(payload.get("@odata.nextLink") or "").strip()
            if len(summaries) >= safe_max or not next_link:
                break
            url = next_link
        return summaries

    def _save_receipt_attachments(
        self,
        access_token: str,
        *,
        message_id: str,
        output_dir: Path | None,
        url_prefix: str = "",
    ) -> list[dict[str, Any]]:
        if output_dir is None:
            return []
        encoded_message_id = urllib_parse.quote(message_id, safe="")
        list_params = urllib_parse.urlencode({
            "$select": "id,name,contentType,size",
            "$top": str(mail_attachments.MAX_RECEIPT_ATTACHMENTS_PER_MESSAGE),
        })
        listing = self._get_json(
            f"{GRAPH_MESSAGES_API_URL}/{encoded_message_id}/attachments?{list_params}",
            access_token,
        )
        raw_attachments = listing.get("value") if isinstance(listing.get("value"), list) else []

        attachments: list[dict[str, Any]] = []
        for raw_attachment in raw_attachments:
            if len(attachments) >= mail_attachments.MAX_RECEIPT_ATTACHMENTS_PER_MESSAGE:
                break
            if not isinstance(raw_attachment, dict):
                continue
            mime_type = str(raw_attachment.get("contentType") or "").strip().lower()
            filename = str(raw_attachment.get("name") or "").strip()
            if not mail_attachments.is_receipt_attachment(mime_type, filename):
                continue
            attachment_index = len(attachments) + 1
            safe_name = mail_attachments.safe_attachment_filename(
                filename,
                fallback=f"receipt-{attachment_index:02d}",
                mime_type=mime_type,
                message_id=message_id,
                part_index=attachment_index,
            )
            size = int(raw_attachment.get("size") or 0)
            if size > mail_attachments.MAX_RECEIPT_ATTACHMENT_BYTES:
                attachments.append(mail_attachments.skipped_attachment(
                    safe_name,
                    mime_type=mime_type,
                    size=size,
                ))
                continue

            data_value = str(raw_attachment.get("contentBytes") or "").strip()
            if not data_value:
                attachment_id = str(raw_attachment.get("id") or "").strip()
                if not attachment_id:
                    continue
                encoded_attachment_id = urllib_parse.quote(attachment_id, safe="")
                detail = self._get_json(
                    f"{GRAPH_MESSAGES_API_URL}/{encoded_message_id}/attachments/{encoded_attachment_id}",
                    access_token,
                )
                data_value = str(detail.get("contentBytes") or "").strip()
            if not data_value:
                continue
            try:
                content = mail_attachments.decode_base64_attachment(data_value, url_safe=False)
            except ValueError:
                continue
            if len(content) > mail_attachments.MAX_RECEIPT_ATTACHMENT_BYTES:
                attachments.append(mail_attachments.skipped_attachment(
                    safe_name,
                    mime_type=mime_type,
                    size=len(content),
                ))
                continue
            attachments.append(mail_attachments.save_attachment(
                content,
                output_dir=output_dir,
                filename=safe_name,
                mime_type=mime_type,
                url_prefix=url_prefix,
            ))
        return attachments

    def run(
        self,
        access_token: str,
        *,
        query: MailQuery,
        max_results: int = GRAPH_MAX_DIGEST_MESSAGES,
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
        header = "Outlook digest"
        if not items:
            return {
                "ok": True,
                "message": f"{header}\n\nNo Outlook messages found for {query.describe()}.",
                "summary": header,
                "messageCount": 0,
                "items": [],
            }
        lines = [header, "", f"{len(items)} recent message{'s' if len(items) != 1 else ''}:"]
        for index, item in enumerate(items, start=1):
            subject = item.get("subject") or "(no subject)"
            sender = item.get("from") or "Unknown sender"
            date_text = item.get("date") or ""
            snippet = item.get("snippet") or ""
            heading = f"{index}. {subject} - {sender}"
            if date_text:
                heading = f"{heading} - {date_text}"
            lines.append(f"{heading}\n   {snippet}" if snippet else heading)
        return {
            "ok": True,
            "message": "\n".join(lines),
            "summary": f"{header} - {len(items)} message{'s' if len(items) != 1 else ''}",
            "messageCount": len(items),
            "items": items,
        }
