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
    connection_display_name,
    connections_for_disconnect,
    parse_yes_no,
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
        self.assertEqual(ids(parse_calendar_choice("family please", CALENDARS)), ["family@group.calendar.google.com"])
        self.assertEqual(ids(parse_calendar_choice("Family and Nimrod", CALENDARS)), ["family@group.calendar.google.com", "primary"], "in the order they were named")
        self.assertEqual(len(parse_calendar_choice("all of them please", CALENDARS)), 3)
        self.assertEqual(len(parse_calendar_choice("both", CALENDARS)), 3)
        self.assertEqual(parse_calendar_choice("Am I free at 3?", CALENDARS), [], "a number inside a question is not a pick")
        self.assertEqual(parse_calendar_choice("I want to log out from google", CALENDARS), [])
        self.assertEqual(parse_calendar_choice("Just disconnect me from google", CALENDARS), [])
        self.assertEqual(parse_calendar_choice("the first one", CALENDARS), [], "words the parser cannot place are for the model")
        self.assertEqual(parse_calendar_choice("12", CALENDARS), [], "a number that is not on the list is not a pick")
        addressed = [{"id": "primary", "label": "nimrod.shai@gmail.com"}, {"id": "fam", "label": "Family"}]
        self.assertEqual(ids(parse_calendar_choice("nimrod.shai and family", addressed)), ["primary", "fam"], "the part before the @ names an address")

    def test_a_yes_or_no_is_only_the_whole_message(self) -> None:
        self.assertEqual(parse_yes_no("Yes!"), "yes")
        self.assertEqual(parse_yes_no("go ahead"), "yes")
        self.assertEqual(parse_yes_no("No, cancel"), "no")
        self.assertEqual(parse_yes_no("don't"), "no")
        self.assertEqual(parse_yes_no("yes, but which ones exactly?"), "", "a question first is not a yes")
        self.assertEqual(parse_yes_no("what's on tomorrow?"), "")

    def test_disconnect_words_map_onto_stored_connections(self) -> None:
        records = [
            {"id": "c1", "platform": "calendar", "provider": "google_calendar"},
            {"id": "m1", "platform": "email", "provider": "google_gmail", "accountAddress": "nimrod@gmail.com"},
            {"id": "m2", "platform": "email", "metadata": {"provider": "microsoft_outlook", "accountEmail": "nimrod@outlook.com"}},
            {"id": "d1", "platform": "drive"},
            {"id": "s1", "platform": "slack"},
        ]
        ids = lambda chosen: [c["id"] for c in chosen]  # noqa: E731
        self.assertEqual(ids(connections_for_disconnect(records, ["google"])), ["c1", "m1", "d1"])
        self.assertEqual(ids(connections_for_disconnect(records, ["outlook"])), ["m2"])
        self.assertEqual(ids(connections_for_disconnect(records, ["gmail", "calendar"])), ["c1", "m1"])
        self.assertEqual(connection_display_name(records[1]), "Gmail (nimrod@gmail.com)")
        self.assertEqual(connection_display_name(records[2]), "Outlook (nimrod@outlook.com)")
        self.assertEqual(connection_display_name(records[0]), "Google Calendar")

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

    def test_a_message_that_is_not_a_pick_is_understood_while_the_question_stays_open(self) -> None:
        # 2026-09-04: "I want to log out from google" got "I didn't catch
        # which ones" and the list again, three times. Words that are not
        # plainly a pick go to the model with the open question in view.
        self._post("what's on next week?", message_id="wamid.o1")
        user_id = int(self.user["id"])
        prompts: list[str] = []

        def _model(**kwargs):
            if kwargs.get("tool_name") == "portal_answer_composer":
                return SimpleNamespace(output_text="You have 4 meetings next week.")
            prompt = str(kwargs.get("prompt") or "")
            prompts.append(prompt)
            # The earlier message stays in recentConversation, so the
            # branch is chosen by the latest message alone.
            if '"latestUserMessage":"I want to log out from google"' in prompt:
                return SimpleNamespace(output_text=json.dumps({
                    "outcome": "message", "proposalType": "", "changes": {},
                    "reply": "To disconnect Google, open Connections in the portal and choose Disconnect."}))
            if '"latestUserMessage":"the first and the last"' in prompt:
                return SimpleNamespace(output_text=json.dumps({
                    "outcome": "calendar_choice", "proposalType": "", "changes": {},
                    "reply": "I'll read Nimrod and Family.", "calendarIndexes": [1, 3]}))
            return self._model(**kwargs)
        self.model.side_effect = _model

        result = self._post("I want to log out from google", message_id="wamid.o2")
        self.assertEqual(result["results"][0]["outcome"], "message")
        self.assertIn("Disconnect", self._texts()[-1])
        self.assertNotIn("didn't catch", self._texts()[-1])
        self.assertIn('"pendingChoice":{"kind":"calendar_choice","question":"what\'s on next week?"', prompts[-1])
        self.assertIn('{"index":2,"label":"Work"}', prompts[-1])
        self.assertEqual(self.database.get_whatsapp_agent_pending(user_id=user_id)["question"], "what's on next week?",
                         "the calendar question is still open")

        # A pick in words the parser cannot read is read by the model, and
        # saved exactly as if the numbers had been typed.
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            result = self._post("the first and the last", message_id="wamid.o3")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual([c["id"] for c in self._chosen], ["primary", "family@group.calendar.google.com"])
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=user_id))
        self.assertIn("4 meetings", self._texts()[-1])

    def test_a_pick_in_plain_words_never_needs_the_model(self) -> None:
        self._post("what's on next week?", message_id="wamid.p1")
        calls = self.model.call_count
        with mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._handle_platform_connection_calendars_post", autospec=True) as save:
            def _save(handler):
                from packages.infrastructure.portal_auth.server import json_response, parse_json_body
                from http import HTTPStatus
                self._chosen = parse_json_body(handler)["calendars"]
                json_response(handler, HTTPStatus.OK, {"ok": True})
            save.side_effect = _save
            result = self._post("family please", message_id="wamid.p2")
        self.assertEqual(result["results"][0]["outcome"], "calendar_choice_saved")
        self.assertEqual([c["id"] for c in self._chosen], ["family@group.calendar.google.com"])
        # The resumed question reaches the model; the pick itself never does.
        self.assertLessEqual(self.model.call_count - calls, 2)


