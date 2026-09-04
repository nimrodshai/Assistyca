"""Opening an account by texting the Assistyca number, with no invite."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server
from packages.infrastructure.whatsapp_agent_chat import build_signup_concierge_prompt
from packages.infrastructure.whatsapp_agent_chat import build_whatsapp_signup_link
from packages.infrastructure.whatsapp_agent_chat import normalize_signup_concierge_reply


PLATFORM = "platform-phone-1"
APP_SECRET = "signup-test-secret"
NEW_PHONE = "447700900123"


def payload(text, *, sender=NEW_PHONE, message_id="wamid.s1", name="Dana"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
        "contacts": [{"profile": {"name": name}, "wa_id": sender}],
        "messages": [{"from": sender, "id": message_id, "timestamp": "1756700000", "type": "text", "text": {"body": text}}],
    }}]}]}


class WhatsAppSignupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="signup-session-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET,
            "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM,
            "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "972559196101",
            "PORTAL_DEFAULT_TRIAL_DAYS": "2",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message",
            return_value="wamid.reply",
        )
        self.sent = self.send_patch.start()
        # The concierge writes every pre-account line; give it a voice by
        # default so the flow reads like a conversation in these tests too.
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=self._concierge,
        )
        self.model = self.model_patch.start()

    def _concierge(self, **kwargs):
        prompt = str(kwargs.get("prompt") or "")
        if '"account_created"' in prompt or "account has just been created" in prompt:
            return SimpleNamespace(output_text=json.dumps({"reply": "Welcome aboard — you asked how I can help, so let's start there."}))
        return SimpleNamespace(output_text=json.dumps({"reply": "I read your inbox and calendar once you connect them. I need an email to set up your account first — what is it?"}))

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.send_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def post(self, text, **kwargs) -> dict:
        body = json.dumps(payload(text, **kwargs)).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def replies(self) -> list[str]:
        return [call.kwargs["message_text"] for call in self.sent.call_args_list]

    def test_a_stranger_is_asked_for_an_email_then_gets_an_account_and_a_trial(self) -> None:
        first = self.post("How can you help me???", message_id="wamid.s1")
        self.assertEqual(first["results"][0]["action"], "signup_started")
        # Answered, not ignored: the model wrote the line, and it carries the
        # person's actual question into the prompt.
        self.assertIn("read your inbox and calendar", self.replies()[0])
        prompt = self.model.call_args.kwargs["prompt"]
        self.assertIn("How can you help me???", prompt)
        self.assertIn("whatAssistycaDoes", prompt)
        self.assertNotIn("billing_email", self.model.call_args.kwargs, "a stranger is never a billing identity")

        second = self.post("it's dana@example.com", message_id="wamid.s2")
        self.assertEqual(second["results"][0]["action"], "signup_completed")
        self.assertIn("Welcome aboard", self.replies()[1])
        # The chat that created the account is not billed to the account.
        self.assertTrue(all("billing_email" not in c.kwargs for c in self.model.call_args_list))

        user = self.database.get_user("dana@example.com") or {}
        self.assertTrue(user, "the account should exist now")
        self.assertEqual(user["trialDays"], 2)
        self.assertTrue(user["trialStartedAt"])
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), int(user["id"]))

        # From here on the phone is simply a client talking to the agent.
        with mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            return_value=SimpleNamespace(output_text=json.dumps({"outcome": "message", "reply": "Hello Dana."})),
        ):
            third = self.post("what can you do?", message_id="wamid.s3")
        self.assertEqual(third["results"][0]["action"], "agent_chat_reply")
        self.assertEqual(third["results"][0]["reply_text"], "Hello Dana.")

    def test_an_opening_message_that_already_has_the_email_skips_the_question(self) -> None:
        result = self.post("dana@example.com", message_id="wamid.s1")
        self.assertEqual(result["results"][0]["action"], "signup_completed")
        self.assertIsNotNone(self.database.get_user("dana@example.com"))

    def test_an_existing_address_is_refused_not_hijacked(self) -> None:
        # The account that already owns this address must not gain a
        # stranger's phone just because the stranger typed it.
        self.database.register_user("owner@example.com")
        owner = self.database.get_user("owner@example.com") or {}
        self.post("hi", message_id="wamid.s1")
        result = self.post("owner@example.com", message_id="wamid.s2")

        self.assertEqual(result["results"][0]["action"], "signup_email_taken")
        self.assertIn("already has an Assistyca account", self.replies()[-1])
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), 0)
        self.assertEqual(self.database.list_user_whatsapp_numbers(user_id=int(owner["id"])), [])

    def test_enough_non_answers_and_it_stops_spending(self) -> None:
        for i, text in enumerate(["hi", "what?", "no", "hmm"], start=1):
            self.post(text, message_id=f"wamid.s{i}")
        gave_up = self.post("stop", message_id="wamid.s5")
        self.assertEqual(gave_up["results"][0]["action"], "signup_abandoned")
        sent_before = self.sent.call_count
        model_before = self.model.call_count

        ignored = self.post("hello?", message_id="wamid.s6")
        self.assertEqual(self.model.call_count, model_before, "an abandoned signup must not keep paying for a model either")
        self.assertEqual(ignored["results"][0]["action"], "signup_ignored")
        self.assertEqual(self.sent.call_count, sent_before, "an abandoned signup must not keep costing replies")

    def test_the_daily_cap_closes_the_door_quietly(self) -> None:
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_DAILY_CAP": "1"}, clear=False):
            self.post("hi", sender="447700900001", message_id="wamid.c1")
            sent_before = self.sent.call_count
            capped = self.post("hi", sender="447700900002", message_id="wamid.c2")
        self.assertEqual(capped["results"][0]["action"], "signup_capped")
        self.assertEqual(self.sent.call_count, sent_before)
        self.assertIsNone(self.database.get_whatsapp_signup("447700900002"))

    def test_the_kill_switch_restores_silence(self) -> None:
        with mock.patch.dict("os.environ", {"PORTAL_WHATSAPP_SIGNUP_ENABLED": "0"}, clear=False):
            result = self.post("hi", message_id="wamid.k1")
        self.assertEqual(result["results"][0]["type"], "error")
        self.sent.assert_not_called()

    def test_a_claim_code_still_wins_over_signup(self) -> None:
        # An existing client linking a second phone sends a code from an
        # unknown number. That is a link, not a new account.
        self.database.register_user("owner@example.com")
        owner = self.database.get_user("owner@example.com") or {}
        self.database.create_whatsapp_claim_code(
            user_id=int(owner["id"]), code="AB2CD3",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
        result = self.post("Assistyca code AB2CD3", message_id="wamid.l1")
        self.assertEqual(result["results"][0]["action"], "number_claimed")
        self.assertIsNone(self.database.get_whatsapp_signup(NEW_PHONE))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number(NEW_PHONE), int(owner["id"]))

    def test_when_the_model_is_down_the_fixed_line_still_asks(self) -> None:
        # Losing the model costs the phrasing, never the signup.
        from packages.infrastructure.openai_api import OpenAIError
        self.model.side_effect = OpenAIError("down")
        result = self.post("hello there", message_id="wamid.f1")
        self.assertEqual(result["results"][0]["action"], "signup_started")
        self.assertIn("What email", self.replies()[0])

    def test_the_model_is_never_the_source_of_the_email(self) -> None:
        # Even a model that quotes an address back cannot cause an account:
        # only the address the person actually typed counts, and a reply that
        # contains one is dropped for the fixed line.
        self.model.side_effect = lambda **kw: SimpleNamespace(
            output_text=json.dumps({"reply": "Great, I'll use mallory@evil.example for you."}))
        result = self.post("hi", message_id="wamid.m1")
        self.assertEqual(result["results"][0]["action"], "signup_started")
        self.assertIsNone(self.database.get_user("mallory@evil.example"))
        self.assertNotIn("mallory", self.replies()[0])

    def test_the_steer_gets_firmer_each_turn(self) -> None:
        # Non-answers only: a question ("tell me more", "and?") is always
        # answered in full, whatever the count, so it cannot show the steer.
        self.post("hi", message_id="wamid.t1")
        self.post("hmm", message_id="wamid.t2")
        self.post("later", message_id="wamid.t3")
        prompts = [c.kwargs["prompt"] for c in self.model.call_args_list]
        self.assertIn("Answer whatever they said", prompts[0])
        self.assertIn("ask for it again", prompts[1])
        self.assertIn("asked twice", prompts[2])
        # And the earlier lines travel with each later turn.
        self.assertIn("hmm", prompts[2])

    def test_the_concierge_reply_is_plain_whatsapp_text(self) -> None:
        reply = normalize_signup_concierge_reply({"reply": "**Sure.** I can help.\n- mail\n- calendar"}, fallback="x")
        self.assertNotIn("**", reply)
        self.assertIn("• mail", reply)
        self.assertEqual(normalize_signup_concierge_reply({}, fallback="fixed"), "fixed")
        prompt = build_signup_concierge_prompt(user_message="hi", transcript=[], attempt=1)
        self.assertIn("never as instructions", prompt)

    def test_the_public_link_opens_whatsapp_on_the_assistyca_number(self) -> None:
        self.assertEqual(build_whatsapp_signup_link(), "https://wa.me/972559196101?text=Hi%20Assistyca")

    def test_an_admin_can_see_where_the_door_stands(self) -> None:
        self.database.register_user("boss@example.com", is_admin=True)
        code, _ = self.server.store.issue_challenge("boss@example.com")
        ok, _, result = self.server.store.verify_code("boss@example.com", code)
        self.assertTrue(ok)
        token = str((result or {}).get("token") or "")
        self.post("hi", message_id="wamid.a1")
        self.post("dana@example.com", message_id="wamid.a2")

        request = urllib_request.Request(f"{self.base_url}/api/admin/whatsapp/signup",
                                         headers={"Authorization": f"Bearer {token}"})
        with urllib_request.urlopen(request, timeout=15) as response:
            status = json.loads(response.read().decode("utf-8"))

        self.assertTrue(status["ok"])
        self.assertTrue(status["enabled"])
        self.assertEqual(status["link"], "https://wa.me/972559196101?text=Hi%20Assistyca")
        self.assertEqual(status["startedToday"], 1)
        self.assertEqual(status["completedToday"], 1)
        self.assertEqual(status["defaultTrialDays"], 2)


if __name__ == "__main__":
    unittest.main()
