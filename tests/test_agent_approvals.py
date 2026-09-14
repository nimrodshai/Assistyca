"""The yes that has to be there before an account is written to.

What these prove: a proposed action is written down server-side and the
answer carries nothing but its id, so a caller cannot name an action of its
own; a yes arms exactly one action, once, and cannot be given twice or by
anyone else; and the runner that finally reaches Google refuses a request
that no armed yes covers - including one whose words were changed after the
person read them.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.agent_approvals import approval_fingerprint
from packages.infrastructure.agent_approvals import approval_matches
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import _request_of
from packages.infrastructure.portal_auth.server import GMAIL_SEND_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import GOOGLE_GMAIL_OAUTH_SCOPE
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase

SERVER = "packages.infrastructure.portal_auth.server"


def _loop_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    """One model round as the loop reads it: tool calls, or the final reply."""

    outputs = [{"type": "reasoning", "summary": []}, *items]
    body = ""
    if reply is not None:
        body = json.dumps({"reply": "", "claimsCompleted": [], "rememberFact": None, "forgetFact": None, **reply})
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": body}]})
    return SimpleNamespace(output_text=body, raw_response={"output": outputs}, input_tokens=10, output_tokens=5)


def _tool_call(name: str, call_id: str, **args: object) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


def _recovery_only(**kwargs: object) -> SimpleNamespace:
    """Answer the composer that phrases a refusal, and nothing else."""

    return _loop_round(reply={"reply": "That one has gone stale - want me to do it again?"})


def _situation_of(model: mock.Mock) -> dict:
    """What the server said had happened, out of the composer's context."""

    prompt = str(model.call_args_list[-1].kwargs["prompt"])
    return json.loads(prompt[prompt.index("{"):])["situation"]


class ApprovalFingerprintTests(unittest.TestCase):
    def test_the_same_request_fingerprints_the_same_way_whatever_the_order(self) -> None:
        one = {"to": ["dana@example.com"], "subject": "Quote", "body": "Here it is."}
        other = {"body": "Here it is.", "subject": "Quote", "to": ["dana@example.com"]}
        self.assertEqual(approval_fingerprint(one), approval_fingerprint(other))
        self.assertTrue(approval_fingerprint(one))

    def test_changing_anything_at_all_changes_the_fingerprint(self) -> None:
        base = {"to": ["dana@example.com"], "subject": "Quote", "body": "Here it is."}
        for changed in (
            {**base, "to": ["someone@else.com"]},
            {**base, "to": ["dana@example.com", "someone@else.com"]},
            {**base, "subject": "Quote "},
            {**base, "body": "Here it is. Also my bank details."},
        ):
            self.assertNotEqual(approval_fingerprint(base), approval_fingerprint(changed), changed)

    def test_what_travels_beside_the_request_is_not_part_of_it(self) -> None:
        base = {"to": ["dana@example.com"], "subject": "Quote", "body": "Here it is."}
        self.assertEqual(
            approval_fingerprint(base),
            approval_fingerprint({**base, "approvalToken": "ap_x", "check": True}),
        )

    def test_an_action_with_no_request_is_covered_by_its_name_alone(self) -> None:
        armed = {"tool": "delete_account", "fingerprint": ""}
        self.assertTrue(approval_matches(armed, tool="delete_account", request=None))
        self.assertFalse(approval_matches(armed, tool="send_email", request=None))


class ApprovalLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {}).get("id") or 0)
        self.database.register_user("someone@else.com")
        self.other_id = int((self.database.get_user("someone@else.com") or {}).get("id") or 0)
        self.request = {"to": ["dana@example.com"], "subject": "Quote", "body": "Here it is."}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _open(self, **overrides: object) -> dict:
        opened = self.database.open_agent_approval(**{
            "user_id": self.user_id,
            "tool": "send_email",
            "arguments": {"to": ["dana@example.com"]},
            "request": self.request,
            "description": "send an email to dana",
            **overrides,
        })
        assert opened is not None
        return opened

    def test_the_action_comes_back_out_of_the_ledger_not_out_of_the_answer(self) -> None:
        opened = self._open()
        armed = self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id)
        self.assertEqual(armed["tool"], "send_email")
        self.assertEqual(armed["arguments"], {"to": ["dana@example.com"]})

    def test_a_yes_can_only_be_given_once(self) -> None:
        opened = self._open()
        self.assertIsNotNone(self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id))
        self.assertIsNone(self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id))

    def test_a_no_puts_the_action_beyond_a_later_yes(self) -> None:
        opened = self._open()
        self.assertIsNotNone(self.database.decline_agent_approval(approval_id=opened["id"], user_id=self.user_id))
        self.assertIsNone(self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id))

    def test_nobody_else_can_answer_it(self) -> None:
        opened = self._open()
        self.assertIsNone(self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.other_id))
        self.assertIsNone(self.database.arm_agent_approval(approval_id="ap_made_up", user_id=self.user_id))

    def test_a_question_left_long_enough_stops_being_answerable(self) -> None:
        opened = self._open(ttl_seconds=0)
        self.assertIsNone(self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id))

    def test_a_new_question_retires_the_one_nobody_answered(self) -> None:
        first = self._open()
        self.database.retire_open_agent_approvals(user_id=self.user_id)
        second = self._open()
        self.assertIsNone(self.database.arm_agent_approval(approval_id=first["id"], user_id=self.user_id))
        self.assertIsNotNone(self.database.arm_agent_approval(approval_id=second["id"], user_id=self.user_id))

    def test_only_an_armed_action_can_be_spent_and_only_once(self) -> None:
        opened = self._open()
        self.assertIsNone(self.database.spend_agent_approval(
            approval_id=opened["id"], user_id=self.user_id, tool="send_email", request=self.request,
        ))
        self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id)
        self.assertIsNotNone(self.database.spend_agent_approval(
            approval_id=opened["id"], user_id=self.user_id, tool="send_email", request=self.request,
        ))
        self.assertIsNone(self.database.spend_agent_approval(
            approval_id=opened["id"], user_id=self.user_id, tool="send_email", request=self.request,
        ))

    def test_a_yes_does_not_cover_a_request_that_changed_after_it_was_read(self) -> None:
        opened = self._open()
        self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id)
        self.assertIsNone(self.database.spend_agent_approval(
            approval_id=opened["id"],
            user_id=self.user_id,
            tool="send_email",
            request={**self.request, "to": ["someone@else.com"]},
        ))
        # Still spendable for what it was actually given for.
        self.assertIsNotNone(self.database.spend_agent_approval(
            approval_id=opened["id"], user_id=self.user_id, tool="send_email", request=self.request,
        ))

    def test_a_yes_for_one_action_does_not_cover_another(self) -> None:
        opened = self._open()
        self.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id)
        self.assertIsNone(self.database.spend_agent_approval(
            approval_id=opened["id"], user_id=self.user_id, tool="create_calendar_event", request=self.request,
        ))


