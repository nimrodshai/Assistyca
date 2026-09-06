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
# isDraft rides along on every read: a mailbox search returns the drafts
# sitting in it too, and a draft is not mail that happened.
GRAPH_MESSAGE_FIELDS = "id,conversationId,subject,from,receivedDateTime,bodyPreview,hasAttachments,isDraft"
# A receipt run needs the total, which lives in the body rather than in the
# preview Graph returns by default. Digest runs stay on the lighter select.
GRAPH_RECEIPT_MESSAGE_FIELDS = f"{GRAPH_MESSAGE_FIELDS},body"
# Enough of Graph's error body to name the cause without filling the log.
GRAPH_ERROR_LOG_CHARS = 500


class OutlookAuthorizationError(RuntimeError):
    """Raised when a saved Microsoft credential cannot read the mailbox."""

    code = "outlook_authorization_failed"


class OutlookSummaryError(RuntimeError):
    """Raised when Graph cannot be reached or returns an unusable response."""

    def __init__(self, message: str, *, code: str = "outlook_summary_failed") -> None:
        super().__init__(message)
        self.code = code


def _log_graph_failure(url: str, status: Any, detail: Any) -> None:
    """Record what Graph refused, since the client only ever sees a sentence.

    The message handed back to a client is deliberately plain, which leaves
    nothing behind to diagnose from: a mailbox Graph keeps rejecting reads as
    "try it again later" for ever. The URL carries the query that failed. The
    access token travels in a header and is never part of either.
    """

    body = mail_body.collapse_whitespace(detail)[:GRAPH_ERROR_LOG_CHARS]
    print(f"Outlook read failed: status={status} url={url} detail={body}", flush=True)


