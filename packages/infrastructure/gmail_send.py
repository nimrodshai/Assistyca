"""Sending mail through a connected Gmail mailbox.

The readers in ``gmail_summary.py`` need ``gmail.readonly``; this needs
``gmail.send``, which Google grants separately. A mailbox connected before
that permission was asked for can still be read, and the sender says so in
its own error rather than failing as if the mailbox had gone.
"""

from __future__ import annotations

import base64
import json
import re
from email.message import EmailMessage
from email.utils import formataddr
from email.utils import parseaddr
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure.gmail_summary import GMAIL_MESSAGES_API_URL
from packages.infrastructure.gmail_summary import GMAIL_TIMEOUT_SECONDS
from packages.infrastructure.gmail_summary import GmailAuthorizationError
from packages.infrastructure.gmail_summary import GmailSummaryError

GMAIL_SEND_API_URL = f"{GMAIL_MESSAGES_API_URL}/send"
GMAIL_SEND_OAUTH_SCOPE = "https://www.googleapis.com/auth/gmail.send"
# Recipients per message and the size of what is written, so a runaway
# request cannot turn a mailbox into a bulk sender.
MAX_RECIPIENTS = 20
MAX_SUBJECT_LENGTH = 300
MAX_BODY_LENGTH = 20_000
ADDRESS_PATTERN = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class GmailSendPermissionError(GmailAuthorizationError):
    """The mailbox is connected, but without permission to send."""

    code = "gmail_send_permission_required"

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "Gmail is connected for reading only. Connect Google again and allow sending, then try once more."
        )


def normalize_addresses(values: Any, *, limit: int = MAX_RECIPIENTS) -> list[str]:
    """Addresses as a clean list; anything that is not an address is dropped.

    A display name is kept when one was given ("Dana <dana@x.com>"), so the
    recipient sees who the mail was meant for rather than a bare address.
    """

    raw_values = values if isinstance(values, (list, tuple)) else [values]
    addresses: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        name, address = parseaddr(text)
        address = address.strip().lower()
        if not ADDRESS_PATTERN.match(address) or address in seen:
            continue
        seen.add(address)
        addresses.append(formataddr((name.strip(), address)) if name.strip() else address)
        if len(addresses) >= limit:
            break
    return addresses


def bare_address(value: str) -> str:
    return parseaddr(str(value or ""))[1].strip().lower()


def build_raw_message(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    from_address: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """The RFC 822 message Gmail expects, base64url-encoded."""

    message = EmailMessage()
    if from_address:
        message["From"] = from_address
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    message.set_content(body_text)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


class GmailSender:
    """Send one message, new or as a reply, from a connected Gmail mailbox."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: int = GMAIL_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib_request.urlopen
        self.timeout_seconds = max(3, min(60, int(timeout_seconds)))

    def _request_json(self, url: str, access_token: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            raise GmailAuthorizationError(
                "Gmail access needs attention: no usable access token is saved. Connect Google again, then try once more."
            )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib_request.Request(url, headers=headers, method=method, data=data)
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8")) if raw else {}
        except urllib_error.HTTPError as exc:
            if exc.code == 403:
                # Reading works and sending does not: the grant is the
                # difference, and that is what the person has to hear.
                raise GmailSendPermissionError() from exc
            if exc.code == 401:
                raise GmailAuthorizationError(
                    "Gmail access needs attention: Google rejected the saved credential. Connect Google again, then try once more."
                ) from exc
            if exc.code == 404:
                raise GmailSummaryError(
                    "The message being replied to is not in this mailbox any more.",
                    code="gmail_message_not_found",
                ) from exc
            raise GmailSummaryError(
                "I couldn't send through Gmail just now. Try again in a moment.",
                code="gmail_provider_error",
            ) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise GmailSummaryError("I couldn't reach Gmail. Check the connection and try again.", code="gmail_network_error") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GmailSummaryError("I couldn't read Gmail's answer just now. Try again in a moment.", code="gmail_provider_error") from exc
        if not isinstance(payload, dict):
            raise GmailSummaryError("I couldn't read Gmail's answer just now. Try again in a moment.", code="gmail_provider_error")
        return payload

    def read_reply_target(self, access_token: str, message_id: str) -> dict[str, str]:
        """What a reply to one message needs: who to answer, the subject, the thread."""

        encoded = urllib_parse.quote(str(message_id or "").strip(), safe="")
        params = urllib_parse.urlencode([
            ("format", "metadata"),
            ("metadataHeaders", "Message-ID"),
            ("metadataHeaders", "Subject"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "Reply-To"),
            ("metadataHeaders", "References"),
        ])
        message = self._request_json(f"{GMAIL_MESSAGES_API_URL}/{encoded}?{params}", access_token)
        headers = {}
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        for header in payload.get("headers") or []:
            if isinstance(header, dict):
                headers[str(header.get("name") or "").lower()] = str(header.get("value") or "").strip()
        subject = headers.get("subject", "")
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        return {
            "threadId": str(message.get("threadId") or "").strip(),
            "messageId": headers.get("message-id", ""),
            "references": headers.get("references", ""),
            "replyTo": headers.get("reply-to") or headers.get("from", ""),
            "subject": subject,
        }

    def send(
        self,
        access_token: str,
        *,
        to: list[str] | None,
        subject: str,
        body_text: str,
        cc: list[str] | None = None,
        reply_to_message_id: str = "",
        from_address: str = "",
    ) -> dict[str, Any]:
        recipients = normalize_addresses(to or [])
        copies = normalize_addresses(cc or [])
        subject_text = " ".join(str(subject or "").split())[:MAX_SUBJECT_LENGTH]
        body = str(body_text or "").replace("\r\n", "\n").strip()[:MAX_BODY_LENGTH]
        thread_id = ""
        in_reply_to = ""
        references = ""
        if str(reply_to_message_id or "").strip():
            target = self.read_reply_target(access_token, reply_to_message_id)
            thread_id = target["threadId"]
            in_reply_to = target["messageId"]
            references = target["references"]
            if not recipients:
                recipients = normalize_addresses([target["replyTo"]])
            if not subject_text:
                subject_text = target["subject"][:MAX_SUBJECT_LENGTH]
        if not recipients:
            raise ValueError("At least one recipient address is needed.")
        if not subject_text:
            raise ValueError("A subject is needed.")
        if not body:
            raise ValueError("The message text is needed.")
        raw = build_raw_message(
            to=recipients,
            cc=copies,
            subject=subject_text,
            body_text=body,
            from_address=from_address,
            in_reply_to=in_reply_to,
            references=references,
        )
        request_body: dict[str, Any] = {"raw": raw}
        if thread_id:
            request_body["threadId"] = thread_id
        sent = self._request_json(GMAIL_SEND_API_URL, access_token, method="POST", body=request_body)
        return {
            "id": str(sent.get("id") or "").strip(),
            "threadId": str(sent.get("threadId") or thread_id).strip(),
            "to": recipients,
            "cc": copies,
            "subject": subject_text,
            "isReply": bool(in_reply_to or thread_id),
        }