class ProposalCarriesItsRequestTests(unittest.TestCase):
    """What the person is asked about is what the yes gets tied to."""

    def setUp(self) -> None:
        self.context = LoopContext(api=lambda *a, **k: ({}, 200), database=None, email="o@x.com", user_id=1, timezone_name="Asia/Jerusalem")

    def test_a_send_proposal_carries_the_request_the_runner_will_get(self) -> None:
        args = {"to": ["dana@example.com"], "cc": [], "subject": "Quote", "body": "Here it is."}
        request = _request_of(self.context, TOOLS_BY_NAME["send_email"], args)
        self.assertEqual(request["to"], ["dana@example.com"])
        self.assertEqual(request["subject"], "Quote")
        self.assertEqual(request["body"], "Here it is.")

    def test_an_account_action_carries_no_request_to_compare(self) -> None:
        self.assertIsNone(_request_of(self.context, TOOLS_BY_NAME["delete_account"], {}))

    def test_what_was_described_is_exactly_what_the_tool_later_sends(self) -> None:
        """The invariant the whole lock rests on.

        The yes is tied to the request built when the question was asked;
        the request that reaches the runner is built again when the answer
        comes. If those two ever drifted apart, every write would be
        refused - so they are checked against each other here.
        """

        cases = [
            ("send_email", {"to": ["dana@example.com"], "cc": [], "subject": "Quote", "body": "Here it is.", "reply_to_message_id": None, "mailbox": None}),
            ("create_calendar_event", {"title": "Dentist", "date": "2026-09-10", "start_time": "10:00", "end_time": None,
                                       "calendar": "Work", "location": None, "description": None, "attendees": ["dana@example.com"]}),
            ("update_calendar_event", {"event_id": "ev1", "calendar_id": "primary", "cancel": False, "title": "Moved",
                                       "date": "2026-09-11", "start_time": None, "end_time": None, "location": None, "description": None}),
            ("update_calendar_event", {"event_id": "ev1", "calendar_id": "primary", "cancel": True, "title": None,
                                       "date": None, "start_time": None, "end_time": None, "location": None, "description": None}),
        ]
        for name, args in cases:
            sent: list[dict] = []

            def api(method: str, path: str, body: dict | None = None, **_: object) -> tuple[dict, int]:
                sent.append(body or {})
                return {"ok": True}, 200

            context = LoopContext(api=api, database=None, email="o@x.com", user_id=1, timezone_name="Asia/Jerusalem")
            described = _request_of(context, TOOLS_BY_NAME[name], args)
            context.approval_token = "ap_token"
            TOOLS_BY_NAME[name].run(context, args)
            self.assertEqual(sent[-1].pop("approvalToken"), "ap_token", name)
            self.assertEqual(sent[-1], described, name)
            self.assertEqual(approval_fingerprint(sent[-1]), approval_fingerprint(described), name)