def _read_error_body(exc: urllib_error.HTTPError) -> str:
    """The body Graph sent with an error, or "" when there is nothing to read.

    An error carrying no response body cannot be read at all, so this never
    lets a failed read of the explanation replace the failure being explained.
    """

    if getattr(exc, "fp", None) is None:
        return ""
    try:
        raw = exc.read()
    except Exception:
        return ""
    return raw.decode("utf-8", errors="replace") if raw else ""


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
        _log_graph_failure(url, exc.code, _read_error_body(exc))
        if exc.code in {401, 403}:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: Microsoft rejected the saved credential or its permissions. "
                "Reconnect Outlook with read-only access, then try again."
            ) from exc
        raise OutlookSummaryError(
            # The person reading this is a client, not an operator: the HTTP
            # code belongs in ``code`` and the logs, not in the sentence.
            "I couldn't read Outlook just now. Try it again later, and reconnect Outlook if it keeps happening.",
            code="outlook_provider_error",
        ) from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        _log_graph_failure(url, "network", exc)
        raise OutlookSummaryError(
            "I couldn't reach Outlook. Check the connection and try again.",
            code="outlook_network_error",
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log_graph_failure(url, "unreadable-response", exc)
        raise OutlookSummaryError(
            "I couldn't read Outlook just now. Try it again later, and reconnect Outlook if it keeps happening.",
            code="outlook_provider_error",
        ) from exc

    if not isinstance(payload, dict):
        _log_graph_failure(url, "unexpected-payload", type(payload).__name__)
        raise OutlookSummaryError(
            "I couldn't read Outlook just now. Try it again later, and reconnect Outlook if it keeps happening.",
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


def _as_search_literal(search: str) -> str:
    """Wrap a KQL string as the quoted literal ``$search`` expects.

    The KQL quotes each word it searches for, and those quotes have to be
    escaped on the way in or the first one closes the literal early - Graph
    then reads the rest of the search as syntax it does not know and refuses
    the whole request, which is not an authorization failure and so reads back
    as a mailbox that is connected but cannot be opened.
    """

    escaped = str(search or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
            params.append(("$search", _as_search_literal(search)))
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
        include_body: bool = False,
        include_attachments: bool = False,
        attachment_output_dir: Path | str | None = None,
        attachment_url_prefix: str = "",
        known: "Callable[[list[str]], dict[str, dict[str, Any]]] | None" = None,
    ) -> list[dict[str, Any]]:
        """Read the messages a query matches.

        Graph hands the body back on the listing page, so a message read
        before costs nothing extra to read again. ``known`` still matters: a
        message it names carries its earlier verdict, is marked as supplied
        by the ledger, and does not count against ``max_results``, so a month
        read in earlier runs is read to the end.
        """

        token = str(access_token or "").strip()
        if not token:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: no usable credential is saved. "
                "Reconnect Outlook with read-only access, then try again."
            )

        # A run that saves attachments is a receipt run, and it reads the body
        # too. Graph hands the body back on the listing page, so asking for it
        # costs a bigger response rather than a request per message.
        want_body = bool(include_body or include_attachments)
        safe_max = max(1, min(GRAPH_MAX_SEARCH_MESSAGES, int(max_results or GRAPH_MAX_DIGEST_MESSAGES)))
        output_dir = Path(attachment_output_dir) if attachment_output_dir else None
        if include_attachments and output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        summaries: list[dict[str, Any]] = []
        fetched = 0
        url = self._first_page_url(query, GRAPH_PAGE_SIZE, include_body=want_body)
        for _ in range(GRAPH_MAX_PAGES):
            payload = self._get_json(url, token)
            raw_messages = payload.get("value") if isinstance(payload.get("value"), list) else []
            page_ids = [
                str(raw.get("id") or "").strip()
                for raw in raw_messages
                if isinstance(raw, dict) and str(raw.get("id") or "").strip()
            ]
            remembered = known(page_ids) if known is not None and page_ids else {}
            for raw_message in raw_messages:
                if not isinstance(raw_message, dict):
                    continue
                message_id = str(raw_message.get("id") or "").strip()
                if not message_id:
                    continue
                cached = remembered.get(message_id)
                if fetched >= safe_max and not isinstance(cached, dict):
                    continue
                # A draft reply quotes the message it answers, so a receipt
                # someone started replying to would come back a second time,
                # dated the day the reply was begun and carrying the same
                # amount.
                if bool(raw_message.get("isDraft")):
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
                if want_body:
                    item["bodyText"] = _extract_body_text(raw_message)
                if isinstance(cached, dict):
                    for key in ("receiptVerdict", "fromLedger"):
                        if key in cached:
                            item[key] = cached[key]
                else:
                    fetched += 1
                if include_attachments:
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
                    item["attachmentNames"] = [
                        str(attachment.get("filename") or "").strip()
                        for attachment in item["attachments"]
                        if isinstance(attachment, dict) and str(attachment.get("filename") or "").strip()
                    ]
                elif want_body and not has_attachment:
                    # Graph says outright that this message carries nothing,
                    # and that is worth passing on. What a message does carry
                    # is a request of its own per message, which a run that
                    # was not asked to save anything does not make - so those
                    # messages travel with nothing said about their files
                    # rather than with a wrong "none".
                    item["attachmentNames"] = []
                summaries.append(item)

            next_link = str(payload.get("@odata.nextLink") or "").strip()
            # With a ledger the listing runs on past the download ceiling,
            # so the older messages earlier runs read are gathered too.
            if (known is None and len(summaries) >= safe_max) or not next_link:
                break
            url = next_link
        return summaries

    def save_message_attachments(
        self,
        access_token: str,
        *,
        message_id: str,
        output_dir: Path | str,
        url_prefix: str = "",
        filename_prefix: str = "",
    ) -> list[dict[str, Any]]:
        """Save the receipt files attached to one known message.

        A search run saves attachments as it reads the mailbox. Keeping an
        answer happens later, when the only thing left of that run is the id
        of the message the total came from, so that message is asked for by
        id here.
        """

        token = str(access_token or "").strip()
        if not token:
            raise OutlookAuthorizationError(
                "Outlook access needs attention: no usable credential is saved. "
                "Reconnect Outlook with read-only access, then try again."
            )
        safe_message_id = str(message_id or "").strip()
        if not safe_message_id:
            return []
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return self._save_receipt_attachments(
            token,
            message_id=safe_message_id,
            output_dir=directory,
            url_prefix=url_prefix,
            filename_prefix=filename_prefix,
        )

    def _save_receipt_attachments(
        self,
        access_token: str,
        *,
        message_id: str,
        output_dir: Path | None,
        url_prefix: str = "",
        filename_prefix: str = "",
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
                name_prefix=filename_prefix,
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
            if not mail_attachments.content_is_receipt_attachment(content, mime_type=mime_type, filename=filename):
                attachments.append(mail_attachments.skipped_attachment(
                    safe_name,
                    mime_type=mime_type,
                    size=len(content),
                    reason=mail_attachments.ATTACHMENT_NOT_A_RECEIPT_FILE_REASON,
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
        include_body: bool = False,
        include_attachments: bool = False,
        attachment_output_dir: Path | str | None = None,
        attachment_url_prefix: str = "",
        known: "Callable[[list[str]], dict[str, dict[str, Any]]] | None" = None,
    ) -> dict[str, Any]:
        items = self.fetch_message_summaries(
            access_token,
            query=query,
            max_results=max_results,
            include_body=include_body,
            include_attachments=include_attachments,
            attachment_output_dir=attachment_output_dir,
            attachment_url_prefix=attachment_url_prefix,
            known=known,
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
