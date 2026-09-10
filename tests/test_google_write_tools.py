"""Writing to Google: sending from Gmail, adding to and changing the calendar.

What these prove: the grant is asked for beside the read grant and a row
remembers whether it got it; a tool that writes is offered only when it did;
every write waits for the person's yes and the question names exactly what
will go out; and the endpoints behind the tools send and write only through
the mailbox and calendar the account chose.
"""

from __future__ import annotations

import base64
import email
import json
import sys
import tempfile
import threading
import unittest
from email import policy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import run_agent_loop
from packages.infrastructure.agent_loop import tool_definitions
from packages.infrastructure.agent_proposals import connected_sources
from packages.infrastructure.agent_proposals import normalize_agent_tool_context
from packages.infrastructure.calendar_summary import describe_calendar_records
from packages.infrastructure.calendar_write import CALENDAR_WRITE_OAUTH_SCOPE
from packages.infrastructure.calendar_write import CalendarWritePermissionError
from packages.infrastructure.calendar_write import CalendarWriter
from packages.infrastructure.calendar_write import build_event_times
from packages.infrastructure.gmail_send import GMAIL_SEND_OAUTH_SCOPE
from packages.infrastructure.gmail_send import GmailSendPermissionError
from packages.infrastructure.gmail_send import GmailSender
from packages.infrastructure.gmail_send import normalize_addresses
from packages.infrastructure.portal_auth.server import GOOGLE_CALENDAR_LIST_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_CALENDAR_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_GMAIL_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import PortalAuthHandler
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import google_connection_write_access

SERVER = "packages.infrastructure.portal_auth.server"


# -- fakes ---------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict | None, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None


def _http_error(url: str, code: int) -> urllib_error.HTTPError:
    return urllib_error.HTTPError(url, code, "nope", {}, BytesIO(b"{}"))


