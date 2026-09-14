"""A question that waited on a sign-in, and was offered back once it arrived.

Asking something that needs Gmail when Google has let go of the saved sign-in
used to end twice over: the link went out, and the question went nowhere. The
person signed in and typed the whole thing again. Here the question is kept,
and signing in offers it back in their own words - answered on a yes, dropped
on a no, and never run behind their back.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
import urllib.parse as urllib_parse
import urllib.request as urllib_request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.portal_auth.server import PortalConfig, create_server, sign_oauth_state_payload
from packages.infrastructure.whatsapp_agent_chat import _pending_is_fresh, build_resume_ask


VAULT_KEY = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
PLATFORM = "platform-phone-1"
APP_SECRET = "held-test-secret"
SESSION_SECRET = "held-session-secret-that-is-long-enough"
PHONE = "447700900123"
EMAIL = "dana@gmail.com"
QUESTION = "How much did I pay to Apple on aug?"
HANDLER = "packages.infrastructure.portal_auth.server.PortalAuthHandler"


def _loop_round(*items: dict, reply: dict | None = None) -> SimpleNamespace:
    outputs = [{"type": "reasoning", "summary": []}, *items]
    text = ""
    if reply is not None:
        text = json.dumps({"reply": "", "claimsCompleted": [], "rememberFact": None, "forgetFact": None,
                           "answersOpenQuestion": None, **reply})
        outputs.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return SimpleNamespace(output_text=text, raw_response={"output": outputs}, input_tokens=10, output_tokens=5)


def _tool_call(name: str, call_id: str, **args) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)}


class TheAskItselfTests(unittest.TestCase):
    """What the offer says, and how the wait changes it."""

    def test_the_question_comes_back_in_the_person_s_own_words(self) -> None:
        ask = build_resume_ask(QUESTION, asked_at=datetime.now(timezone.utc).isoformat(),
                               opening="Your Gmail and calendar are connected.")
        self.assertIn("Your Gmail and calendar are connected.", ask)
        self.assertIn(f'"{QUESTION}"', ask)
        self.assertIn("want me to pull that up now?", ask)

    def test_an_hour_later_it_asks_whether_they_still_care(self) -> None:
        an_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=5)).isoformat()
        ask = build_resume_ask(QUESTION, asked_at=an_hour_ago, opening="Your Gmail and calendar are connected.")
        self.assertIn("A while back you asked", ask)
        self.assertIn("do you still want that answer?", ask)
        self.assertIn(f'"{QUESTION}"', ask)

    def test_a_question_that_waited_a_week_is_still_worth_asking_about(self) -> None:
        # Waiting is not a reason to throw it away; it is a reason to ask
        # differently. Every other open question still goes stale on its own.
        week_old = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        self.assertTrue(_pending_is_fresh({"kind": "held_question", "askedAt": week_old}))
        self.assertTrue(_pending_is_fresh({"kind": "resume_question", "askedAt": week_old}))
        self.assertFalse(_pending_is_fresh({"kind": "calendar_choice", "askedAt": week_old}))

    def test_nothing_held_is_nothing_asked(self) -> None:
        self.assertEqual(build_resume_ask("", opening="Connected."), "")


class HeldQuestionOverWhatsAppTests(unittest.TestCase):
    """The whole round trip: blocked question, sign-in, offer, yes or no."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db",
            session_secret=SESSION_SECRET,
            credential_encryption_key=VAULT_KEY,
            google_oauth_client_id="google-client",
            google_oauth_client_secret="google-secret",
        ))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user(EMAIL)
        self.user = self.database.get_user(EMAIL) or {}
        self.database.link_user_whatsapp_number(user_id=int(self.user["id"]), wa_id=PHONE)
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET,
            "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM,
            "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "972559196101",
            "PUBLIC_BASE_URL": "https://assistyca.example",
            "WHATSAPP_AGENT_LOOP_ENABLED": "1",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.reply")
        self.sent = self.send_patch.start()
        self.model_patch = mock.patch("packages.infrastructure.portal_auth.server.call_openai_response")
        self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.send_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    # -- the wires ---------------------------------------------------------

    def _webhook(self, text: str, *, message_id: str) -> dict:
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
            "contacts": [{"profile": {"name": "Dana"}, "wa_id": PHONE}],
            "messages": [{"from": PHONE, "id": message_id, "timestamp": "1756700000", "type": "text", "text": {"body": text}}],
        }}]}]}
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def _callback(self) -> int:
        state = sign_oauth_state_payload(SESSION_SECRET, {
            "version": 1, "channel": "whatsapp", "provider": "google", "email": EMAIL, "waId": PHONE,
            "purpose": "connect", "issuedAt": int(time.time()), "nonce": "n", "scopeIds": ["gmail", "calendar"]})
        query = urllib_parse.urlencode({"code": "auth-code", "state": state})
        with (
            mock.patch(f"{HANDLER}._exchange_google_calendar_oauth_code",
                       return_value={"access_token": "at", "refresh_token": "rt", "scope": "x"}),
            mock.patch(f"{HANDLER}._save_google_oauth_connections", return_value=[{"accountAddress": EMAIL}]),
        ):
            with urllib_request.urlopen(
                f"{self.base_url}/api/oauth/google/calendar/callback?{query}", timeout=15
            ) as response:
                return int(response.status)

    def _texts(self) -> list[str]:
        return [c.kwargs.get("message_text") for c in self.sent.call_args_list if c.kwargs.get("message_text")]

    def _pending(self) -> dict:
        return self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])) or {}

    def _ask_something_that_needs_gmail(self) -> None:
        """The question in the screenshot: Gmail is wanted, Gmail is not there."""

        self.model.side_effect = [
            _loop_round(_tool_call("search_receipts", "c1", what="Apple receipts in August", vendor="Apple", months="2026-08")),
            _loop_round(_tool_call("connect_link", "c2", provider="google")),
            _loop_round(reply={"reply": "I can't total Apple for August yet - sign in again here."}),
        ]
        self._webhook(QUESTION, message_id="wamid.q1")

    # -- what it does ------------------------------------------------------

    def test_a_question_blocked_by_a_sign_in_is_kept_not_dropped(self) -> None:
        self._ask_something_that_needs_gmail()
        pending = self._pending()
        self.assertEqual(pending.get("kind"), "held_question")
        self.assertEqual(pending.get("text"), QUESTION)
        self.assertEqual(pending.get("source"), "mailbox")

    def test_signing_in_offers_the_question_back_instead_of_asking_for_it_again(self) -> None:
        self._ask_something_that_needs_gmail()
        self.assertEqual(self._callback(), 200)

        offer = self._texts()[-1]
        self.assertIn(f'"{QUESTION}"', offer)
        self.assertIn("want me to pull that up now?", offer)
        self.assertNotIn("Ask me anything about your inbox", offer)
        self.assertEqual(self._pending().get("kind"), "resume_question")
        # And the offer is in the transcript, so the model can see what was asked.
        history = self.database.list_recent_whatsapp_agent_messages(user_id=int(self.user["id"]), limit=5)
        self.assertEqual(history[-1]["role"], "assistant")
        self.assertIn(QUESTION, history[-1]["text"])

    def test_yes_answers_the_question_they_never_retyped(self) -> None:
        self._ask_something_that_needs_gmail()
        self._callback()

        asked: list[str] = []

        def answering(**kwargs):
            context = str(kwargs["input"][0]["content"])
            asked.append(json.loads(context.split("CONTEXT\n", 1)[1])["latestUserMessage"])
            return _loop_round(reply={"reply": "You paid Apple 271.90 in August."})

        self.model.side_effect = answering
        result = self._webhook("yes", message_id="wamid.q2")

        self.assertEqual(result["results"][0]["outcome"], "resume_question_answered")
        self.assertEqual(asked, [QUESTION], "the held question runs, not the word yes")
        self.assertIn("271.90", self._texts()[-1])
        self.assertEqual(self._pending(), {}, "nothing is left waiting once it is answered")

    def test_no_lets_it_go_without_running_anything(self) -> None:
        self._ask_something_that_needs_gmail()
        self._callback()
        self.model.side_effect = AssertionError("a no must not reach the model")

        result = self._webhook("no", message_id="wamid.q3")

        self.assertEqual(result["results"][0]["outcome"], "resume_question_declined")
        self.assertIn("let that one go", self._texts()[-1])
        self.assertEqual(self._pending(), {})

    def test_a_calendar_picker_settles_first_and_the_question_is_offered_after_it(self) -> None:
        # Signing in can raise a question of ours - which calendars to read.
        # That one is in front of them now, so it is answered first; theirs is
        # offered once it is settled, and still not run unasked.
        self.database.save_platform_connection(
            EMAIL, platform="calendar", auth_type="oauth", secret_ciphertext="cipher", secret_hint="••••",
            provider="google_calendar",
            metadata={"availableCalendars": [{"id": "primary", "label": "Dana"},
                                             {"id": "work@group.calendar.google.com", "label": "Work"}]},
        )
        self._ask_something_that_needs_gmail()
        self._callback()

        self.assertIn("One thing before I read your calendar", self._texts()[-1])
        pending = self._pending()
        self.assertEqual(pending.get("kind"), "calendar_choice")
        self.assertEqual(pending.get("resumeQuestion"), QUESTION, "their question rides along with our own")

        with mock.patch(f"{HANDLER}._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from http import HTTPStatus
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                json_response(handler, HTTPStatus.OK, {"ok": True, "selectedCalendars": parse_json_body(handler)["calendars"]})

            save.side_effect = _save
            self.model.side_effect = AssertionError("the held question must not run before they say so")
            self._webhook("all", message_id="wamid.q5")

        offer = self._texts()[-1]
        self.assertIn("I'll read", offer)
        self.assertIn(f'"{QUESTION}"', offer)
        self.assertEqual(self._pending().get("kind"), "resume_question")

    def test_anything_else_is_answered_and_the_offer_stays_up(self) -> None:
        # An open question never swallows a message that is not an answer to it.
        self._ask_something_that_needs_gmail()
        self._callback()
        self.model.side_effect = [_loop_round(reply={"reply": "Tuesday looks clear."})]

        self._webhook("what's on tuesday?", message_id="wamid.q4")

        self.assertIn("Tuesday looks clear.", self._texts()[-1])
        self.assertEqual(self._pending().get("kind"), "resume_question", "the offer is still standing")
        context = json.loads(str(self.model.call_args.kwargs["input"][0]["content"]).split("CONTEXT\n", 1)[1])
        self.assertIn(QUESTION, context["openQuestion"]["question"], "the model can see what is on the table")


if __name__ == "__main__":
    unittest.main()
