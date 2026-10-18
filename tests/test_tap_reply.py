"""The line that answers a tap on "remind me again": written by the model
from what code knows, guarded in code, and assembled when it cannot be."""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from contextlib import redirect_stdout
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from packages.infrastructure.agent_turns import TAP_REPLY_PATH
from packages.infrastructure.agent_turns import TURN_FOLLOW_UP_PATHS
from packages.infrastructure.agent_turns import describe_response
from packages.infrastructure.openai_api import OpenAIError
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.tap_reply import TAP_REPLY_COMPLEXITY
from packages.infrastructure.tap_reply import TAP_REPLY_INSTRUCTIONS
from packages.infrastructure.tap_reply import build_tap_reply_prompt
from packages.infrastructure.tap_reply import guard_tap_reply
from packages.infrastructure.tap_reply import tap_reply_fallback
from packages.infrastructure.task_complexity import TaskComplexity
from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat

UTC = timezone.utc
PHONE = "972500000001"


class WordsTests(unittest.TestCase):
    def test_the_assembled_lines_in_both_languages(self) -> None:
        self.assertEqual(tap_reply_fallback("scheduled", "07:55", "en"), "Got it - I'll remind you again at 07:55.")
        self.assertEqual(tap_reply_fallback("already", "07:55", "en"), "Already set - I'll remind you at 07:55.")
        self.assertEqual(tap_reply_fallback("imminent", "08:00", "en"), "It's at 08:00 - time to head out.")
        self.assertEqual(tap_reply_fallback("scheduled", "07:55", "he"), "סגור, אזכיר שוב ב-07:55.")
        self.assertEqual(tap_reply_fallback("already", "07:55", "he"), "כבר מסודר, אזכיר ב-07:55.")
        self.assertIn("08:00", tap_reply_fallback("imminent", "08:00", "he"))

    def test_only_a_plain_line_with_the_time_is_kept(self) -> None:
        fallback = "Got it - I'll remind you again at 07:55."
        self.assertEqual(guard_tap_reply("Sure - 07:55 for Tom 🙂", clock="07:55", fallback=fallback), "Sure - 07:55 for Tom 🙂")
        for written in (
            "",
            "Sure, I'll remind you a little before.",
            "Sure - 07:55. Anything else?",
            "Sure - 07:55.\nHave a good drive.",
            "Sure - 07:55, see https://assistyca.com",
            "Queued for 07:55 by the server.",
            "Sure - 07:55 " + "x" * 140,
        ):
            self.assertEqual(guard_tap_reply(written, clock="07:55", fallback=fallback), fallback, written)

    def test_the_model_gets_the_facts_and_the_voice(self) -> None:
        self.assertEqual(TAP_REPLY_COMPLEXITY, TaskComplexity.MEDIUM)
        self.assertIn("Voice: calm", TAP_REPLY_INSTRUCTIONS)
        self.assertIn("Don't explain, don't thank, don't ask anything", TAP_REPLY_INSTRUCTIONS)
        prompt = build_tap_reply_prompt(
            outcome="scheduled", clock="07:55", drive_at="08:00", about="take Tom - Kindergarten at 08:00",
            language="he", address_form="a woman",
            conversation=[{"role": "user", "text": str(n)} for n in range(6)],
        )
        context = json.loads(prompt.split("CONTEXT\n", 1)[1])
        self.assertEqual(context["outcome"], "scheduled")
        self.assertEqual(context["clock"], "07:55")
        self.assertEqual(context["driveAt"], "08:00")
        self.assertEqual(context["addressAs"], "a woman")
        self.assertEqual([item["text"] for item in context["recentConversation"]], ["2", "3", "4", "5"])

    def test_the_route_is_a_follow_up_of_its_own(self) -> None:
        self.assertIn(TAP_REPLY_PATH, TURN_FOLLOW_UP_PATHS)
        described = describe_response(TAP_REPLY_PATH, {}, 200, {"ok": True, "composed": False})
        self.assertEqual(described["outcome"], "tap_reply")
        self.assertTrue(described["fallback_used"])


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.env = mock.patch.dict(os.environ, {"PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "wa")}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        root = Path(__file__).resolve().parents[1]
        self.server = create_server("127.0.0.1", 0, root, PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db"))
        self.server.database.register_user("client@example.com")
        code, _ = self.server.store.issue_challenge("client@example.com")
        ok, _, result = self.server.store.verify_code("client@example.com", code)
        assert ok and result is not None
        self.token = result["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, payload: dict) -> tuple[int, dict]:
        request = urllib_request.Request(
            f"{self.base_url}{TAP_REPLY_PATH}", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_the_line_is_the_models_when_it_passes_the_guard(self) -> None:
        calls = []

        def fake_call(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="סגור, 07:55 לטום 🙂", model="m", input_tokens=1, output_tokens=1, incomplete_attempts=0, request_payload={})

        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=fake_call):
            status, payload = self._post({"outcome": "scheduled", "clock": "07:55", "driveAt": "08:00", "about": "take Tom", "language": "he"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["reply"], "סגור, 07:55 לטום 🙂")
        self.assertTrue(payload["composed"])
        self.assertEqual(calls[0]["instructions"], TAP_REPLY_INSTRUCTIONS)
        self.assertIn('"clock": "07:55"', calls[0]["prompt"])
        self.assertIn("reasoning", calls[0])

    def test_a_failed_or_unfit_line_falls_back(self) -> None:
        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=OpenAIError("no model")), \
             redirect_stdout(io.StringIO()):
            status, payload = self._post({"outcome": "already", "clock": "07:55", "language": "en"})
        self.assertEqual((status, payload["reply"], payload["composed"]), (200, "Already set - I'll remind you at 07:55.", False))
        unfit = SimpleNamespace(output_text="Want another one at 07:58?", model="m", input_tokens=1, output_tokens=1, incomplete_attempts=0, request_payload={})
        with mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", return_value=unfit):
            status, payload = self._post({"outcome": "scheduled", "clock": "07:55", "language": "en"})
        self.assertEqual(payload["reply"], "Got it - I'll remind you again at 07:55.")
        status, payload = self._post({"outcome": "sometime", "clock": "07:55"})
        self.assertEqual(status, 400)


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=PHONE)
        self.database.save_household_profile(user_id=self.user_id, address_form="f")
        due = datetime.now(UTC) + timedelta(minutes=30)
        self.word = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(UTC), timezone_name="Asia/Jerusalem",
            payload={"title": "Time to leave soon", "instruction": "x", "fallbackText": "Soon.", "oneOff": True,
                     "source": "family_week", "remindAgain": {"dueAt": due.isoformat(), "minutesBefore": 5,
                                                              "facts": ["take Tom - Kindergarten at 08:00"]}},
        )
        self.chat = WhatsAppAgentChat(
            database=self.database, connection={"userId": self.user_id, "email": "owner@example.com", "ownerWaId": PHONE},
            base_url="http://127.0.0.1:1", session_token_factory=lambda _email: "token",
        )

    def test_the_chat_sends_the_written_line_and_the_facts_go_to_the_server(self) -> None:
        sent_to_server = []

        def fake_api(method, path, payload=None):
            sent_to_server.append((path, payload))
            return {"ok": True, "reply": f"Sure - {payload['clock']} for Tom.", "composed": True}, 200

        with mock.patch.object(self.chat, "_api", side_effect=fake_api), \
             mock.patch.dict("os.environ", {"WHATSAPP_ALLOW_MOCK_SEND": "1"}, clear=False), \
             mock.patch("packages.infrastructure.whatsapp_agent_chat.send_assistyca_text", return_value="wamid.r") as send:
            result = self.chat.handle_message("Yes, 5 min before", message_type="button", interactive_id=f"remindagain:{self.word['id']}")
        self.assertEqual(result["outcome"], "remind_again_scheduled")
        [(path, payload)] = [call for call in sent_to_server if call[0] == TAP_REPLY_PATH]
        self.assertEqual(payload["outcome"], "scheduled")
        self.assertEqual(payload["about"], "take Tom - Kindergarten at 08:00")
        self.assertEqual(payload["addressForm"], "a woman")
        self.assertRegex(payload["clock"], r"^\d\d:\d\d$")
        self.assertRegex(payload["driveAt"], r"^\d\d:\d\d$")
        self.assertEqual(send.call_args.kwargs["text"], f"Sure - {payload['clock']} for Tom.")


if __name__ == "__main__":
    unittest.main()
