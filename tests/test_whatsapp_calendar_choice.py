"""Choosing calendars from WhatsApp, and never answering one message twice."""

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
from packages.infrastructure.whatsapp_agent_chat import (
    build_calendar_choice_interactive,
    build_calendar_choice_text,
    calendars_missing_colour,
    color_dot,
    looks_like_a_question,
    parse_calendar_choice,
)


PLATFORM = "platform-phone-1"
APP_SECRET = "cal-test-secret"
PHONE = "972507322341"
CALENDARS = [
    {"id": "primary", "label": "Nimrod", "color": "#039BE5"},
    {"id": "work@group.calendar.google.com", "label": "Work", "color": "#D50000"},
    {"id": "family@group.calendar.google.com", "label": "Family", "color": "#33B679"},
]


class HelperTests(unittest.TestCase):
    def test_colours_become_the_nearest_dot(self) -> None:
        self.assertEqual(color_dot("#D50000"), "🔴")
        self.assertEqual(color_dot("#33B679"), "🟢")
        self.assertEqual(color_dot("#039BE5"), "🔵")
        self.assertEqual(color_dot(""), "⚪")
        self.assertEqual(color_dot("nonsense"), "⚪")

    def test_the_fallback_text_is_numbered_with_a_dot_per_calendar(self) -> None:
        text = build_calendar_choice_text(CALENDARS, resuming="what's on next week")
        self.assertIn("1. 🔵 Nimrod", text)
        self.assertIn("2. 🔴 Work", text)
        self.assertIn("3. 🟢 Family", text)
        self.assertIn("*all*", text)
        self.assertIn("straight away", text)

    def test_the_picker_behaves_like_checkboxes(self) -> None:
        fresh = build_calendar_choice_interactive(CALENDARS)
        rows = fresh["action"]["sections"][0]["rows"]
        self.assertEqual([r["id"] for r in rows], ["calpick:1", "calpick:2", "calpick:3", "calpick:all"])
        self.assertNotIn("Done", " ".join(r["title"] for r in rows), "nothing to confirm before a tap")
        self.assertTrue(all(len(r["title"]) <= 24 for r in rows))

        partial = build_calendar_choice_interactive(CALENDARS, selected=["work@group.calendar.google.com"])
        rows = partial["action"]["sections"][0]["rows"]
        self.assertEqual(rows[0]["id"], "calpick:done")
        self.assertIn("Work", rows[0]["description"])
        self.assertTrue(rows[2]["title"].startswith("✓ 🔴"), rows[2]["title"])
        self.assertFalse(rows[1]["title"].startswith("✓"))
        self.assertEqual(partial["header"]["text"], "Which calendars should I read?")

    def test_an_address_label_is_shortened_for_the_row_and_kept_in_full_beneath(self) -> None:
        picker = build_calendar_choice_interactive([{"id": "primary", "label": "nimrod.shai@gmail.com", "color": "#039BE5"}])
        row = picker["action"]["sections"][0]["rows"][0]
        self.assertEqual(row["title"], "🔵 nimrod.shai")
        self.assertEqual(row["description"], "nimrod.shai@gmail.com")

    def test_a_cached_list_without_colours_is_worth_asking_google_again(self) -> None:
        self.assertTrue(calendars_missing_colour([{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]))
        self.assertFalse(calendars_missing_colour(CALENDARS))
        self.assertFalse(calendars_missing_colour([]))
        self.assertEqual(color_dot("#616161"), "⚫", "graphite is a dark grey, not brown")
        self.assertEqual(color_dot("#BDBDBD"), "⚪", "a light grey reads as white, not yellow")

    def test_a_reply_is_read_as_numbers_names_all_or_a_tap(self) -> None:
        ids = lambda chosen: [c["id"] for c in chosen]  # noqa: E731
        self.assertEqual(ids(parse_calendar_choice("1, 3", CALENDARS)), ["primary", "family@group.calendar.google.com"])
        self.assertEqual(ids(parse_calendar_choice("work and family", CALENDARS)), ["work@group.calendar.google.com", "family@group.calendar.google.com"])
        self.assertEqual(len(parse_calendar_choice("all", CALENDARS)), 3)
        self.assertEqual(ids(parse_calendar_choice("", CALENDARS, interactive_id="calpick:2")), ["work@group.calendar.google.com"])
        self.assertEqual(len(parse_calendar_choice("", CALENDARS, interactive_id="calpick:all")), 3)
        self.assertEqual(parse_calendar_choice("hmm", CALENDARS), [])

    def test_a_question_is_recognised_however_the_email_count_stands(self) -> None:
        self.assertTrue(looks_like_a_question("How can you help me?"))
        self.assertTrue(looks_like_a_question("what can you do"))
        self.assertFalse(looks_like_a_question("nimrod@example.com"))
        self.assertFalse(looks_like_a_question("ok"))


class CalendarChoiceOverWhatsAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="cal-session-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.link_user_whatsapp_number(user_id=int(self.user["id"]), wa_id=PHONE)
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET, "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM, "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.reply")
        self.sent = self.send_patch.start()
        # The agent asks for a calendar summary; the runner is a stand-in that
        # first demands a choice and, once one exists, answers.
        self.model_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.call_openai_response",
            side_effect=self._model)
        self.model = self.model_patch.start()
        self.runner_patch = mock.patch(
            "packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_agent_proposal_run",
            side_effect=self._runner, autospec=True)
        self.runner = self.runner_patch.start()
        self.available = list(CALENDARS)

    def tearDown(self) -> None:
        self.runner_patch.stop(); self.model_patch.stop(); self.send_patch.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp_dir.cleanup()

    def _model(self, **kwargs):
        prompt = str(kwargs.get("prompt") or "")
        if kwargs.get("tool_name") == "portal_answer_composer":
            return SimpleNamespace(output_text="You have 4 meetings next week; Tuesday is the busy one.")
        return SimpleNamespace(output_text=json.dumps({
            "outcome": "answer_now", "proposalType": "calendar-summary",
            "reply": "Let me check.", "changes": {"fields": {"timeWindow": "next week"}}}))

    def _runner(self, handler):
        from packages.infrastructure.portal_auth.server import json_response, parse_json_body
        from http import HTTPStatus
        self._last_run_body = parse_json_body(handler)
        chosen = getattr(self, "_chosen", None)
        if not chosen:
            json_response(handler, HTTPStatus.CONFLICT, {"ok": False, "error": "calendar_selection_required",
                          "message": "Before I read your calendar I need to know which calendars to look at.",
                          "availableCalendars": self.available})
            return
        json_response(handler, HTTPStatus.OK, {"ok": True, "answer": f"4 meetings across {len(chosen)} calendar(s).", "answerRecords": []})

    def _post(self, text=None, *, message_id, interactive_id=""):
        message = {"from": PHONE, "id": message_id, "timestamp": "1756700000"}
        if interactive_id:
            message.update({"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": interactive_id, "title": "x"}}})
        else:
            message.update({"type": "text", "text": {"body": text}})
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
            "contacts": [{"profile": {"name": "Nimrod"}, "wa_id": PHONE}], "messages": [message]}}]}]}
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def _texts(self):
        return [c.kwargs.get("message_text") for c in self.sent.call_args_list if c.kwargs.get("message_text")]

    def _interactives(self):
        return [c.kwargs.get("interactive") for c in self.sent.call_args_list if c.kwargs.get("interactive")]

    def test_the_same_message_delivered_twice_is_answered_once(self) -> None:
        # Meta redelivers when we are slow. Both deliveries carry one id.
        first = self._post("hello", message_id="wamid.dup-1")
        second = self._post("hello", message_id="wamid.dup-1")
        self.assertEqual(first["results"][0]["action"], "agent_chat_reply")
        self.assertEqual(second["results"][0]["type"], "duplicate")
        self.assertEqual(self.model.call_count, 1, "the second delivery must not reach the model")

    def test_a_calendar_question_asks_with_the_picker_and_nothing_else(self) -> None:
        result = self._post("Can you summarize my next week meetings?", message_id="wamid.c1")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice")
        self.assertFalse(any("Which calendars" in t for t in self._texts()), "no numbered list beside the picker")
        picker = self._interactives()[-1]
        self.assertEqual(picker["type"], "list")
        self.assertEqual(picker["header"]["text"], "Which calendars should I read?")
        self.assertIn("straight away", picker["body"]["text"])
        rows = picker["action"]["sections"][0]["rows"]
        self.assertEqual(rows[1]["id"], "calpick:2")
        self.assertTrue(rows[1]["title"].startswith("🔴"))
        pending = self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"]))
        self.assertEqual(pending["question"], "Can you summarize my next week meetings?")

    def test_taps_toggle_and_done_confirms_several(self) -> None:
        self._post("what's on next week?", message_id="wamid.m1")
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            first = self._post(message_id="wamid.m2", interactive_id="calpick:2")
            self.assertEqual(first["results"][0]["outcome"], "calendar_choice_toggled")
            self.assertEqual(first["results"][0]["selected"], ["work@group.calendar.google.com"])
            picker = self._interactives()[-1]
            rows = picker["action"]["sections"][0]["rows"]
            self.assertEqual(rows[0]["id"], "calpick:done")
            self.assertTrue(rows[2]["title"].startswith("✓"))
            save.assert_not_called()

            second = self._post(message_id="wamid.m3", interactive_id="calpick:3")
            self.assertEqual(second["results"][0]["selected"], ["work@group.calendar.google.com", "family@group.calendar.google.com"])
            # Tapping a ticked one again removes it.
            third = self._post(message_id="wamid.m4", interactive_id="calpick:2")
            self.assertEqual(third["results"][0]["selected"], ["family@group.calendar.google.com"])

            done = self._post(message_id="wamid.m5", interactive_id="calpick:done")
        self.assertEqual(done["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual([c["id"] for c in self._chosen], ["family@group.calendar.google.com"])
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))
        self.assertIn("4 meetings", self._texts()[-1])

    def test_all_calendars_is_one_tap(self) -> None:
        self._post("what's on next week?", message_id="wamid.all1")
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            result = self._post(message_id="wamid.all2", interactive_id="calpick:all")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual(len(self._chosen), 3)

    def test_the_phone_asks_the_runner_for_calendar_colours(self) -> None:
        # Only this channel draws colours, so only this channel asks; the
        # portal's cached list stays authoritative (see test_calendar_summary).
        self._post("what's on next week?", message_id="wamid.col1")
        self.assertIs(self._last_run_body.get("refreshCalendarColours"), True)

    def test_when_the_picker_cannot_be_sent_the_words_go_instead(self) -> None:
        with mock.patch("packages.infrastructure.whatsapp_agent_chat.send_assistyca_interactive", return_value=""):
            self._post("what's on next week?", message_id="wamid.fb1")
        self.assertTrue(any("1. 🔵 Nimrod" in t for t in self._texts()))

    def test_answering_with_numbers_saves_the_choice_and_answers_the_question_itself(self) -> None:
        self._post("Can you summarize my next week meetings?", message_id="wamid.n1")
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                payload = parse_json_body(handler)
                self._chosen = payload["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True, "selectedCalendars": payload["calendars"]})
            save.side_effect = _save
            result = self._post("1, 3", message_id="wamid.n2")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual([c["id"] for c in self._chosen], ["primary", "family@group.calendar.google.com"])
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))
        texts = self._texts()
        self.assertTrue(any("I'll read Nimrod, Family" in t for t in texts))
        self.assertIn("4 meetings", texts[-1], "the interrupted question is answered, not asked for again")

    def test_a_tap_on_the_picker_chooses_that_calendar(self) -> None:
        self._post("what's on next week?", message_id="wamid.t1")
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            self._post(message_id="wamid.t2", interactive_id="calpick:2")
            result = self._post(message_id="wamid.t3", interactive_id="calpick:done")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual([c["id"] for c in self._chosen], ["work@group.calendar.google.com"])

    def test_one_calendar_is_no_question_at_all(self) -> None:
        self.available = [CALENDARS[0]]
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            result = self._post("what's on next week?", message_id="wamid.one-1")
        self.assertEqual(result["results"][0]["outcome"], "answer_now")
        self.assertIn("4 meetings", self._texts()[-1])
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))
        self.assertFalse(any("Which calendars" in t for t in self._texts()))

    def test_an_unclear_answer_asks_again_without_losing_the_question(self) -> None:
        self._post("what's on next week?", message_id="wamid.u1")
        before = len(self._interactives())
        result = self._post("erm", message_id="wamid.u2")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_retry")
        self.assertEqual(len(self._interactives()), before + 1, "the picker is offered again")
        self.assertEqual(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"]))["question"], "what's on next week?")


class SignupWarmthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="warm-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET, "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM, "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False); self.env.start()
        self.send_patch = mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.r"); self.send_patch.start()
        self.model_patch = mock.patch("packages.infrastructure.portal_auth.server.call_openai_response",
                                      return_value=SimpleNamespace(output_text=json.dumps({"reply": "Hello!"}))); self.model = self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop(); self.send_patch.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp_dir.cleanup()

    def _post(self, text, message_id):
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1555", "phone_number_id": PLATFORM},
            "contacts": [{"profile": {"name": "Dana"}, "wa_id": "447700900123"}],
            "messages": [{"from": "447700900123", "id": message_id, "timestamp": "1756700000", "type": "text", "text": {"body": text}}]}}]}]}
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _age_signup(self, hours: float, attempts: int) -> None:
        with self.database._connection() as conn:  # noqa: SLF001 - fixture setup
            conn.execute("UPDATE whatsapp_signups SET updated_at = ?, attempts = ? WHERE wa_id = ?",
                         ((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(), attempts, "447700900123"))
            conn.commit()

    def test_coming_back_the_next_morning_is_a_fresh_conversation(self) -> None:
        self._post("hi", message_id="wamid.w1")
        self._age_signup(hours=8, attempts=4)
        self._post("How can you help me?", message_id="wamid.w2")
        prompt = self.model.call_args.kwargs["prompt"]
        self.assertIn("Answer whatever they said or asked", prompt)
        self.assertNotIn("asked twice", prompt)
        self.assertIn("three or four concrete things", prompt)

    def test_a_question_gets_the_full_answer_even_mid_escalation(self) -> None:
        self._post("hi", message_id="wamid.q1")
        self._age_signup(hours=0.1, attempts=3)
        self._post("what can you actually do?", message_id="wamid.q2")
        prompt = self.model.call_args.kwargs["prompt"]
        self.assertIn("Answer whatever they said or asked", prompt)
        self.assertIn("flights to Lisbon", prompt)


if __name__ == "__main__":
    unittest.main()
