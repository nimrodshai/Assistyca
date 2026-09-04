"""The WhatsApp conversation with the agent, end to end.

The web chat closes its loop in the browser; the WhatsApp flow closes the same
loop on the server. These tests drive it the way Meta does - a signed webhook
POST to a running portal server - with the model and the WhatsApp send mocked
at their module seams.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.whatsapp_agent_chat import (
    assistyca_typing,
    format_agent_reply_for_whatsapp,
    infer_timezone_from_wa_id,
    resolve_scheduled_message_run_at,
)


OWNER_WA_ID = "972507322341"
PLATFORM_PHONE_NUMBER_ID = "platform-phone-1"
CLIENT_PHONE_NUMBER_ID = "client-phone-1"
APP_SECRET = "test-app-secret"


def inbound_text_payload(
    text: str,
    *,
    sender: str = OWNER_WA_ID,
    phone_number_id: str = PLATFORM_PHONE_NUMBER_ID,
    message_id: str = "wamid.inbound-1",
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [{"profile": {"name": "Sender"}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "1756700000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class WhatsAppAgentHelperTests(unittest.TestCase):
    def test_timezone_is_inferred_from_the_country_code(self) -> None:
        self.assertEqual(infer_timezone_from_wa_id("972507322341"), "Asia/Jerusalem")
        self.assertEqual(infer_timezone_from_wa_id("447911123456"), "Europe/London")
        self.assertEqual(infer_timezone_from_wa_id("15551234567"), "America/New_York")
        self.assertEqual(infer_timezone_from_wa_id(""), "UTC")

    def test_portal_markdown_becomes_whatsapp_text(self) -> None:
        reply = format_agent_reply_for_whatsapp(
            "## Today\n**Two** meetings.\n- [Agenda](https://example.com/a)\n- Standup"
        )
        self.assertIn("*Today*", reply)
        self.assertIn("*Two* meetings.", reply)
        self.assertIn("• Agenda (https://example.com/a)", reply)
        self.assertIn("• Standup", reply)
        self.assertNotIn("##", reply)
        self.assertNotIn("](", reply)

    def test_a_very_long_reply_is_truncated(self) -> None:
        reply = format_agent_reply_for_whatsapp("word " * 2000)
        self.assertLessEqual(len(reply), 3500)
        self.assertTrue(reply.endswith("…"))

    def test_run_at_rolls_to_tomorrow_when_the_time_already_passed(self) -> None:
        now = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
        run_at = resolve_scheduled_message_run_at(
            {"timeLocal": "12:40", "datePolicy": "next_occurrence", "timezone": "UTC"},
            now=now,
        )
        self.assertEqual(run_at, "2026-09-02T12:40:00+00:00")

    def test_run_at_honours_the_timezone(self) -> None:
        now = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)  # 09:00 in Jerusalem
        run_at = resolve_scheduled_message_run_at(
            {"timeLocal": "12:40", "datePolicy": "next_occurrence", "timezone": "Asia/Jerusalem"},
            now=now,
        )
        self.assertEqual(run_at, "2026-09-01T09:40:00+00:00")

    def test_run_at_needs_a_real_time(self) -> None:
        self.assertEqual(resolve_scheduled_message_run_at({"timeLocal": "later"}), "")
        self.assertEqual(resolve_scheduled_message_run_at({}), "")


class WhatsAppTypingIndicatorTests(unittest.TestCase):
    """The phone shows "typing..." from the moment a message arrives until the reply."""

    def setUp(self) -> None:
        self.env = mock.patch.dict(
            "os.environ",
            {
                "WHATSAPP_ALLOW_MOCK_SEND": "0",
                "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM_PHONE_NUMBER_ID,
                "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_the_indicator_is_renewed_while_the_turn_is_still_running(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator"
        ) as typing:
            with assistyca_typing("wamid.slow", refresh_seconds=0.05):
                import time
                time.sleep(0.18)
        self.assertGreaterEqual(typing.call_count, 3)
        for call in typing.call_args_list:
            self.assertEqual(call.kwargs["message_id"], "wamid.slow")
            self.assertEqual(call.kwargs["phone_number_id"], PLATFORM_PHONE_NUMBER_ID)
            self.assertEqual(call.kwargs["access_token"], "platform-token")

    def test_a_failed_indicator_is_not_retried_and_never_stops_the_turn(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator",
            side_effect=RuntimeError("WhatsApp rejected the message: bad token"),
        ) as typing, contextlib.redirect_stdout(io.StringIO()) as out:
            with assistyca_typing("wamid.slow", refresh_seconds=0.05):
                import time
                time.sleep(0.15)
                ran = True
        self.assertTrue(ran)
        self.assertEqual(typing.call_count, 1)
        self.assertIn("typing indicator could not be sent", out.getvalue())

    def test_nothing_is_sent_without_an_inbound_message_id(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator"
        ) as typing:
            with assistyca_typing(""):
                pass
        typing.assert_not_called()

    def test_mock_send_mode_never_reaches_meta(self) -> None:
        with mock.patch.dict("os.environ", {"WHATSAPP_ALLOW_MOCK_SEND": "1"}, clear=False), mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator"
        ) as typing:
            with assistyca_typing("wamid.slow"):
                pass
        typing.assert_not_called()


class WhatsAppAgentChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1",
            0,
            self.root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                session_secret="agent-chat-test-secret",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.save_whatsapp_connection(
            "owner@example.com",
            business_account_id="waba-1",
            phone_number_id=CLIENT_PHONE_NUMBER_ID,
            owner_wa_id=OWNER_WA_ID,
            connection_status="connected",
        )
        self.env = mock.patch.dict(
            "os.environ",
            {
                # The approval store does not follow the temporary database:
                # left alone it resolves to portal/portal-whatsapp inside the
                # repository, where every run of every test would share one
                # file and inherit the approvals the last run left behind.
                "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
                "WHATSAPP_APP_SECRET": APP_SECRET,
                "WHATSAPP_ALLOW_MOCK_SEND": "1",
                "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM_PHONE_NUMBER_ID,
                "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            },
            clear=False,
        )
        self.env.start()
        self.send_mock = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message",
            return_value="wamid.agent-reply",
        )
        self.sent = self.send_mock.start()

    def tearDown(self) -> None:
        self.send_mock.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _post_webhook(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(
            f"{self.base_url}/webhooks/whatsapp",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={signature}",
            },
        )
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _turn_response(self, turn: dict) -> SimpleNamespace:
        return SimpleNamespace(output_text=json.dumps(turn))

    def test_an_owner_message_gets_an_agent_reply_over_whatsapp(self) -> None:
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({
                "outcome": "message",
                "reply": "Hi! I can help with that.",
            }),
        ):
            response = self._post_webhook(
                inbound_text_payload("What can you do?", message_id="wamid.agent-msg-1")
            )

        actions = [entry.get("action") for entry in response.get("results", [])]
        self.assertIn("agent_chat_reply", actions)
        reply_entry = next(
            entry for entry in response["results"] if entry.get("action") == "agent_chat_reply"
        )
        self.assertEqual(reply_entry["reply_text"], "Hi! I can help with that.")
        self.assertEqual(reply_entry["route"], "platform_owner_alert")

        self.sent.assert_called_once()
        self.assertEqual(self.sent.call_args.kwargs["recipient_wa_id"], OWNER_WA_ID)

        transcript = self.database.list_recent_whatsapp_agent_messages(
            user_id=int(self.user["id"]),
        )
        self.assertEqual([item["role"] for item in transcript], ["user", "assistant"])
        self.assertEqual(transcript[0]["text"], "What can you do?")
        self.assertEqual(transcript[1]["text"], "Hi! I can help with that.")

    def test_the_phone_shows_typing_before_the_reply_arrives(self) -> None:
        order: list[str] = []

        def typing(**kwargs):
            order.append(f"typing:{kwargs['message_id']}")

        def send(**kwargs):
            order.append("reply")
            return "wamid.agent-reply"

        self.sent.side_effect = send
        with (
            mock.patch.dict("os.environ", {"WHATSAPP_ALLOW_MOCK_SEND": "0"}, clear=False),
            mock.patch(
                "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_typing_indicator",
                side_effect=typing,
            ),
            mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
                return_value=self._turn_response({"outcome": "message", "reply": "On it."}),
            ),
        ):
            response = self._post_webhook(
                inbound_text_payload("Book me a slot tomorrow", message_id="wamid.agent-msg-7")
            )

        actions = [entry.get("action") for entry in response.get("results", [])]
        self.assertIn("agent_chat_reply", actions)
        self.assertEqual(order, ["typing:wamid.agent-msg-7", "reply"])

    def test_the_conversation_history_reaches_the_next_turn(self) -> None:
        self.database.save_whatsapp_agent_message(
            user_id=int(self.user["id"]), role="user", text="Earlier question",
        )
        self.database.save_whatsapp_agent_message(
            user_id=int(self.user["id"]), role="assistant", text="Earlier answer",
        )
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({"outcome": "message", "reply": "Following up."}),
        ) as model:
            self._post_webhook(inbound_text_payload("And then?", message_id="wamid.agent-msg-2"))

        prompt = model.call_args.kwargs["prompt"]
        self.assertIn("Earlier question", prompt)
        self.assertIn("Earlier answer", prompt)
        self.assertIn('"channel":"whatsapp"', prompt)

    def test_a_proposal_is_held_and_a_yes_schedules_it(self) -> None:
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({
                "outcome": "proposal",
                "proposalType": "scheduled-message",
                "reply": "I'll text you at 12:40. Want me to set it up?",
                "changes": {
                    "channel": "whatsapp",
                    "timeLocal": "12:40",
                    "datePolicy": "next_occurrence",
                    "messageText": "Reminder: stand up and stretch.",
                },
            }),
        ):
            self._post_webhook(
                inbound_text_payload("Text me at 12:40", message_id="wamid.agent-msg-3")
            )

        held = self.database.get_whatsapp_agent_active_proposal(user_id=int(self.user["id"]))
        self.assertIsNotNone(held)
        self.assertEqual(held["type"], "scheduled-message")
        self.assertEqual(held["details"]["timeLocal"], "12:40")
        self.assertEqual(held["details"]["timezone"], "Asia/Jerusalem")

        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({
                "outcome": "approve_proposal",
                "reply": "Done - it's scheduled.",
            }),
        ):
            response = self._post_webhook(
                inbound_text_payload("yes", message_id="wamid.agent-msg-4")
            )

        reply_entry = next(
            entry for entry in response["results"] if entry.get("action") == "agent_chat_reply"
        )
        self.assertEqual(reply_entry["outcome"], "approve_proposal")
        # The model's reply, then the time it is really set for, as a fact.
        self.assertRegex(reply_entry["reply_text"], r"^Done - it's scheduled\. That's for \w{3} \d{1,2} \w{3} at 12:40\.$")

        self.assertIsNone(
            self.database.get_whatsapp_agent_active_proposal(user_id=int(self.user["id"]))
        )
        actions = self.database.list_scheduled_actions_for_user(int(self.user["id"]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["payload"]["messageText"], "Reminder: stand up and stretch.")
        self.assertEqual(actions[0]["payload"]["source"], "whatsapp_agent")

    def test_a_bare_send_with_a_pending_approval_stays_with_the_approval_flow(self) -> None:
        with mock.patch(
            "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
            return_value="wamid.owner-notice",
        ):
            self._post_webhook(
                inbound_text_payload(
                    "Do you have any openings tomorrow?",
                    sender="972500000001",
                    phone_number_id=CLIENT_PHONE_NUMBER_ID,
                    message_id="wamid.customer-1",
                )
            )

            with mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
            ) as model:
                response = self._post_webhook(
                    inbound_text_payload("Send", message_id="wamid.agent-msg-5")
                )

        model.assert_not_called()
        actions = [entry.get("action") for entry in response.get("results", [])]
        self.assertNotIn("agent_chat_reply", actions)
        self.assertIn("send_suggested", actions)

    def test_an_operator_number_is_answered_without_any_saved_connection(self) -> None:
        # The account whose number *is* the Assistyca number has no client
        # WhatsApp connection to be recognised by, which is the whole reason
        # the server-configured mapping exists.
        self.database.register_user("operator@example.com")
        operator = self.database.get_user("operator@example.com") or {}
        self.assertIsNone(
            self.database.get_whatsapp_connection_by_user_id(int(operator["id"]))
        )

        # Written the way a person would type their own phone, to prove the
        # spaces, dashes and country prefix are all normalized away.
        with (
            mock.patch.dict(
                "os.environ",
                {"ASSISTYCA_WHATSAPP_OWNER_NUMBERS": "+972 52-111-2233 : operator@example.com"},
                clear=False,
            ),
            mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
                return_value=self._turn_response({
                    "outcome": "message",
                    "reply": "Hello from the agent.",
                }),
            ),
        ):
            response = self._post_webhook(
                inbound_text_payload(
                    "are you there?",
                    sender="972521112233",
                    message_id="wamid.agent-operator-1",
                )
            )

        reply_entry = next(
            entry for entry in response["results"] if entry.get("action") == "agent_chat_reply"
        )
        self.assertEqual(reply_entry["reply_text"], "Hello from the agent.")
        self.assertEqual(reply_entry["route"], "platform_owner_alert")
        self.sent.assert_called_once()
        self.assertEqual(self.sent.call_args.kwargs["recipient_wa_id"], "972521112233")

        transcript = self.database.list_recent_whatsapp_agent_messages(
            user_id=int(operator["id"]),
        )
        self.assertEqual([item["text"] for item in transcript], ["are you there?", "Hello from the agent."])

    def test_an_unmapped_stranger_is_still_not_answered(self) -> None:
        # With signup on, a stranger is greeted rather than dropped; these
        # tests are about the door being closed, so they close it. A plain
        # assignment, not a second patch: setUp's patch restores the whole
        # environment in tearDown, and a second patch stopped afterwards by
        # addCleanup would put its own snapshot back on top of that.
        os.environ["PORTAL_WHATSAPP_SIGNUP_ENABLED"] = "0"
        with (
            mock.patch.dict(
                "os.environ",
                {"ASSISTYCA_WHATSAPP_OWNER_NUMBERS": "972521112233:operator@example.com"},
                clear=False,
            ),
            mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
            ) as model,
        ):
            response = self._post_webhook(
                inbound_text_payload(
                    "hello?",
                    sender="14155550123",
                    message_id="wamid.agent-stranger-1",
                )
            )

        model.assert_not_called()
        self.sent.assert_not_called()
        self.assertEqual(response["results"][0]["type"], "error")

    def _issue_claim_code(self, email: str = "owner@example.com") -> dict:
        code, _ = self.server.store.issue_challenge(email)
        ok, error, result = self.server.store.verify_code(email, code)
        self.assertTrue(ok, error)
        token = str((result or {}).get("token") or "")
        request = urllib_request.Request(
            f"{self.base_url}/api/whatsapp/my-numbers/code",
            data=b"{}",
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib_request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_a_phone_links_itself_by_sending_the_code_then_can_chat(self) -> None:
        # Nobody edits configuration anywhere in this test: the portal issues a
        # code, the phone sends it, and from then on that phone is recognised.
        issued = self._issue_claim_code()
        self.assertTrue(issued["ok"])
        self.assertEqual(len(issued["code"]), 6)
        self.assertEqual(issued["numbers"], [])

        new_phone = "447700900123"
        claim = self._post_webhook(
            inbound_text_payload(
                f"Assistyca code {issued['code']}",
                sender=new_phone,
                message_id="wamid.claim-1",
            )
        )
        self.assertEqual(claim["results"][0]["action"], "number_claimed")
        self.assertEqual(
            self.database.get_user_id_for_whatsapp_number(new_phone),
            int(self.user["id"]),
        )

        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({"outcome": "message", "reply": "Yes, I'm here."}),
        ):
            response = self._post_webhook(
                inbound_text_payload(
                    "are you there?",
                    sender=new_phone,
                    message_id="wamid.claim-chat-1",
                )
            )

        reply = next(
            entry for entry in response["results"] if entry.get("action") == "agent_chat_reply"
        )
        self.assertEqual(reply["reply_text"], "Yes, I'm here.")

    def test_a_claim_code_cannot_be_used_twice(self) -> None:
        issued = self._issue_claim_code()
        self._post_webhook(
            inbound_text_payload(
                f"Assistyca code {issued['code']}",
                sender="447700900123",
                message_id="wamid.claim-2a",
            )
        )
        replay = self._post_webhook(
            inbound_text_payload(
                f"Assistyca code {issued['code']}",
                sender="447700900999",
                message_id="wamid.claim-2b",
            )
        )
        self.assertEqual(replay["results"][0]["action"], "claim_rejected")
        self.assertEqual(replay["results"][0]["reason"], "already_claimed")
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("447700900999"), 0)

    def test_a_phone_already_linked_elsewhere_is_not_taken_over(self) -> None:
        self.database.register_user("second@example.com")
        first = self._issue_claim_code()
        self._post_webhook(
            inbound_text_payload(
                f"code {first['code']}",
                sender="447700900123",
                message_id="wamid.claim-3a",
            )
        )
        second = self._issue_claim_code("second@example.com")
        # A phone that already answers for one account never reaches the claim
        # step again: it resolves to its own account first, so somebody else's
        # code arriving from it is just that phone talking. Taking a number
        # over would take the conversation away from whoever proved it.
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({"outcome": "message", "reply": "Noted."}),
        ):
            response = self._post_webhook(
                inbound_text_payload(
                    f"code {second['code']}",
                    sender="447700900123",
                    message_id="wamid.claim-3b",
                )
            )

        actions = [entry.get("action") for entry in response["results"]]
        self.assertNotIn("number_claimed", actions)
        self.assertEqual(
            self.database.get_user_id_for_whatsapp_number("447700900123"),
            int(self.user["id"]),
        )

    def test_a_code_cannot_move_a_number_that_answers_for_someone_else(self) -> None:
        # The guard underneath the routing, in case the order above ever
        # changes: the store itself refuses to move a claimed number.
        self.database.register_user("second@example.com")
        second = self.database.get_user("second@example.com") or {}
        self.database.create_whatsapp_claim_code(
            user_id=int(self.user["id"]),
            code="AAAA22",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.database.claim_whatsapp_number_with_code(code="AAAA22", wa_id="447700900123")
        self.database.create_whatsapp_claim_code(
            user_id=int(second["id"]),
            code="BBBB33",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

        outcome = self.database.claim_whatsapp_number_with_code(code="BBBB33", wa_id="447700900123")

        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["reason"], "number_taken")
        self.assertEqual(
            self.database.get_user_id_for_whatsapp_number("447700900123"),
            int(self.user["id"]),
        )

    def test_an_ordinary_message_shaped_like_a_code_is_ignored(self) -> None:
        # With signup on, a stranger is greeted rather than dropped; these
        # tests are about the door being closed, so they close it. A plain
        # assignment, not a second patch: setUp's patch restores the whole
        # environment in tearDown, and a second patch stopped afterwards by
        # addCleanup would put its own snapshot back on top of that.
        os.environ["PORTAL_WHATSAPP_SIGNUP_ENABLED"] = "0"
        # "PLEASE" fits the code alphabet exactly. Answering it would turn the
        # number into a paid inbox for anyone who found it.
        response = self._post_webhook(
            inbound_text_payload(
                "PLEASE",
                sender="447700900555",
                message_id="wamid.claim-4",
            )
        )
        self.sent.assert_not_called()
        self.assertEqual(response["results"][0]["type"], "error")

    def test_a_linked_number_can_be_removed_again(self) -> None:
        issued = self._issue_claim_code()
        self._post_webhook(
            inbound_text_payload(
                f"code {issued['code']}",
                sender="447700900123",
                message_id="wamid.claim-5",
            )
        )
        self.assertTrue(
            self.database.delete_user_whatsapp_number(
                user_id=int(self.user["id"]),
                wa_id="447700900123",
            )
        )
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("447700900123"), 0)

    def test_an_unresolved_message_says_why_in_the_log(self) -> None:
        # With signup on, a stranger is greeted rather than dropped; these
        # tests are about the door being closed, so they close it. A plain
        # assignment, not a second patch: setUp's patch restores the whole
        # environment in tearDown, and a second patch stopped afterwards by
        # addCleanup would put its own snapshot back on top of that.
        os.environ["PORTAL_WHATSAPP_SIGNUP_ENABLED"] = "0"
        buffer = io.StringIO()
        with (
            mock.patch.dict(
                "os.environ",
                {"ASSISTYCA_WHATSAPP_OWNER_NUMBERS": "972521112233:nobody@example.com"},
                clear=False,
            ),
            contextlib.redirect_stdout(buffer),
        ):
            self._post_webhook(
                inbound_text_payload(
                    "hello?",
                    sender="14155550123",
                    message_id="wamid.agent-unresolved-1",
                )
            )

        diagnostics = [
            json.loads(line)
            for line in buffer.getvalue().splitlines()
            if '"whatsapp_route_unresolved"' in line
        ]
        self.assertEqual(len(diagnostics), 1)
        entry = diagnostics[0]
        # The number that wrote in, so a wrong entry can be spotted, without
        # writing anyone's phone number out in full.
        self.assertEqual(entry["senderWaId"], "...0123")
        self.assertTrue(entry["isPlatformNumber"])
        self.assertEqual(entry["operatorNumbersConfigured"], 1)
        self.assertEqual(entry["operatorNumbers"], ["...2233"])
        self.assertFalse(entry["operatorNumberMatched"])
        self.assertFalse(entry["operatorAccountActive"])
        self.assertFalse(entry["ownerConnectionMatched"])

    def test_the_log_separates_an_unset_variable_from_a_wrong_number(self) -> None:
        # With signup on, a stranger is greeted rather than dropped; these
        # tests are about the door being closed, so they close it. A plain
        # assignment, not a second patch: setUp's patch restores the whole
        # environment in tearDown, and a second patch stopped afterwards by
        # addCleanup would put its own snapshot back on top of that.
        os.environ["PORTAL_WHATSAPP_SIGNUP_ENABLED"] = "0"
        buffer = io.StringIO()
        with (
            mock.patch.dict("os.environ", {"ASSISTYCA_WHATSAPP_OWNER_NUMBERS": ""}, clear=False),
            contextlib.redirect_stdout(buffer),
        ):
            self._post_webhook(
                inbound_text_payload(
                    "hello?",
                    sender="14155550123",
                    message_id="wamid.agent-unresolved-2",
                )
            )

        entry = next(
            json.loads(line)
            for line in buffer.getvalue().splitlines()
            if '"whatsapp_route_unresolved"' in line
        )
        # Nothing configured at all reads differently from a number that does
        # not match, which is the distinction that matters when nothing works.
        self.assertEqual(entry["operatorNumbersConfigured"], 0)
        self.assertEqual(entry["operatorNumbers"], [])

    def test_an_operator_number_does_not_hijack_a_clients_customer_traffic(self) -> None:
        # The operator mapping only applies to the Assistyca number. A customer
        # writing to a client's own number is still customer traffic.
        with (
            mock.patch.dict(
                "os.environ",
                {"ASSISTYCA_WHATSAPP_OWNER_NUMBERS": f"{OWNER_WA_ID}:owner@example.com"},
                clear=False,
            ),
            mock.patch(
                "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
                return_value="wamid.owner-notice",
            ),
            mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
            ) as model,
        ):
            response = self._post_webhook(
                inbound_text_payload(
                    "do you have openings tomorrow?",
                    sender="972500000002",
                    phone_number_id=CLIENT_PHONE_NUMBER_ID,
                    message_id="wamid.customer-2",
                )
            )

        model.assert_not_called()
        self.assertEqual(response["results"][0]["type"], "customer")

    def test_an_expired_trial_is_told_so_over_whatsapp(self) -> None:
        # Cost control has to reach the channel people actually use, and the
        # person reading it is a client whose trial ran out, not an error.
        self.database.set_user_trial("owner@example.com", trial_days=2)
        with self.database._connection() as conn:  # noqa: SLF001 - fixture setup
            conn.execute(
                "UPDATE users SET trial_started_at = ? WHERE id = ?",
                (
                    (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
                    int(self.user["id"]),
                ),
            )
            conn.commit()

        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
        ) as model:
            response = self._post_webhook(
                inbound_text_payload("are you there?", message_id="wamid.trial-1")
            )

        model.assert_not_called()
        reply = next(
            entry for entry in response["results"] if entry.get("action") == "agent_chat_reply"
        )
        self.assertIn("trial has ended", reply["reply_text"])
        self.sent.assert_called_once()

    def test_disabling_the_flow_keeps_the_old_help_behaviour(self) -> None:
        with (
            mock.patch.dict("os.environ", {"WHATSAPP_AGENT_CHAT_ENABLED": "0"}, clear=False),
            mock.patch(
                "packages.infrastructure.portal_auth.server.call_openai_response",
            ) as model,
            mock.patch(
                "packages.infrastructure.whatsapp_portal_service.send_whatsapp_message",
                return_value="wamid.help",
            ),
        ):
            response = self._post_webhook(
                inbound_text_payload("What can you do?", message_id="wamid.agent-msg-6")
            )

        model.assert_not_called()
        actions = [entry.get("action") for entry in response.get("results", [])]
        self.assertIn("help", actions)
        self.assertNotIn("agent_chat_reply", actions)


if __name__ == "__main__":
    unittest.main()


class _WhatsAppApiCase(unittest.TestCase):
    """The API fixture without its tests, so a suite built on it does not rerun them."""

    setUp = WhatsAppAgentChatApiTests.setUp
    tearDown = WhatsAppAgentChatApiTests.tearDown
    _post_webhook = WhatsAppAgentChatApiTests._post_webhook
    _turn_response = WhatsAppAgentChatApiTests._turn_response


class WhatsAppRecoveryTests(_WhatsAppApiCase):
    """Fault injection at each seam: every failure still gets one reply with a way forward.

    The model that writes the recovery reply is mocked like the turn model, so
    what these prove is the plumbing: the failure becomes a report, the report
    reaches the composer, the composer's words are what the phone receives, and
    when no composer can run the assembled sentence goes instead.
    """

    def _reply(self, response: dict) -> str:
        entry = next(entry for entry in response["results"] if entry.get("action") == "agent_chat_reply")
        return entry["reply_text"]

    def test_a_lookup_that_needs_a_mailbox_nobody_connected_is_explained_not_leaked(self) -> None:
        turn = self._turn_response({
            "outcome": "answer_now",
            "reply": "Checking now.",
            "proposalType": "email-digest",
            "changes": {"fields": {"timeWindow": "today"}},
        })
        recovery = SimpleNamespace(output_text="I can't read your inbox yet - nothing is connected. Reply \"connect my email\" and I'll send the link.")
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=[turn, recovery],
        ) as model:
            response = self._post_webhook(inbound_text_payload("any important emails today?", message_id="wamid.rec-1"))

        reply = self._reply(response)
        self.assertEqual(reply, recovery.output_text)
        self.assertNotIn("Open Email setup", reply)
        # The second call is the recovery composer, and it was told the situation.
        recovery_prompt = model.call_args_list[1].kwargs["prompt"]
        self.assertIn('"code":"source_not_connected"', recovery_prompt)
        self.assertIn('"source":"mailbox"', recovery_prompt)

    def test_a_turn_the_model_never_finishes_is_repaired_then_recovered(self) -> None:
        from packages.infrastructure.openai_api import OpenAIIncompleteError

        recovery = SimpleNamespace(output_text="I lost the thread there for a second. Ask me again and I'll pick it up.")
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=[OpenAIIncompleteError("cut off"), recovery],
        ):
            response = self._post_webhook(inbound_text_payload("what's on today?", message_id="wamid.rec-2"))

        self.assertEqual(self._reply(response), recovery.output_text)

    def test_an_unusable_turn_gets_one_repair_try_before_recovery(self) -> None:
        bad = SimpleNamespace(output_text="not json at all")
        good = self._turn_response({"outcome": "message", "reply": "Here you go."})
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=[bad, good],
        ) as model:
            response = self._post_webhook(inbound_text_payload("hello?", message_id="wamid.rec-3"))

        self.assertEqual(self._reply(response), "Here you go.")
        self.assertEqual(model.call_count, 2)
        self.assertIn("could not be used", model.call_args_list[1].kwargs["prompt"])

    def test_when_no_model_answers_at_all_the_assembled_sentence_goes_out(self) -> None:
        from packages.infrastructure.openai_api import OpenAIRequestError

        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=OpenAIRequestError("down", status_code=503),
        ):
            response = self._post_webhook(inbound_text_payload("are you there?", message_id="wamid.rec-4"))

        reply = self._reply(response)
        self.assertIn("couldn't think that through", reply)
        self.assertIn("Ask me again", reply)
        self.assertNotIn("OpenAI", reply)

    def test_a_voice_note_is_answered_in_words_the_composer_wrote(self) -> None:
        payload = inbound_text_payload("", message_id="wamid.rec-5")
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        message["type"] = "audio"
        message.pop("text", None)
        message["audio"] = {"id": "audio-1"}
        recovery = SimpleNamespace(output_text="I can't listen to voice notes yet - type it and I'm on it.")
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=recovery,
        ):
            response = self._post_webhook(payload)

        self.assertEqual(self._reply(response), recovery.output_text)

    def test_no_reply_from_this_channel_is_ever_a_dead_end(self) -> None:
        # The assembled sentence is the floor every reply stands on. Whatever
        # the composer does, this is what the person gets when it cannot run.
        from packages.infrastructure.recovery_reply import RECOVERY_CODES, build_situation, computed_recovery_sentence

        for code in sorted(RECOVERY_CODES):
            sentence = computed_recovery_sentence(build_situation(code, can_retry=True))
            self.assertTrue(any(word in sentence for word in ("Ask me again", "Reply", "Tell me", "https://")), sentence)


class WhatsAppPreflightTests(_WhatsAppApiCase):
    def _reply(self, response: dict) -> str:
        entry = next(entry for entry in response["results"] if entry.get("action") == "agent_chat_reply")
        return entry["reply_text"]

    def test_a_lookup_missing_its_source_is_never_started(self) -> None:
        from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat

        turn = self._turn_response({
            "outcome": "answer_now",
            "reply": "Checking now.",
            "proposalType": "calendar-summary",
            "changes": {"fields": {"timeWindow": "2026-09-05"}},
        })
        recovery = SimpleNamespace(output_text="Your calendar isn't connected yet - reply \"connect my calendar\" and I'll send the link.")
        calls: list[str] = []
        original = WhatsAppAgentChat._api

        def recording(self_chat, method, path, payload=None, **kwargs):
            calls.append(path)
            return original(self_chat, method, path, payload, **kwargs)

        with (
            mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=[turn, recovery]),
            mock.patch.object(WhatsAppAgentChat, "_api", recording),
        ):
            response = self._post_webhook(inbound_text_payload("am I free tomorrow?", message_id="wamid.pre-1"))

        self.assertEqual(self._reply(response), recovery.output_text)
        self.assertNotIn("/api/agent/proposals/run", calls)
        self.assertIn("/api/agent/recover", calls)

    def test_a_question_older_than_a_day_is_no_longer_open(self) -> None:
        from packages.infrastructure.portal_auth.server import PortalSession  # noqa: F401 - import check only

        self.database.save_whatsapp_agent_pending(
            user_id=int(self.user["id"]),
            pending={
                "kind": "disconnect",
                "question": "Disconnect Gmail?",
                "connectionIds": ["conn-1"],
                "names": ["Gmail"],
                "askedAt": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            },
        )
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=self._turn_response({"outcome": "message", "reply": "Morning! What would you like?"}),
        ) as model:
            response = self._post_webhook(inbound_text_payload("yes", message_id="wamid.pre-2"))

        # A stale yes is a message for the model, not consent to last week's disconnect.
        model.assert_called_once()
        self.assertEqual(self._reply(response), "Morning! What would you like?")
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))
