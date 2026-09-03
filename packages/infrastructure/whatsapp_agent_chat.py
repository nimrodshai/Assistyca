"""The Assistyca agent, reached by texting the Assistyca WhatsApp number.

The portal chat keeps its loop in the browser: the page holds the transcript,
calls /api/agent/turn, and dispatches whatever the turn decided. A WhatsApp
message has no browser behind it, so this module closes the same loop on the
server: it keeps the transcript in SQLite, calls the same agent endpoints over
loopback HTTP with a short-lived session token for the resolved owner, and
sends the reply back over WhatsApp through the Assistyca sender number.

Only messages from the account's own verified owner number reach this flow, and
only when they do not target the reply-approval flow -- that split happens in
the webhook handler, not here.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error as urllib_error
import urllib.parse as urllib_parse
import urllib.request as urllib_request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.infrastructure.notification_delivery import DEFAULT_WHATSAPP_API_VERSION
from packages.infrastructure.notification_delivery import normalize_email
from packages.infrastructure.notification_delivery import normalize_text
from packages.infrastructure.notification_delivery import parse_bool
from packages.infrastructure.notification_delivery import resolve_whatsapp_sender_access_token
from packages.infrastructure.notification_delivery import resolve_whatsapp_sender_phone_number_id
from packages.tools.whatsapp_reply_approval.server import send_whatsapp_message


AGENT_CHAT_HISTORY_LIMIT = 12
AGENT_CHAT_REPLY_MAX_LENGTH = 3500
AGENT_CHAT_RECORD_LIMIT = 60
AGENT_TURN_TIMEOUT_SECONDS = 120
AGENT_RUN_TIMEOUT_SECONDS = 300

_TIME_LOCAL_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# The owner's phone number is the one thing the webhook always knows about
# them, and its country code is a workable first guess at their clock. It is
# only a default: an explicit timezone saved on the conversation would win,
# and the agent asks rather than guesses when a time is ambiguous.
_COUNTRY_CODE_TIMEZONES: dict[str, str] = {
    "1": "America/New_York",
    "7": "Europe/Moscow",
    "20": "Africa/Cairo",
    "27": "Africa/Johannesburg",
    "30": "Europe/Athens",
    "31": "Europe/Amsterdam",
    "32": "Europe/Brussels",
    "33": "Europe/Paris",
    "34": "Europe/Madrid",
    "39": "Europe/Rome",
    "41": "Europe/Zurich",
    "43": "Europe/Vienna",
    "44": "Europe/London",
    "45": "Europe/Copenhagen",
    "46": "Europe/Stockholm",
    "47": "Europe/Oslo",
    "48": "Europe/Warsaw",
    "49": "Europe/Berlin",
    "52": "America/Mexico_City",
    "54": "America/Argentina/Buenos_Aires",
    "55": "America/Sao_Paulo",
    "60": "Asia/Kuala_Lumpur",
    "61": "Australia/Sydney",
    "62": "Asia/Jakarta",
    "63": "Asia/Manila",
    "64": "Pacific/Auckland",
    "65": "Asia/Singapore",
    "66": "Asia/Bangkok",
    "81": "Asia/Tokyo",
    "82": "Asia/Seoul",
    "84": "Asia/Ho_Chi_Minh",
    "86": "Asia/Shanghai",
    "90": "Europe/Istanbul",
    "91": "Asia/Kolkata",
    "92": "Asia/Karachi",
    "94": "Asia/Colombo",
    "98": "Asia/Tehran",
    "212": "Africa/Casablanca",
    "234": "Africa/Lagos",
    "254": "Africa/Nairobi",
    "351": "Europe/Lisbon",
    "353": "Europe/Dublin",
    "852": "Asia/Hong_Kong",
    "880": "Asia/Dhaka",
    "886": "Asia/Taipei",
    "961": "Asia/Beirut",
    "962": "Asia/Amman",
    "966": "Asia/Riyadh",
    "971": "Asia/Dubai",
    "972": "Asia/Jerusalem",
    "974": "Asia/Qatar",
    "977": "Asia/Kathmandu",
}


def whatsapp_agent_chat_enabled() -> bool:
    """Whether owner messages to the Assistyca number reach the agent at all."""

    return parse_bool(os.getenv("WHATSAPP_AGENT_CHAT_ENABLED"), True)


CLAIM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CLAIM_CODE_LENGTH = 6
CLAIM_CODE_TTL_SECONDS = 900
_CLAIM_CODE_RE = re.compile(rf"\b[{CLAIM_CODE_ALPHABET}]{{{CLAIM_CODE_LENGTH}}}\b", re.IGNORECASE)


def generate_whatsapp_claim_code() -> str:
    """A code short enough to type and free of characters people confuse."""

    return "".join(secrets.choice(CLAIM_CODE_ALPHABET) for _ in range(CLAIM_CODE_LENGTH))


def extract_whatsapp_claim_code(text: Any) -> str:
    """The claim code inside a message, wherever in the sentence it sits.

    A link fills the message with words around the code, and someone typing it
    by hand may add their own, so the code is looked for rather than expected
    to stand alone. Ordinary words can match this shape, which is why a code
    that no account ever issued is answered with silence rather than a reply.
    """

    match = _CLAIM_CODE_RE.search(str(text or ""))
    return match.group(0).upper() if match else ""


def resolve_assistyca_display_number() -> str:
    """The Assistyca number in the form a wa.me link needs, if configured."""

    return re.sub(r"\D+", "", normalize_text(os.getenv("ASSISTYCA_WHATSAPP_DISPLAY_NUMBER")))


def build_whatsapp_claim_link(code: str) -> str:
    """A tap-to-open WhatsApp link with the claim code already written out."""

    number = resolve_assistyca_display_number()
    normalized_code = normalize_text(code).upper()
    if not number or not normalized_code:
        return ""
    message = urllib_parse.quote(f"Assistyca code {normalized_code}")
    return f"https://wa.me/{number}?text={message}"


def send_assistyca_text(*, recipient_wa_id: str, text: str, api_version: str = DEFAULT_WHATSAPP_API_VERSION) -> str:
    """Send one plain message from the Assistyca number."""

    access_token = resolve_whatsapp_sender_access_token()
    phone_number_id = resolve_whatsapp_sender_phone_number_id()
    if access_token and phone_number_id:
        return send_whatsapp_message(
            access_token=access_token,
            phone_number_id=phone_number_id,
            api_version=api_version,
            recipient_wa_id=recipient_wa_id,
            message_text=text,
        )
    if parse_bool(os.getenv("WHATSAPP_ALLOW_MOCK_SEND")):
        return f"mock-{uuid.uuid4().hex}"
    raise WhatsAppAgentChatError(
        "Assistyca WhatsApp sending is not configured, so the agent cannot reply on this channel."
    )


SIGNUP_DEFAULT_DAILY_CAP = 50
SIGNUP_MAX_EMAIL_ATTEMPTS = 3
SIGNUP_REOPEN_AFTER_SECONDS = 86400


_EMAIL_IN_TEXT_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def find_email_in_text(text: Any) -> str:
    """The email address inside a chat message, if there is one.

    People answer "what's your email?" with a sentence, not a header, so this
    looks for the address wherever it sits rather than expecting the whole
    message to be one.
    """

    match = _EMAIL_IN_TEXT_RE.search(str(text or ""))
    return normalize_email(match.group(0).rstrip(".")) if match else ""


def whatsapp_signup_enabled() -> bool:
    """Whether a phone nobody knows can open an account by texting.

    On by default because bounding what one account can cost (the free trial)
    is what made an open door safe; this switch and the daily cap are for the
    day something unexpected points a crowd at the number.
    """

    return parse_bool(os.getenv("PORTAL_WHATSAPP_SIGNUP_ENABLED"), True)


def resolve_whatsapp_signup_daily_cap() -> int:
    raw = normalize_text(os.getenv("PORTAL_WHATSAPP_SIGNUP_DAILY_CAP"))
    if not raw:
        return SIGNUP_DEFAULT_DAILY_CAP
    try:
        return max(0, int(raw))
    except ValueError:
        return SIGNUP_DEFAULT_DAILY_CAP


def build_whatsapp_signup_link() -> str:
    """The one public link: tap it and WhatsApp opens on the Assistyca number."""

    number = resolve_assistyca_display_number()
    if not number:
        return ""
    return f"https://wa.me/{number}?text={urllib_parse.quote('Hi Assistyca')}"


SIGNUP_ASK_EMAIL_TEXT = (
    "Hi — I'm Assistyca, your assistant. What email should I set your account up with? "
    "You'll use it if you ever want to open things on the web."
)
SIGNUP_ASK_EMAIL_AGAIN_TEXT = (
    "That doesn't look like an email address. What email should I use for your account?"
)
SIGNUP_EMAIL_TAKEN_TEXT = (
    "That address already has an Assistyca account. Sign in at assistyca.com and get a code "
    "from Settings to link this phone to it."
)
SIGNUP_WELCOME_TEXT = (
    "You're set up. Ask me anything — I can go through your inbox, check your calendar, chase "
    "receipts, or remind you about things. What's on your plate?"
)


def normalize_whatsapp_number(value: Any) -> str:
    """Digits only, with the Israeli local 05x form written out in full."""

    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 10 and digits.startswith("05"):
        return f"972{digits[1:]}"
    return digits


def resolve_operator_whatsapp_numbers() -> dict[str, str]:
    """Phones that reach the agent directly, each mapped to its account.

    A client is recognized by the WhatsApp Business connection they saved, and
    whoever runs Assistyca has no such thing: their number *is* the Assistyca
    number, so there is no client connection to look them up by. Without this
    the people best placed to use the agent are the only ones who cannot, and
    inventing a fake client connection for them would route their own messages
    into the customer approval flow instead.

        ASSISTYCA_WHATSAPP_OWNER_NUMBERS="972507322341:owner@example.com"

    Several are allowed, separated by commas, so a second phone can be added
    for testing without disturbing the first.
    """

    raw = normalize_text(os.getenv("ASSISTYCA_WHATSAPP_OWNER_NUMBERS"))
    mapping: dict[str, str] = {}
    for entry in re.split(r"[,;\n]+", raw):
        piece = entry.strip()
        if not piece:
            continue
        parts = re.split(r"[:=]", piece, maxsplit=1)
        if len(parts) != 2:
            continue
        number = normalize_whatsapp_number(parts[0])
        email = normalize_email(parts[1])
        if number and email:
            mapping[number] = email
    return mapping


def infer_timezone_from_wa_id(wa_id: Any) -> str:
    """A default timezone from the phone number's country code, or UTC."""

    digits = re.sub(r"\D", "", str(wa_id or ""))
    for length in (3, 2, 1):
        prefix = digits[:length]
        zone = _COUNTRY_CODE_TIMEZONES.get(prefix)
        if zone:
            return zone
    return "UTC"