class _Opener:
    """Answers each request from a script and remembers what was asked."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.requests: list[urllib_request.Request] = []

    def __call__(self, request: urllib_request.Request, timeout: int = 0) -> _FakeResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _FakeResponse(answer)


class FakeApi:
    def __init__(self, responses: dict[str, tuple[dict, int]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, payload: dict | None = None, **kwargs) -> tuple[dict, int]:
        self.calls.append((method, path, payload))
        return self.responses.get(path, ({"ok": True}, 200))


def _call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


def _model_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = list(items)
    text = ""
    if reply is not None:
        text = json.dumps({"reply": "", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, **reply})
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": [{"type": "reasoning", "summary": []}, *outputs]}, input_tokens=100, output_tokens=20)


class ScriptedModel:
    def __init__(self, rounds: list[SimpleNamespace]) -> None:
        self.rounds = list(rounds)
        self.inputs: list[list[dict]] = []

    def __call__(self, input_items: list[dict], tools: list[dict]) -> SimpleNamespace:
        self.inputs.append(list(input_items))
        return self.rounds.pop(0)


def _tool_context(*, gmail: bool | None = None, calendar: bool | None = None, mailboxes: list[dict] | None = None) -> dict:
    """gmail/calendar: None is not connected, False is read-only, True can write."""

    context: dict = {}
    if gmail is not None:
        context["gmail"] = {"platformConnected": True, "connectionStatus": "connected", "writeAccess": gmail}
    if calendar is not None:
        context["calendar"] = {"platformConnected": True, "connectionStatus": "connected", "writeAccess": calendar}
    if mailboxes:
        context["mailboxes"] = mailboxes
    return context


def _context(api: FakeApi | None = None, **sources) -> LoopContext:
    return LoopContext(
        api=api or FakeApi(), database=SimpleNamespace(), email="owner@example.com", user_id=1,
        timezone_name="Asia/Jerusalem", tool_context=_tool_context(**sources), channel="whatsapp",
    )


# -- gmail_send ----------------------------------------------------------------


class GmailSenderTests(unittest.TestCase):
    def test_addresses_are_cleaned_named_and_deduplicated(self) -> None:
        addresses = normalize_addresses(["Dana <Dana@Example.com>", "dana@example.com", "not an address", "", "x@y.z"])
        self.assertEqual(addresses, ["Dana <dana@example.com>", "x@y.z"])

    def test_a_new_email_is_posted_as_one_raw_message(self) -> None:
        opener = _Opener([{"id": "m1", "threadId": "t1"}])
        sent = GmailSender(opener=opener).send(
            "tok", to=["dana@example.com"], cc=["Lee <lee@example.com>"], subject="Quote", body_text="Hi Dana,\n\nHere it is.",
            from_address="owner@gmail.com",
        )
        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertTrue(request.full_url.endswith("/users/me/messages/send"))
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("threadId", body)
        raw = body["raw"]
        message = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=policy.default)
        self.assertEqual(message["To"], "dana@example.com")
        self.assertEqual(message["Cc"], "Lee <lee@example.com>")
        self.assertEqual(message["From"], "owner@gmail.com")
        self.assertEqual(message["Subject"], "Quote")
        self.assertIn("Here it is.", message.get_content())
        self.assertEqual(sent["to"], ["dana@example.com"])
        self.assertFalse(sent["isReply"])

    def test_a_reply_reads_the_original_and_lands_in_its_thread(self) -> None:
        original = {
            "threadId": "t9",
            "payload": {"headers": [
                {"name": "Message-ID", "value": "<abc@mail.example>"},
                {"name": "Subject", "value": "Invoice 12"},
                {"name": "From", "value": "Dana <dana@example.com>"},
                {"name": "References", "value": "<first@mail.example>"},
            ]},
        }
        opener = _Opener([original, {"id": "m2", "threadId": "t9"}])
        sent = GmailSender(opener=opener).send("tok", to=[], subject="", body_text="Paid today.", reply_to_message_id="orig1")
        self.assertEqual(opener.requests[0].get_method(), "GET")
        self.assertIn("/users/me/messages/orig1?", opener.requests[0].full_url)
        body = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(body["threadId"], "t9")
        raw = body["raw"]
        message = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=policy.default)
        self.assertEqual(message["To"], "Dana <dana@example.com>")
        self.assertEqual(message["Subject"], "Re: Invoice 12")
        self.assertEqual(message["In-Reply-To"], "<abc@mail.example>")
        self.assertEqual(message["References"], "<first@mail.example> <abc@mail.example>")
        self.assertTrue(sent["isReply"])

    def test_a_forbidden_answer_names_the_missing_permission(self) -> None:
        opener = _Opener([_http_error("send", 403)])
        with self.assertRaises(GmailSendPermissionError) as raised:
            GmailSender(opener=opener).send("tok", to=["dana@example.com"], subject="x", body_text="y")
        self.assertEqual(raised.exception.code, "gmail_send_permission_required")
        self.assertIn("allow sending", str(raised.exception))

    def test_an_email_with_nobody_to_send_to_is_refused_before_google_is_asked(self) -> None:
        opener = _Opener([])
        with self.assertRaises(ValueError):
            GmailSender(opener=opener).send("tok", to=["nonsense"], subject="x", body_text="y")
        self.assertEqual(opener.requests, [])


# -- calendar_write ------------------------------------------------------------


class CalendarWriterTests(unittest.TestCase):
    def test_times_default_to_an_hour_and_no_time_means_all_day(self) -> None:
        timed = build_event_times(date_text="2026-09-10", start_time="10:00", timezone_name="Asia/Jerusalem")
        self.assertEqual(timed["start"], {"dateTime": "2026-09-10T10:00:00+03:00", "timeZone": "Asia/Jerusalem"})
        self.assertEqual(timed["end"]["dateTime"], "2026-09-10T11:00:00+03:00")
        all_day = build_event_times(date_text="2026-09-10")
        self.assertEqual(all_day, {"start": {"date": "2026-09-10"}, "end": {"date": "2026-09-11"}, "allDay": True})
        with self.assertRaises(ValueError):
            build_event_times(date_text="next tuesday")
        with self.assertRaises(ValueError):
            build_event_times(date_text="2026-09-10", start_time="11:00", end_time="10:00")

    def test_creating_posts_the_event_and_tells_the_guests(self) -> None:
        created = {
            "id": "ev1", "summary": "Dentist", "htmlLink": "https://calendar.google.com/x",
            "start": {"dateTime": "2026-09-10T10:00:00+03:00"}, "end": {"dateTime": "2026-09-10T11:00:00+03:00"},
            "attendees": [{"email": "dana@example.com"}],
        }
        opener = _Opener([created])
        event = CalendarWriter(opener=opener).create_event(
            "tok", calendar_id="work@group.calendar.google.com", title="Dentist", date_text="2026-09-10", start_time="10:00",
            timezone_name="Asia/Jerusalem", attendees=["Dana <dana@example.com>"],
        )
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn("/calendars/work%40group.calendar.google.com/events?sendUpdates=all", request.full_url)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["summary"], "Dentist")
        self.assertEqual(body["attendees"], [{"email": "dana@example.com"}])
        self.assertEqual(body["start"]["timeZone"], "Asia/Jerusalem")
        self.assertEqual(event["eventId"], "ev1")
        self.assertEqual(event["calendarId"], "work@group.calendar.google.com")
        self.assertEqual(event["link"], "https://calendar.google.com/x")
        self.assertIn("10:00", event["when"])

    def test_moving_the_clock_without_a_day_reads_the_day_first(self) -> None:
        current = {"id": "ev1", "start": {"dateTime": "2026-09-10T10:00:00+03:00"}, "end": {"dateTime": "2026-09-10T11:00:00+03:00"}}
        moved = {**current, "summary": "Dentist", "start": {"dateTime": "2026-09-10T16:00:00+03:00"}, "end": {"dateTime": "2026-09-10T17:00:00+03:00"}}
        opener = _Opener([current, moved])
        event = CalendarWriter(opener=opener).update_event("tok", calendar_id="primary", event_id="ev1", start_time="16:00", timezone_name="Asia/Jerusalem")
        self.assertEqual([r.get_method() for r in opener.requests], ["GET", "PATCH"])
        body = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(body["start"]["dateTime"], "2026-09-10T16:00:00+03:00")
        self.assertEqual(body["end"]["dateTime"], "2026-09-10T17:00:00+03:00")
        self.assertIn("4:00 PM", event["when"])

    def test_cancelling_deletes_and_a_forbidden_answer_names_the_permission(self) -> None:
        opener = _Opener([None])
        result = CalendarWriter(opener=opener).cancel_event("tok", calendar_id="primary", event_id="ev1")
        self.assertEqual(opener.requests[0].get_method(), "DELETE")
        self.assertTrue(result["cancelled"])
        with self.assertRaises(CalendarWritePermissionError) as raised:
            CalendarWriter(opener=_Opener([_http_error("ev", 403)])).cancel_event("tok", calendar_id="primary", event_id="ev1")
        self.assertEqual(raised.exception.code, "calendar_write_permission_required")

    def test_read_records_now_carry_what_a_change_needs(self) -> None:
        from datetime import datetime

        records = describe_calendar_records([{"id": "ev1", "calendarId": "primary", "title": "Standup", "start": datetime(2026, 9, 10, 9, 0)}])
        self.assertEqual(records[0]["eventId"], "ev1")
        self.assertEqual(records[0]["calendarId"], "primary")


# -- the tools -----------------------------------------------------------------


class WriteToolAvailabilityTests(unittest.TestCase):
    def test_write_access_is_a_source_of_its_own(self) -> None:
        context = normalize_agent_tool_context({"gmail": {"platformConnected": True, "writeAccess": True}, "calendar": {"platformConnected": True}})
        self.assertEqual(connected_sources(context), {"mailbox", "calendar", "gmail_send"})
        self.assertNotIn("writeAccess", context["calendar"])

    def test_a_read_only_connection_leaves_the_write_tools_unavailable_with_the_way_round_it(self) -> None:
        by_name = {tool["name"]: tool for tool in tool_definitions(_tool_context(gmail=False, calendar=False))}
        self.assertIn("UNAVAILABLE RIGHT NOW", by_name["send_email"]["description"])
        self.assertIn("connect_link", by_name["send_email"]["description"])
        self.assertIn("UNAVAILABLE RIGHT NOW", by_name["create_calendar_event"]["description"])
        self.assertIn("UNAVAILABLE RIGHT NOW", by_name["update_calendar_event"]["description"])
        self.assertNotIn("UNAVAILABLE", by_name["read_inbox"]["description"])

        granted = {tool["name"]: tool for tool in tool_definitions(_tool_context(gmail=True, calendar=True))}
        for name in ("send_email", "create_calendar_event", "update_calendar_event"):
            self.assertNotIn("UNAVAILABLE", granted[name]["description"])
            self.assertIn("Needs the person's yes", granted[name]["description"])
            self.assertTrue(granted[name]["strict"])


class SendEmailToolTests(unittest.TestCase):
    def test_the_turn_pauses_with_the_email_spelled_out_and_a_yes_sends_it(self) -> None:
        api = FakeApi({"/api/agent/email/send": ({"ok": True, "mailbox": "owner@gmail.com", "sent": {"to": ["dana@example.com"], "cc": [], "subject": "Quote", "isReply": False}}, 200)})
        model = ScriptedModel([
            _model_round(_call("send_email", "c1", to=["dana@example.com"], cc=[], subject="Quote", body="Hi Dana, the quote is 1,200 ILS. Nimrod", reply_to_message_id=None, mailbox=None)),
            _model_round(reply={"reply": "Send it?"}),
        ])
        result = run_agent_loop(context=_context(api, gmail=True), call_model=model, user_message="email dana the quote", conversation=[], today="2026-09-08")

        # Only the check ran; nothing was sent.
        self.assertEqual([(m, p, (b or {}).get("check")) for m, p, b in api.calls], [("POST", "/api/agent/email/send", True)])
        self.assertEqual(result.pending_confirmation["tool"], "send_email")
        asked = json.loads(model.inputs[1][-1]["output"])
        self.assertEqual(asked["error"]["code"], "confirmation_required")
        self.assertIn("send an email to dana@example.com with the subject 'Quote'", asked["error"]["whatHappened"])
        self.assertIn("the quote is 1,200 ILS", asked["error"]["whatHappened"])

        model = ScriptedModel([_model_round(reply={"reply": "Sent.", "claimsCompleted": ["send_email"]})])
        resumed = run_agent_loop(
            context=_context(api, gmail=True), call_model=model, user_message="yes", conversation=[], today="2026-09-08",
            confirmed_call=result.pending_confirmation,
        )
        sent_call = api.calls[-1]
        self.assertEqual(sent_call[:2], ("POST", "/api/agent/email/send"))
        self.assertNotIn("check", sent_call[2])
        self.assertEqual(sent_call[2]["to"], ["dana@example.com"])
        self.assertEqual(resumed.completed, ["send_email"])
        self.assertIn('"confirmedAction"', model.inputs[0][0]["content"])

    def test_a_reply_names_the_thread_and_the_only_gmail_mailbox(self) -> None:
        api = FakeApi()
        context = _context(api, gmail=True, mailboxes=[{"name": "owner@gmail.com", "provider": "Gmail"}, {"name": "o@outlook.com", "provider": "Outlook"}])
        tool = TOOLS_BY_NAME["send_email"]
        args = {"to": [], "cc": [], "subject": None, "body": "Paid today, thanks.", "reply_to_message_id": "m77", "mailbox": None}
        self.assertIsNone(tool.preflight(context, args))
        from packages.infrastructure.agent_loop import _describe_call

        described = _describe_call(context, tool, args)
        self.assertIn("reply by email to the sender", described)
        self.assertIn("from owner@gmail.com", described)
        self.assertEqual(api.calls[0][2]["replyToMessageId"], "m77")

    def test_an_email_nobody_can_receive_is_never_asked_about(self) -> None:
        api = FakeApi()
        tool = TOOLS_BY_NAME["send_email"]
        problem = tool.preflight(_context(api, gmail=True), {"to": ["dana"], "cc": [], "subject": "x", "body": "y", "reply_to_message_id": None, "mailbox": None})
        self.assertEqual(problem["error"]["code"], "choice_required")
        self.assertEqual(api.calls, [])

    def test_two_mailboxes_that_can_send_become_a_question_not_a_guess(self) -> None:
        api = FakeApi({"/api/agent/email/send": ({"ok": False, "error": "mailbox_choice_required", "message": "Which one?", "mailboxes": ["a@gmail.com", "b@gmail.com"]}, 409)})
        problem = TOOLS_BY_NAME["send_email"].preflight(_context(api, gmail=True), {"to": ["dana@example.com"], "cc": [], "subject": "x", "body": "y", "reply_to_message_id": None, "mailbox": None})
        self.assertEqual(problem["error"]["code"], "choice_required")
        self.assertEqual(problem["error"]["mailboxes"], ["a@gmail.com", "b@gmail.com"])

    def test_a_mailbox_that_lost_the_grant_is_reported_as_not_connected_for_sending(self) -> None:
        api = FakeApi({"/api/agent/email/send": ({"ok": False, "error": "gmail_send_permission_required", "message": "Connect Google again and allow sending."}, 409)})
        result = TOOLS_BY_NAME["send_email"].run(_context(api, gmail=True), {"to": ["dana@example.com"], "cc": [], "subject": "x", "body": "y"})
        self.assertEqual(result["error"]["code"], "source_not_connected")
        self.assertEqual(result["error"]["source"], "gmail_send")


class CalendarWriteToolTests(unittest.TestCase):
    def test_a_meeting_is_described_in_full_before_the_yes(self) -> None:
        api = FakeApi({"/api/agent/calendar/events": ({"ok": True, "checked": True, "calendar": "Work"}, 200)})
        context = _context(api, calendar=True)
        tool = TOOLS_BY_NAME["create_calendar_event"]
        args = {"title": "Dentist", "date": "2026-09-10", "start_time": "10:00", "end_time": None, "calendar": "Work", "location": "Herzliya", "description": None, "attendees": ["dana@example.com"]}
        self.assertIsNone(tool.preflight(context, args))
        from packages.infrastructure.agent_loop import _describe_call

        self.assertEqual(
            _describe_call(context, tool, args),
            "add 'Dentist' on 2026-09-10 from 10:00 to 11:00 at Herzliya to the Work calendar, inviting dana@example.com",
        )
        self.assertEqual(api.calls[0][2]["action"], "create")
        self.assertEqual(api.calls[0][2]["timezone"], "Asia/Jerusalem")

    def test_a_day_the_model_did_not_resolve_is_sent_back_for_a_date(self) -> None:
        api = FakeApi()
        problem = TOOLS_BY_NAME["create_calendar_event"].preflight(_context(api, calendar=True), {"title": "Dentist", "date": "Thursday", "start_time": "10:00", "end_time": None, "calendar": None, "location": None, "description": None, "attendees": []})
        self.assertEqual(problem["error"]["code"], "choice_required")
        self.assertIn("YYYY-MM-DD", problem["error"]["whatHappened"])
        self.assertEqual(api.calls, [])

    def test_a_confirmed_creation_returns_the_event_as_a_record(self) -> None:
        event = {"kind": "meeting", "eventId": "ev1", "calendarId": "primary", "when": "Thu, Sep 10 · 10:00 AM–11:00 AM", "title": "Dentist", "link": "https://calendar.google.com/x"}
        api = FakeApi({"/api/agent/calendar/events": ({"ok": True, "event": event, "calendar": "My calendar"}, 200)})
        result = TOOLS_BY_NAME["create_calendar_event"].run(_context(api, calendar=True), {"title": "Dentist", "date": "2026-09-10", "start_time": "10:00", "attendees": []})
        self.assertTrue(result["ok"])
        self.assertEqual(result["event"]["eventId"], "ev1")
        self.assertEqual(result["calendar"], "My calendar")

    def test_cancelling_and_moving_are_named_for_the_question(self) -> None:
        api = FakeApi({"/api/agent/calendar/events": ({"ok": True, "checked": True, "calendar": "My calendar"}, 200)})
        context = _context(api, calendar=True)
        tool = TOOLS_BY_NAME["update_calendar_event"]
        from packages.infrastructure.agent_loop import _describe_call

        cancel = {"event_id": "ev1", "calendar_id": "primary", "cancel": True, "title": None, "date": None, "start_time": None, "end_time": None, "location": None, "description": None}
        self.assertIsNone(tool.preflight(context, cancel))
        self.assertIn("cancel that meeting", _describe_call(context, tool, cancel))
        self.assertEqual(api.calls[-1][2]["action"], "cancel")

        move = {**cancel, "cancel": False, "start_time": "16:00"}
        self.assertIsNone(tool.preflight(context, move))
        self.assertEqual(_describe_call(context, tool, move), "change that meeting: move it to 16:00 the same day")
        self.assertEqual(api.calls[-1][2]["action"], "update")

        nothing = {**cancel, "cancel": False}
        self.assertEqual(tool.preflight(context, nothing)["error"]["code"], "choice_required")
        unknown = {**move, "event_id": ""}
        self.assertIn("eventId", tool.preflight(context, unknown)["error"]["whatHappened"])


# -- the server ----------------------------------------------------------------


class GoogleWriteScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = PortalAuthHandler.__new__(PortalAuthHandler)

    def test_connecting_asks_for_writing_beside_reading(self) -> None:
        text = self.handler._google_oauth_scope_text(("gmail", "calendar", "drive"))
        scopes = text.split()
        self.assertIn(GOOGLE_GMAIL_OAUTH_SCOPE, scopes)
        self.assertIn(GMAIL_SEND_OAUTH_SCOPE, scopes)
        self.assertIn(CALENDAR_WRITE_OAUTH_SCOPE, scopes)
        self.assertIn(GOOGLE_CALENDAR_LIST_OAUTH_SCOPE, scopes)
        # calendar.events already covers reading, so the read scope is not
        # put on Google's consent screen a second time.
        self.assertNotIn(GOOGLE_CALENDAR_OAUTH_SCOPE, scopes)
        self.assertIn("drive.readonly", text)
        self.assertNotIn("drive.file", text)

    def test_a_calendar_granted_only_the_write_scope_still_connects(self) -> None:
        granted = self.handler._granted_google_oauth_scope_ids(f"{CALENDAR_WRITE_OAUTH_SCOPE} {GOOGLE_GMAIL_OAUTH_SCOPE}", ("calendar", "gmail"))
        self.assertEqual(granted, ("calendar", "gmail"))
        # An older grant, read-only, still connects the calendar too.
        self.assertEqual(self.handler._granted_google_oauth_scope_ids(GOOGLE_CALENDAR_OAUTH_SCOPE, ("calendar",)), ("calendar",))

    def test_a_row_says_whether_it_can_write_from_the_grant_it_got(self) -> None:
        self.assertTrue(google_connection_write_access({"metadata": {"grantedScope": f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}"}}, "gmail"))
        self.assertFalse(google_connection_write_access({"metadata": {"grantedScope": GOOGLE_GMAIL_OAUTH_SCOPE}}, "gmail"))
        self.assertFalse(google_connection_write_access({"metadata": {"grantedScope": GMAIL_SEND_OAUTH_SCOPE}}, "calendar"))
        # Drive has no write grant to check for.
        self.assertFalse(google_connection_write_access({"metadata": {"grantedScope": "https://www.googleapis.com/auth/drive"}}, "drive"))
        self.assertFalse(google_connection_write_access({"metadata": {}}, "gmail"))


class GoogleWriteEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.server = create_server(
            "127.0.0.1", 0, root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=Path(self.temp_dir.name) / "agent_outputs",
            ),
        )
        if self.server.credential_vault is None:
            self.server.server_close()
            self.temp_dir.cleanup()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _connect(self, platform: str, *, granted_scope: str, address: str = "", provider: str = "") -> None:
        vault = self.server.credential_vault
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform=platform,
            provider=provider or ("google_gmail" if platform == "email" else "google_calendar"),
            auth_type="oauth",
            secret_ciphertext=vault.encrypt(json.dumps({"type": "google_refresh_token", "provider": "google", "refreshToken": "rt"})),  # type: ignore[union-attr]
            secret_hint="Google OAuth",
            key_version=vault.key_version,  # type: ignore[union-attr]
            account_address=address,
            metadata={"provider": provider or ("google_gmail" if platform == "email" else "google_calendar"), "grantedScope": granted_scope, "validationStatus": "verified"},
            connection_status="connected",
        )

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.session_token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return int(exc.code), json.loads(exc.read().decode("utf-8"))

    def test_sending_needs_a_gmail_mailbox_with_the_send_grant(self) -> None:
        status, body = self._post("/api/agent/email/send", {"to": ["dana@example.com"], "subject": "x", "body": "y"})
        self.assertEqual((status, body["error"]), (409, "gmail_not_connected"))

        self._connect("email", granted_scope=GOOGLE_GMAIL_OAUTH_SCOPE, address="owner@gmail.com")
        status, body = self._post("/api/agent/email/send", {"to": ["dana@example.com"], "subject": "x", "body": "y"})
        self.assertEqual((status, body["error"]), (409, "gmail_send_permission_required"))
        self.assertIn("allow sending", body["message"])

    def test_a_check_names_the_mailbox_and_sends_nothing(self) -> None:
        self._connect("email", granted_scope=f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}", address="owner@gmail.com")
        with mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._post("/api/agent/email/send", {"to": ["dana@example.com"], "subject": "x", "body": "y", "check": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["mailbox"], "owner@gmail.com")
        send.assert_not_called()

    def test_sending_goes_through_the_chosen_mailbox_with_a_fresh_token(self) -> None:
        self._connect("email", granted_scope=f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}", address="owner@gmail.com")
        self._connect("email", granted_scope=f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}", address="shop@gmail.com")
        status, body = self._post("/api/agent/email/send", {"to": ["dana@example.com"], "subject": "x", "body": "y"})
        self.assertEqual((status, body["error"]), (409, "mailbox_choice_required"))
        self.assertEqual(sorted(body["mailboxes"]), ["owner@gmail.com", "shop@gmail.com"])

        sent = {"id": "m1", "threadId": "t1", "to": ["dana@example.com"], "cc": [], "subject": "x", "isReply": False}
        with mock.patch(f"{SERVER}.PortalAuthHandler._refresh_google_access_token", return_value="fresh-token") as refresh, \
                mock.patch(f"{SERVER}.GmailSender.send", return_value=sent) as send:
            status, body = self._post("/api/agent/email/send", {"to": ["dana@example.com"], "subject": "x", "body": "y", "mailboxAccount": "shop@gmail.com"})
        self.assertEqual(status, 200)
        self.assertEqual(body["mailbox"], "shop@gmail.com")
        self.assertEqual(refresh.call_args.args[0], "rt")
        self.assertEqual(send.call_args.args[0], "fresh-token")
        self.assertEqual(send.call_args.kwargs["from_address"], "shop@gmail.com")
        self.assertNotIn("rt", json.dumps(body))

    def test_a_calendar_write_needs_the_grant_and_goes_to_the_chosen_calendar(self) -> None:
        status, body = self._post("/api/agent/calendar/events", {"title": "Dentist", "date": "2026-09-10"})
        self.assertEqual((status, body["error"]), (409, "calendar_setup_required"))

        self._connect("calendar", granted_scope=f"{GOOGLE_CALENDAR_OAUTH_SCOPE} {GOOGLE_CALENDAR_LIST_OAUTH_SCOPE}")
        status, body = self._post("/api/agent/calendar/events", {"title": "Dentist", "date": "2026-09-10"})
        self.assertEqual((status, body["error"]), (409, "calendar_write_permission_required"))

        self.server.database.update_platform_connection_status(
            "owner@example.com", platform="calendar", connection_status="connected",
            metadata_updates={
                "grantedScope": f"{CALENDAR_WRITE_OAUTH_SCOPE} {GOOGLE_CALENDAR_LIST_OAUTH_SCOPE}",
                "availableCalendars": [{"id": "primary", "label": "Nimrod"}, {"id": "work@group.calendar.google.com", "label": "Work"}],
                "selectedCalendars": [{"id": "primary", "label": "Nimrod"}, {"id": "work@group.calendar.google.com", "label": "Work"}],
            },
        )
        # Two calendars are read, so which one this goes in is a question.
        status, body = self._post("/api/agent/calendar/events", {"title": "Dentist", "date": "2026-09-10", "check": True})
        self.assertEqual((status, body["error"]), (409, "calendar_choice_required"))
        self.assertEqual(body["calendars"], ["Nimrod", "Work"])
        status, body = self._post("/api/agent/calendar/events", {"title": "Dentist", "date": "2026-09-10", "calendar": "work", "check": True})
        self.assertEqual(status, 200)
        self.assertEqual((body["calendar"], body["calendarId"]), ("Work", "work@group.calendar.google.com"))
        status, body = self._post("/api/agent/calendar/events", {"title": "Dentist", "date": "2026-09-10", "calendar": "Family", "check": True})
        self.assertEqual((status, body["error"]), (409, "calendar_not_found"))

        event = {"kind": "meeting", "eventId": "ev1", "calendarId": "work@group.calendar.google.com", "title": "Dentist"}
        with mock.patch(f"{SERVER}.PortalAuthHandler._refresh_google_access_token", return_value="fresh-token"), \
                mock.patch(f"{SERVER}.CalendarWriter.create_event", return_value=event) as create:
            status, body = self._post("/api/agent/calendar/events", {
                "title": "Dentist", "date": "2026-09-10", "startTime": "10:00", "calendar": "Work", "timezone": "Asia/Jerusalem",
                "attendees": ["dana@example.com"],
            })
        self.assertEqual(status, 200)
        self.assertEqual(body["event"]["eventId"], "ev1")
        self.assertEqual(create.call_args.args[0], "fresh-token")
        self.assertEqual(create.call_args.kwargs["calendar_id"], "work@group.calendar.google.com")
        self.assertEqual(create.call_args.kwargs["attendees"], ["dana@example.com"])
        self.assertEqual(create.call_args.kwargs["timezone_name"], "Asia/Jerusalem")

        with mock.patch(f"{SERVER}.PortalAuthHandler._refresh_google_access_token", return_value="fresh-token"), \
                mock.patch(f"{SERVER}.CalendarWriter.cancel_event", return_value={"eventId": "ev1", "calendarId": "primary", "cancelled": True}) as cancel:
            status, body = self._post("/api/agent/calendar/events", {"action": "cancel", "eventId": "ev1", "calendar": "primary"})
        self.assertEqual(status, 200)
        self.assertEqual(cancel.call_args.kwargs["event_id"], "ev1")

    def test_the_loop_learns_what_each_google_connection_may_write_from_the_rows(self) -> None:
        self._connect("email", granted_scope=f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}", address="owner@gmail.com")
        self._connect("calendar", granted_scope=GOOGLE_CALENDAR_OAUTH_SCOPE)
        # The browser claims both can write; the rows decide.
        context = PortalAuthHandler._with_google_write_access(SimpleNamespace(database=self.server.database), "owner@example.com", {
            "gmail": {"platformConnected": True, "connectionStatus": "connected", "writeAccess": False},
            "calendar": {"platformConnected": True, "connectionStatus": "connected", "writeAccess": True},
        })
        self.assertTrue(context["gmail"]["writeAccess"])
        self.assertFalse(context["calendar"]["writeAccess"])
        self.assertEqual(connected_sources(context), {"mailbox", "calendar", "gmail_send"})


if __name__ == "__main__":
    unittest.main()