class DisconnectOverWhatsAppTests(unittest.TestCase):
    """"Just disconnect me from google" disconnects, after a yes, from the chat."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="disc-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.database.link_user_whatsapp_number(user_id=int(self.user["id"]), wa_id=PHONE)
        self.database.save_platform_connection("owner@example.com", platform="calendar", auth_type="oauth",
                                               secret_ciphertext="cal-cipher", secret_hint="••••cal", provider="google_calendar")
        self.database.save_platform_connection("owner@example.com", platform="email", auth_type="oauth",
                                               secret_ciphertext="mail-cipher", secret_hint="••••mail", provider="google_gmail",
                                               account_address="nimrod@gmail.com", metadata={"accountEmail": "nimrod@gmail.com"})
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": APP_SECRET, "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": PLATFORM, "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False); self.env.start()
        self.send_patch = mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.r")
        self.sent = self.send_patch.start()
        self.model_patch = mock.patch("packages.infrastructure.portal_auth.server.call_openai_response", side_effect=self._model)
        self.model = self.model_patch.start()
        # Revoking is a call to Google; the test checks that it is asked for, not made.
        self.revoke_patch = mock.patch("packages.infrastructure.portal_auth.server.PortalAuthHandler._revoke_google_calendar_connection",
                                       autospec=True, return_value=(True, ""))
        self.revoke = self.revoke_patch.start()
        self.prompts: list[str] = []

    def tearDown(self) -> None:
        self.revoke_patch.stop(); self.model_patch.stop(); self.send_patch.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp_dir.cleanup()

    def _model(self, **kwargs):
        prompt = str(kwargs.get("prompt") or "")
        self.prompts.append(prompt)
        if '"latestUserMessage":"Just disconnect me from google"' in prompt:
            return SimpleNamespace(output_text=json.dumps({
                "outcome": "disconnect_command", "proposalType": "", "changes": {},
                "reply": "Disconnecting Google.", "disconnectTargets": ["google"]}))
        if '"latestUserMessage":"wait, what will stop working?"' in prompt:
            return SimpleNamespace(output_text=json.dumps({
                "outcome": "message", "proposalType": "", "changes": {},
                "reply": "Calendar questions and receipt searches, until you connect again."}))
        if '"latestUserMessage":"alright then, go on"' in prompt:
            return SimpleNamespace(output_text=json.dumps({
                "outcome": "confirm", "proposalType": "", "changes": {}, "reply": "Doing it now."}))
        return SimpleNamespace(output_text=json.dumps({
            "outcome": "message", "proposalType": "", "changes": {}, "reply": "Sure."}))

    _post = CalendarChoiceOverWhatsAppTests._post
    _texts = CalendarChoiceOverWhatsAppTests._texts

    def _connected(self):
        return sorted(c["platform"] for c in self.database.list_platform_connections("owner@example.com"))

    def test_a_disconnect_names_what_would_go_and_waits_for_a_yes(self) -> None:
        result = self._post("Just disconnect me from google", message_id="wamid.d1")
        self.assertEqual(result["results"][0]["outcome"], "disconnect_confirmation")
        self.assertIn("- disconnect_command:", self.prompts[-1], "the phone is offered the command")
        asked = self._texts()[-1]
        self.assertIn("Disconnect Google Calendar and Gmail (nimrod@gmail.com) from Assistyca?", asked)
        self.assertIn("*yes*", asked)
        self.assertEqual(self._connected(), ["calendar", "email"], "nothing goes before the yes")

        done = self._post("Yes", message_id="wamid.d2")
        self.assertEqual(done["results"][0]["outcome"], "disconnected")
        self.assertIn("Google Calendar and Gmail (nimrod@gmail.com) are disconnected", self._texts()[-1])
        self.assertEqual(self._connected(), [])
        self.assertEqual(self.revoke.call_count, 2, "each Google grant is revoked, as the portal button does")
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))
        self.assertEqual(len(self.prompts), 1, "a plain yes never needs the model")

    def test_a_no_keeps_everything(self) -> None:
        self._post("Just disconnect me from google", message_id="wamid.n1")
        result = self._post("no", message_id="wamid.n2")
        self.assertEqual(result["results"][0]["outcome"], "disconnect_declined")
        self.assertIn("nothing changed", self._texts()[-1].lower())
        self.assertEqual(self._connected(), ["calendar", "email"])
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"])))

    def test_a_question_before_the_yes_is_answered_and_the_yes_can_come_in_words(self) -> None:
        self._post("Just disconnect me from google", message_id="wamid.q1")
        asked = self._post("wait, what will stop working?", message_id="wamid.q2")
        self.assertEqual(asked["results"][0]["outcome"], "message")
        self.assertIn("until you connect again", self._texts()[-1])
        self.assertIn('"pendingChoice":{"kind":"confirmation","question":"Disconnect Google Calendar and Gmail (nimrod@gmail.com) from Assistyca?","about":"disconnect"}', self.prompts[-1])
        self.assertIn("- confirm:", self.prompts[-1])
        self.assertEqual(self._connected(), ["calendar", "email"], "a question is not a yes")
        self.assertEqual(self.database.get_whatsapp_agent_pending(user_id=int(self.user["id"]))["kind"], "disconnect")

        done = self._post("alright then, go on", message_id="wamid.q3")
        self.assertEqual(done["results"][0]["outcome"], "disconnected")
        self.assertEqual(self._connected(), [])

    def test_nothing_connected_by_that_name_says_so(self) -> None:
        self.model.side_effect = lambda **kwargs: SimpleNamespace(output_text=json.dumps({
            "outcome": "disconnect_command", "proposalType": "", "changes": {},
            "reply": "Disconnecting Outlook.", "disconnectTargets": ["outlook"]}))
        result = self._post("disconnect outlook", message_id="wamid.x1")
        self.assertEqual(result["results"][0]["outcome"], "disconnect_nothing")
        self.assertIn("nothing to disconnect", self._texts()[-1])
        self.assertEqual(self._connected(), ["calendar", "email"])


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