def format_agent_reply_for_whatsapp(text: Any) -> str:
    """Reshape a portal-flavoured reply into WhatsApp text.

    WhatsApp renders *bold* with single asterisks and shows markdown link
    syntax literally, so the portal's markdown habits are translated rather
    than stripped: the words and the URLs all survive, only the syntax moves.
    """

    reply = str(text or "").strip()
    if not reply:
        return ""

    # [label](url) -> label (url); an anchor with no real target keeps only
    # its words.
    def _replace_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target = match.group(2).strip()
        if not target or target.startswith("#"):
            return label
        return f"{label} ({target})"

    reply = re.sub(r"\[([^\]]+)\]\(([^)\s]*)\)", _replace_link, reply)
    reply = re.sub(r"\*\*([^*\n]+)\*\*", r"*\1*", reply)
    reply = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", reply, flags=re.MULTILINE)
    reply = re.sub(r"^\s*[-*]\s+", "• ", reply, flags=re.MULTILINE)
    reply = re.sub(r"\n{3,}", "\n\n", reply).strip()
    if len(reply) > AGENT_CHAT_REPLY_MAX_LENGTH:
        reply = reply[: AGENT_CHAT_REPLY_MAX_LENGTH - 1].rstrip() + "…"
    return reply


def resolve_scheduled_message_run_at(
    details: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """The exact UTC send time a timeLocal/datePolicy pair means, or "".

    This mirrors the browser's resolveAgentScheduledRunAt: the model never
    calculates runAt itself, so whichever side approves the proposal has to
    resolve the local wall-clock time against the timezone on the details.
    """

    time_local = normalize_text(details.get("timeLocal"))
    match = _TIME_LOCAL_RE.fullmatch(time_local)
    if not match:
        return ""

    timezone_name = normalize_text(details.get("timezone")) or "UTC"
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")

    current = now.astimezone(zone) if isinstance(now, datetime) else datetime.now(zone)
    hour = int(match.group(1))
    minute = int(match.group(2))
    date_policy = normalize_text(details.get("datePolicy")) or "next_occurrence"

    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if date_policy == "tomorrow":
        candidate = candidate + timedelta(days=1)
    elif date_policy == "next_occurrence" and candidate <= current:
        candidate = candidate + timedelta(days=1)

    return candidate.astimezone(timezone.utc).isoformat()


class WhatsAppAgentChatError(RuntimeError):
    """The conversation could not produce or deliver a reply."""


class WhatsAppAgentChat:
    """One owner message in, one WhatsApp reply out."""

    def __init__(
        self,
        *,
        database: Any,
        connection: dict[str, Any],
        base_url: str,
        session_token_factory: Callable[[str], str],
        api_version: str = DEFAULT_WHATSAPP_API_VERSION,
    ) -> None:
        self.database = database
        self.connection = connection if isinstance(connection, dict) else {}
        self.base_url = str(base_url or "").rstrip("/")
        self.session_token_factory = session_token_factory
        self.api_version = api_version
        self.user_id = int(self.connection.get("userId") or 0)
        self.email = normalize_email(self.connection.get("email"))
        self.owner_wa_id = normalize_text(self.connection.get("ownerWaId"))
        self.timezone_name = infer_timezone_from_wa_id(self.owner_wa_id)

    # -- loopback ---------------------------------------------------------

    def _api(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = AGENT_TURN_TIMEOUT_SECONDS,
    ) -> tuple[dict[str, Any], int]:
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.session_token_factory(self.email)}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8")), int(response.status)
        except urllib_error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                parsed = {}
            return parsed if isinstance(parsed, dict) else {}, int(exc.code)
        except (urllib_error.URLError, OSError, ValueError) as exc:
            raise WhatsAppAgentChatError(f"Agent loopback request failed: {exc}") from exc

    # -- context ----------------------------------------------------------

    def _build_tool_context(self) -> dict[str, Any]:
        """The same integration picture the browser sends, read from the DB."""

        whatsapp_ready = bool(
            normalize_text(self.connection.get("businessAccountId"))
            and normalize_text(self.connection.get("phoneNumberId"))
            and self.owner_wa_id
        )
        context: dict[str, Any] = {
            "whatsapp": {
                "ready": whatsapp_ready,
                "platformConnected": True,
                "connectionStatus": "connected" if whatsapp_ready else "partially_connected",
                "missingFields": [],
            },
        }

        mailboxes: list[dict[str, str]] = []
        try:
            platform_connections = self.database.list_platform_connections(self.email)
        except Exception:  # noqa: BLE001 - context is best-effort, the turn still runs
            platform_connections = []
        for record in platform_connections:
            platform = normalize_text(record.get("platform")).lower()
            status = normalize_text(record.get("connectionStatus")).lower() or "connected"
            entry = {
                "platformConnected": status in {"connected", "needs_attention"},
                "connectionStatus": status,
                "validationStatus": normalize_text(
                    (record.get("metadata") or {}).get("validationStatus")
                    if isinstance(record.get("metadata"), dict)
                    else ""
                ).lower() or "unknown",
            }
            if platform in {"calendar", "drive"}:
                context[platform] = entry
            elif platform == "email":
                metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
                provider = normalize_text(metadata.get("provider")).lower()
                slot = "outlook" if "outlook" in provider or "microsoft" in provider else "gmail"
                context[slot] = entry
                mailboxes.append({
                    "name": normalize_text(metadata.get("accountEmail") or metadata.get("displayName")),
                    "provider": "Outlook" if slot == "outlook" else "Gmail",
                })
        if mailboxes:
            context["mailboxes"] = mailboxes
        return context

    # -- outcome dispatch --------------------------------------------------

    def _hold_proposal(self, turn: dict[str, Any], user_message: str) -> None:
        proposal_type = normalize_text(turn.get("proposalType")).lower()
        changes = turn.get("changes") if isinstance(turn.get("changes"), dict) else {}
        proposal: dict[str, Any] = {
            "id": f"wa-{uuid.uuid4().hex[:12]}",
            "type": proposal_type,
            "revision": 1,
            "requestText": user_message,
            "summary": normalize_text(turn.get("reply"))[:500],
        }
        if proposal_type == "scheduled-message":
            proposal["details"] = {
                "channel": normalize_text(changes.get("channel")).lower() or "whatsapp",
                "recipientRef": "owner",
                "timeLocal": normalize_text(changes.get("timeLocal")),
                "datePolicy": normalize_text(changes.get("datePolicy")),
                "timezone": self.timezone_name,
                "messageText": normalize_text(changes.get("messageText")),
            }
        else:
            fields = changes.get("fields") if isinstance(changes.get("fields"), dict) else {}
            proposal["fields"] = fields
        self.database.save_whatsapp_agent_active_proposal(user_id=self.user_id, proposal=proposal)

    def _revise_proposal(self, turn: dict[str, Any], active_proposal: dict[str, Any]) -> None:
        changes = turn.get("changes") if isinstance(turn.get("changes"), dict) else {}
        proposal = dict(active_proposal)
        proposal["revision"] = int(proposal.get("revision") or 1) + 1
        if normalize_text(proposal.get("type")).lower() == "scheduled-message":
            details = dict(proposal.get("details") or {})
            for key in ("channel", "timeLocal", "datePolicy", "messageText"):
                if normalize_text(changes.get(key)):
                    details[key] = normalize_text(changes.get(key))
            proposal["details"] = details
        else:
            fields = dict(proposal.get("fields") or {})
            new_fields = changes.get("fields") if isinstance(changes.get("fields"), dict) else {}
            fields.update(new_fields)
            proposal["fields"] = fields
        self.database.save_whatsapp_agent_active_proposal(user_id=self.user_id, proposal=proposal)

    def _approve_proposal(self, turn: dict[str, Any], active_proposal: dict[str, Any]) -> str:
        proposal_type = normalize_text(active_proposal.get("type")).lower()
        if proposal_type != "scheduled-message":
            # The other proposal types still finish their setup in the portal;
            # saying anything else here would promise work this channel cannot
            # do yet.
            return (
                "I have this plan ready, but finishing this kind of setup still happens in your "
                "Assistyca portal. Open the chat there and it will be waiting under the same words."
            )

        details = active_proposal.get("details") if isinstance(active_proposal.get("details"), dict) else {}
        run_at = resolve_scheduled_message_run_at(details)
        message_text = normalize_text(details.get("messageText"))
        if not run_at:
            return "I still need an exact send time (for example 12:40) before I can schedule this."
        if not message_text:
            return "I still need the message text before I can schedule this."

        response, status = self._api(
            "POST",
            "/api/scheduled-actions",
            {
                "actionType": "send_message",
                "channel": "whatsapp",
                "recipientRef": normalize_text(details.get("recipientRef")) or "owner",
                "runAt": run_at,
                "timezone": normalize_text(details.get("timezone")) or self.timezone_name,
                "messageText": message_text,
                "source": "whatsapp_agent",
                "payload": {
                    "proposalId": normalize_text(active_proposal.get("id")),
                    "requestText": normalize_text(active_proposal.get("requestText")),
                    "messageText": message_text,
                },
            },
        )
        if status == 200 and response.get("ok"):
            self.database.save_whatsapp_agent_active_proposal(user_id=self.user_id, proposal=None)
            return normalize_text(turn.get("reply")) or "Done — it's scheduled."
        return (
            normalize_text(response.get("message"))
            or "I couldn't schedule that just now. Please try again in a moment."
        )

    def _answer_now(self, turn: dict[str, Any], user_message: str, history: list[dict[str, str]]) -> str:
        tasks = turn.get("tasks") if isinstance(turn.get("tasks"), list) else []
        if not tasks:
            single_type = normalize_text(turn.get("proposalType")).lower()
            changes = turn.get("changes") if isinstance(turn.get("changes"), dict) else {}
            if single_type:
                tasks = [{"proposalType": single_type, "changes": changes, "mode": "answer"}]

        lines: list[str] = []
        records: list[dict[str, Any]] = []
        figures: dict[str, Any] = {}
        for task in tasks[:3]:
            if not isinstance(task, dict):
                continue
            task_changes = task.get("changes") if isinstance(task.get("changes"), dict) else {}
            fields = task_changes.get("fields") if isinstance(task_changes.get("fields"), dict) else {}
            response, status = self._api(
                "POST",
                "/api/agent/proposals/run",
                {
                    "proposalType": normalize_text(task.get("proposalType")).lower(),
                    "mode": "answer",
                    "fields": fields,
                    "deliveryChannel": "portal",
                    "timezone": self.timezone_name,
                },
                timeout=AGENT_RUN_TIMEOUT_SECONDS,
            )
            if response.get("needsReceiptDecision"):
                questions = response.get("receiptQuestions") if isinstance(response.get("receiptQuestions"), list) else []
                first_question = ""
                for entry in questions:
                    first_question = normalize_text((entry or {}).get("question")) if isinstance(entry, dict) else ""
                    if first_question:
                        break
                decision_note = (
                    "Two receipts in there look alike, and telling them apart takes a decision "
                    "I can only collect in the portal chat for now."
                )
                lines.append(f"{first_question} {decision_note}".strip())
                continue
            line = normalize_text(
                response.get("answer") or response.get("message") or response.get("summary")
            )
            if status != 200 and not line:
                line = "One of those lookups failed just now."
            if line:
                lines.append(line)
            raw_records = response.get("answerRecords") if isinstance(response.get("answerRecords"), list) else []
            for record in raw_records:
                if isinstance(record, dict) and len(records) < AGENT_CHAT_RECORD_LIMIT:
                    records.append(record)
            availability = response.get("availability")
            if isinstance(availability, dict):
                figures.update(availability)

        computed = " ".join(lines).strip() or "I ran that, but it came back without anything to report."
        conversation = history + [{"role": "user", "text": user_message}]
        composed, status = self._api(
            "POST",
            "/api/agent/answer/compose",
            {
                "question": user_message,
                "answer": computed,
                "records": records,
                "figures": figures,
                "conversation": conversation[-8:],
                "timezone": self.timezone_name,
            },
        )
        if status == 200 and normalize_text(composed.get("answer")):
            return normalize_text(composed.get("answer"))
        return computed

    # -- sending -----------------------------------------------------------

    def _send_owner_text(self, reply_text: str) -> str:
        return send_assistyca_text(
            recipient_wa_id=self.owner_wa_id,
            text=reply_text,
            api_version=self.api_version,
        )

    # -- the whole loop ----------------------------------------------------

    def handle_message(self, message_text: Any, *, message_type: str = "text") -> dict[str, Any]:
        text = normalize_text(message_text)
        if self.user_id <= 0 or not self.email or not self.owner_wa_id:
            raise WhatsAppAgentChatError("The WhatsApp connection does not resolve to an active owner.")

        if not text or normalize_text(message_type).lower() not in {"", "text", "button", "interactive"}:
            reply = (
                "I can only read text messages on WhatsApp so far. "
                "Type what you need and I'll take it from there."
            )
            message_id = self._send_owner_text(reply)
            return {
                "type": "owner",
                "action": "agent_chat_reply",
                "outcome": "unsupported_message",
                "reply_text": reply,
                "message_id": message_id,
            }

        history = self.database.list_recent_whatsapp_agent_messages(
            user_id=self.user_id,
            limit=AGENT_CHAT_HISTORY_LIMIT,
        )
        conversation = [{"role": item["role"], "text": item["text"]} for item in history]
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text=text)
        active_proposal = self.database.get_whatsapp_agent_active_proposal(user_id=self.user_id)

        turn_payload: dict[str, Any] = {
            "userMessage": text,
            "conversation": conversation,
            "timezone": self.timezone_name,
            "channel": "whatsapp",
            "toolContext": self._build_tool_context(),
        }
        if active_proposal:
            turn_payload["activeProposal"] = active_proposal

        turn, status = self._api("POST", "/api/agent/turn", turn_payload)
        outcome = normalize_text(turn.get("outcome")).lower()
        if status != 200 or not turn.get("ok"):
            outcome = "error"
            reply = (
                normalize_text(turn.get("message"))
                or "I'm having trouble thinking that through right now. Please try again in a moment."
            )
        elif outcome == "proposal":
            self._hold_proposal(turn, text)
            reply = normalize_text(turn.get("reply"))
        elif outcome == "revise_proposal" and active_proposal:
            self._revise_proposal(turn, active_proposal)
            reply = normalize_text(turn.get("reply"))
        elif outcome == "approve_proposal" and active_proposal:
            reply = self._approve_proposal(turn, active_proposal)
        elif outcome == "reject_proposal":
            self.database.save_whatsapp_agent_active_proposal(user_id=self.user_id, proposal=None)
            reply = normalize_text(turn.get("reply")) or "Okay, I dropped that plan."
        elif outcome == "answer_now":
            reply = self._answer_now(turn, text, conversation)
        else:
            reply = normalize_text(turn.get("reply"))

        reply = format_agent_reply_for_whatsapp(reply) or (
            "I read that, but I could not put an answer together. Please try phrasing it another way."
        )
        message_id = self._send_owner_text(reply)
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="assistant", text=reply)
        return {
            "type": "owner",
            "action": "agent_chat_reply",
            "outcome": outcome or "message",
            "reply_text": reply,
            "message_id": message_id,
        }


__all__ = [
    "AGENT_CHAT_HISTORY_LIMIT",
    "CLAIM_CODE_TTL_SECONDS",
    "WhatsAppAgentChat",
    "WhatsAppAgentChatError",
    "build_whatsapp_claim_link",
    "build_whatsapp_signup_link",
    "extract_whatsapp_claim_code",
    "find_email_in_text",
    "format_agent_reply_for_whatsapp",
    "generate_whatsapp_claim_code",
    "resolve_assistyca_display_number",
    "resolve_whatsapp_signup_daily_cap",
    "send_assistyca_text",
    "infer_timezone_from_wa_id",
    "normalize_whatsapp_number",
    "resolve_operator_whatsapp_numbers",
    "resolve_scheduled_message_run_at",
    "whatsapp_agent_chat_enabled",
    "whatsapp_signup_enabled",
]