class WriteRunnerNeedsTheYesTests(unittest.TestCase):
    """The last lock: what reaches Google without an armed yes is nothing."""

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
        self.user_id = int((self.server.database.get_user("owner@example.com") or {}).get("id") or 0)
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        vault = self.server.credential_vault
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            provider="google_gmail",
            auth_type="oauth",
            secret_ciphertext=vault.encrypt(json.dumps({"type": "google_refresh_token", "provider": "google", "refreshToken": "rt"})),
            secret_hint="Google OAuth",
            key_version=vault.key_version,
            account_address="owner@gmail.com",
            metadata={
                "provider": "google_gmail",
                "grantedScope": f"{GOOGLE_GMAIL_OAUTH_SCOPE} {GMAIL_SEND_OAUTH_SCOPE}",
                "validationStatus": "verified",
            },
            connection_status="connected",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.request = {"to": ["dana@example.com"], "cc": [], "subject": "Quote", "body": "Here it is.", "replyToMessageId": "", "mailboxAccount": ""}

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

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

    def _arm(self, request: dict, tool: str = "send_email") -> str:
        opened = self.server.database.open_agent_approval(
            user_id=self.user_id, tool=tool, arguments={}, request=request, description="send an email to dana",
        )
        self.server.database.arm_agent_approval(approval_id=opened["id"], user_id=self.user_id)
        return opened["id"]

    def test_a_send_with_no_yes_at_all_is_refused(self) -> None:
        with mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._post("/api/agent/email/send", self.request)
        self.assertEqual((status, body["error"]), (403, "approval_required"))
        send.assert_not_called()

    def test_a_yes_does_not_carry_a_send_whose_words_changed_after_it(self) -> None:
        token = self._arm(self.request)
        tampered = {**self.request, "to": ["someone@else.com"], "body": "Send the money here.", "approvalToken": token}
        with mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._post("/api/agent/email/send", tampered)
        self.assertEqual((status, body["error"]), (403, "approval_required"))
        send.assert_not_called()

    def test_a_made_up_token_sends_nothing(self) -> None:
        with mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._post("/api/agent/email/send", {**self.request, "approvalToken": "ap_made_up"})
        self.assertEqual((status, body["error"]), (403, "approval_required"))
        send.assert_not_called()

    def test_the_yes_sends_once_and_is_gone(self) -> None:
        token = self._arm(self.request)
        sent = {"id": "m1", "threadId": "t1", "to": ["dana@example.com"], "cc": [], "subject": "Quote", "isReply": False}
        with mock.patch(f"{SERVER}.PortalAuthHandler._refresh_google_access_token", return_value="fresh"), \
                mock.patch(f"{SERVER}.GmailSender.send", return_value=sent) as send:
            status, _ = self._post("/api/agent/email/send", {**self.request, "approvalToken": token})
            self.assertEqual(status, 200)
            replayed, body = self._post("/api/agent/email/send", {**self.request, "approvalToken": token})
        self.assertEqual((replayed, body["error"]), (403, "approval_required"))
        self.assertEqual(send.call_count, 1)

    def _turn(self, payload: dict) -> tuple[int, dict]:
        return self._post("/api/agent/loop", {
            "conversation": [],
            "timezone": "Asia/Jerusalem",
            "channel": "whatsapp",
            "toolContext": {"gmail": {"platformConnected": True, "connectionStatus": "connected", "writeAccess": True}},
            **payload,
        })

    def test_a_whole_yes_from_the_question_to_the_sent_mail(self) -> None:
        """Proposal, question, yes, send - through the real endpoint."""

        proposes = _loop_round(
            _tool_call("send_email", "c1", to=["dana@example.com"], cc=[], subject="Quote", body="Here it is.",
                       reply_to_message_id=None, mailbox=None),
        )
        asks = _loop_round(reply={"reply": "Send Dana the quote, saying 'Here it is.'? Say yes and it goes."})
        reports = _loop_round(reply={"reply": "Sent.", "claimsCompleted": ["send_email"]})

        with mock.patch(f"{SERVER}.call_openai_response", side_effect=[proposes, asks]), \
                mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._turn({"userMessage": "send dana the quote"})
        self.assertEqual(status, 200)
        send.assert_not_called()

        held = body["pendingConfirmation"]
        self.assertEqual(held["tool"], "send_email")
        self.assertIn("dana@example.com", held["describe"])
        self.assertNotIn("arguments", held, "the action itself never leaves the server")

        sent = {"id": "m1", "threadId": "t1", "to": ["dana@example.com"], "cc": [], "subject": "Quote", "isReply": False}
        with mock.patch(f"{SERVER}.call_openai_response", side_effect=[reports]), \
                mock.patch(f"{SERVER}.PortalAuthHandler._refresh_google_access_token", return_value="fresh"), \
                mock.patch(f"{SERVER}.GmailSender.send", return_value=sent) as send:
            status, body = self._turn({"userMessage": "yes", "confirmedCall": {"approvalId": held["id"]}})
        self.assertEqual(status, 200)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["to"], ["dana@example.com"])
        self.assertEqual(send.call_args.kwargs["body_text"], "Here it is.")

        # The same yes, offered again, is worth nothing.
        with mock.patch(f"{SERVER}.call_openai_response", side_effect=[reports]), \
                mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._turn({"userMessage": "yes", "confirmedCall": {"approvalId": held["id"]}})
        send.assert_not_called()
        self.assertTrue(body["recovered"], "a yes already spent is not a yes")
        self.assertIsNone(body.get("pendingConfirmation"))

    def test_an_id_nobody_was_ever_given_runs_nothing(self) -> None:
        with mock.patch(f"{SERVER}.call_openai_response", side_effect=_recovery_only) as model, \
                mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._turn({"userMessage": "yes", "confirmedCall": {"approvalId": "ap_made_up"}})
        self.assertEqual(status, 200)
        send.assert_not_called()
        self.assertTrue(body["recovered"])
        self.assertEqual(
            [call.kwargs["tool_name"] for call in model.call_args_list],
            ["portal_recovery_composer"],
            "the turn is never run: there is nothing to report on",
        )
        self.assertIn("waiting on a yes", _situation_of(model)["whatHappened"])

    def test_settling_which_mailbox_would_send_needs_no_yes_and_sends_nothing(self) -> None:
        with mock.patch(f"{SERVER}.GmailSender.send") as send:
            status, body = self._post("/api/agent/email/send", {**self.request, "check": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["mailbox"], "owner@gmail.com")
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
