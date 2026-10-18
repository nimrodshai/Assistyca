"""One more word five minutes before: the offer under the ride word, the
button on both send paths, and the tap that queues the second word."""

from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.request as urllib_request
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from unittest import mock

from packages.infrastructure.family_week_nudges import FamilyWeekNudgeConfig
from packages.infrastructure.family_week_nudges import FamilyWeekNudger
from packages.infrastructure.family_week_nudges import leave_words
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.remind_again import REMIND_AGAIN_BUTTON_LABEL
from packages.infrastructure.remind_again import REMIND_AGAIN_QUESTION
from packages.infrastructure.remind_again import parse_remind_again_id
from packages.infrastructure.remind_again import remind_again_button
from packages.infrastructure.remind_again import schedule_second_word
from packages.infrastructure.scheduled_actions import ScheduledActionConfig
from packages.infrastructure.scheduled_actions import ScheduledActionScheduler
from packages.infrastructure.whatsapp_agent_chat import WhatsAppAgentChat

UTC = timezone.utc
# 2026-09-20 is a Sunday.
SUNDAY = datetime(2026, 9, 20, tzinfo=UTC)
PHONE = "972500000001"
PARTNER_PHONE = "972500000002"


def at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute)


class RideWordOfferTests(unittest.TestCase):
    """The word before a drive of their own ends with the offer; a word that
    asks who does a drive does not."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        partner = self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(partner["id"]), code="SHR111", expires_at=datetime.now(UTC) + timedelta(days=14),
        )
        self.assertTrue(self.database.claim_household_invite(code="SHR111", wa_id=PARTNER_PHONE)["ok"])
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child")
        self.database.save_household_member(user_id=self.user_id, name="Noa", role="child")
        self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun"],
            start_time="08:00", end_time="16:00", drop_off_by="me", pick_up_by="Shirly", place="Gan Rimon",
        )
        self.database.save_household_activity(
            user_id=self.user_id, title="Ballet", who=["Noa"], days=["sun"],
            start_time="17:00", end_time="18:00", drop_off_by="Shirly", pick_up_by="",
        )
        self.nudger = FamilyWeekNudger(
            self.database, config=FamilyWeekNudgeConfig(morning_hour=6, evening_hour=20, ride_lead_minutes=30),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def queued(self) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("source") == "family_week"
        ]

    def test_the_owners_own_drive_ends_with_the_offer(self) -> None:
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 7, 32))["rides"], 1)
        [word] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        offer = word["payload"]["remindAgain"]
        self.assertEqual(offer["dueAt"], "2026-09-20T08:00:00+00:00")
        self.assertEqual(offer["minutesBefore"], 5)
        self.assertEqual(offer["facts"], ["take Tom - Kindergarten at 08:00, Gan Rimon"])
        self.assertNotIn("reader", offer)
        self.assertEqual(word["payload"]["templateKind"], "reminder_again")
        self.assertIn("do not ask or offer that yourself", word["payload"]["instruction"])
        # A drop-off rides its own template: the kid, where to and when.
        self.assertEqual(
            word["payload"]["rideSlots"],
            {"kids": ["Tom"], "from": ["Kindergarten"], "at": "08:00", "leg": "drop_off"},
        )

    def test_a_partner_on_their_own_phone_gets_the_offer_too(self) -> None:
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 15, 35))["rides"], 1)
        [word] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertEqual(word["payload"]["recipientWaId"], PARTNER_PHONE)
        offer = word["payload"]["remindAgain"]
        self.assertEqual(offer["dueAt"], "2026-09-20T16:00:00+00:00")
        self.assertEqual(offer["reader"], "Shirly")
        self.assertEqual(offer["facts"], ["collect Tom - Kindergarten at 16:00, Gan Rimon"])
        # A pickup keeps the kid, where from and when for the pickup template.
        self.assertEqual(word["payload"]["rideSlots"], {"kids": ["Tom"], "from": ["Kindergarten"], "at": "16:00"})

    def test_a_word_that_asks_who_does_a_drive_carries_no_offer(self) -> None:
        # Nobody collects Noa from ballet: the owner is asked who does it.
        self.assertGreaterEqual(self.nudger.run_pending(now=at(SUNDAY, 17, 35))["rides"], 1)
        asks = [a for a in self.queued() if a["payload"]["title"] == "Still needs someone"]
        self.assertTrue(asks)
        for ask in asks:
            self.assertNotIn("remindAgain", ask["payload"])
            self.assertEqual(ask["payload"]["templateKind"], "reminder")

    def test_the_words_say_the_offer_is_under_them_only_when_it_is(self) -> None:
        plain = leave_words(["take Tom - Kindergarten at 08:00"], 0)
        with_offer = leave_words(["take Tom - Kindergarten at 08:00"], 0, again_offered=True)
        self.assertNotIn("five minutes before", plain["instruction"])
        self.assertIn("five minutes before", with_offer["instruction"])
        self.assertEqual(plain["fallback"], with_offer["fallback"])


class ButtonOnTheSendTests(unittest.TestCase):
    """Inside the window the question and the button go under the text;
    outside it the template made for them carries both."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user = self.database.get_user("owner@example.com") or {}
        self.user_id = int(self.user["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=PHONE)
        self.env = mock.patch.dict("os.environ", {
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "platform-1", "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def _ride_word(self, **extra) -> dict:
        return self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(UTC) - timedelta(seconds=1), timezone_name="Asia/Jerusalem",
            payload={
                "title": "Time to leave soon", "instruction": "x", "fallbackText": "Soon: take Tom - Kindergarten at 08:00.",
                "oneOff": True, "source": "family_week", "templateKind": "reminder_again",
                "remindAgain": {"dueAt": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(), "minutesBefore": 5,
                                "facts": ["take Tom - Kindergarten at 08:00"]},
                **extra,
            },
        )

    def _scheduler(self) -> ScheduledActionScheduler:
        return ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: "Soon: take Tom to kindergarten at 08:00.",
        )

    def _run(self):
        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", return_value="wamid.1") as send:
            self._scheduler().run_pending(now=datetime.now(UTC))
        return send

    def test_inside_the_window_the_question_and_the_button_go_under_the_text(self) -> None:
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="hi")
        action = self._ride_word()
        send = self._run()
        self.assertEqual(send.call_count, 1)
        interactive = send.call_args.kwargs["interactive"]
        self.assertEqual(interactive["type"], "button")
        self.assertTrue(interactive["body"]["text"].endswith("\n\n" + REMIND_AGAIN_QUESTION["en"]))
        [button] = interactive["action"]["buttons"]
        self.assertEqual(button["reply"], {"id": f"remindagain:{action['id']}", "title": REMIND_AGAIN_BUTTON_LABEL["en"]})
        self.assertIsNone(send.call_args.kwargs["message_text"])
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["payload"]["whatsappSendMode"], "buttons")

    def test_outside_the_window_the_template_with_the_button_carries_it(self) -> None:
        action = self._ride_word()
        send = self._run()
        template = send.call_args.kwargs["template"]
        self.assertEqual(template["name"], "assistyca_reminder_set_again")
        self.assertEqual(template["language"], {"code": "en"})
        body, button = template["components"]
        self.assertEqual(body["type"], "body")
        self.assertEqual(button, {
            "type": "button", "sub_type": "quick_reply", "index": "0",
            "parameters": [{"type": "payload", "payload": f"remindagain:{action['id']}"}],
        })
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["payload"]["whatsappTemplate"], "assistyca_reminder_set_again:en")

    def test_a_hebrew_writer_gets_the_hebrew_question_and_button(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, language="he")
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="היי")
        self._ride_word()
        send = self._run()
        interactive = send.call_args.kwargs["interactive"]
        self.assertTrue(interactive["body"]["text"].endswith(REMIND_AGAIN_QUESTION["he"]))
        self.assertEqual(interactive["action"]["buttons"][0]["reply"]["title"], REMIND_AGAIN_BUTTON_LABEL["he"])

    def test_until_meta_approves_it_the_plain_reminder_carries_the_word_without_the_button(self) -> None:
        action = self._ride_word()

        def refuse_the_new_one(**kwargs):
            if (kwargs.get("template") or {}).get("name") in ("assistyca_reminder_set_again", "assistyca_reminder_set"):
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            if (kwargs.get("template") or {}).get("name") == "assistyca_reminder_again":
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            return "wamid.2"

        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", side_effect=refuse_the_new_one) as send:
            self._scheduler().run_pending(now=datetime.now(UTC))
        self.assertEqual(send.call_count, 4)
        template = send.call_args.kwargs["template"]
        self.assertEqual(template["name"], "assistyca_reminder")
        self.assertEqual([c["type"] for c in template["components"]], ["body"])
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["payload"]["whatsappTemplate"], "assistyca_reminder:en")

    def _pickup_word(self) -> dict:
        return self._ride_word(pickupSlots={"kids": ["Noa", "Tom"], "from": ["Ballet", "Judo"], "at": "17:30"})

    def test_outside_the_window_a_pickup_rides_its_own_template_with_the_button(self) -> None:
        action = self._pickup_word()
        send = self._run()
        self.assertEqual(send.call_count, 1)
        template = send.call_args.kwargs["template"]
        self.assertEqual((template["name"], template["language"]), ("assistyca_pickup_reminder", {"code": "en"}))
        body, button = template["components"]
        self.assertEqual([parameter["text"] for parameter in body["parameters"]], ["Noa and Tom", "Ballet and Judo", "17:30"])
        self.assertEqual(button["parameters"], [{"type": "payload", "payload": f"remindagain:{action['id']}"}])
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["payload"]["whatsappTemplate"], "assistyca_pickup_reminder:en")

    def test_outside_the_window_a_drop_off_rides_its_own_template_with_the_button(self) -> None:
        action = self._ride_word(rideSlots={"kids": ["Noa"], "from": ["Ballet"], "at": "16:00", "leg": "drop_off"})
        send = self._run()
        self.assertEqual(send.call_count, 1)
        template = send.call_args.kwargs["template"]
        self.assertEqual((template["name"], template["language"]), ("assistyca_drop_off_reminder", {"code": "en"}))
        body, button = template["components"]
        self.assertEqual([parameter["text"] for parameter in body["parameters"]], ["Noa", "Ballet", "16:00"])
        self.assertEqual(button["parameters"], [{"type": "payload", "payload": f"remindagain:{action['id']}"}])

    def test_a_hebrew_pickup_joins_the_names_the_hebrew_way(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, language="he")
        self._pickup_word()
        send = self._run()
        template = send.call_args.kwargs["template"]
        self.assertEqual(template["language"], {"code": "he"})
        self.assertEqual(template["components"][0]["parameters"][0]["text"], "Noa וTom")

    def test_until_meta_approves_the_pickup_template_the_word_rides_the_one_with_the_button(self) -> None:
        action = self._pickup_word()

        def refuse_the_pickup_one(**kwargs):
            if (kwargs.get("template") or {}).get("name") == "assistyca_pickup_reminder":
                raise RuntimeError("(#132001) Template name does not exist in the translation")
            return "wamid.2"

        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", side_effect=refuse_the_pickup_one) as send:
            self._scheduler().run_pending(now=datetime.now(UTC))
        self.assertEqual(send.call_count, 2)
        template = send.call_args.kwargs["template"]
        self.assertEqual(template["name"], "assistyca_reminder_set_again")
        self.assertEqual(len(template["components"][0]["parameters"]), 1)
        saved = self.database.get_scheduled_action(int(action["id"])) or {}
        self.assertEqual(saved["payload"]["whatsappTemplate"], "assistyca_reminder_set_again:en")

    def test_inside_the_window_a_pickup_is_still_the_assistants_own_words(self) -> None:
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="hi")
        self._pickup_word()
        send = self._run()
        self.assertIsNone(send.call_args.kwargs["template"])
        self.assertEqual(send.call_args.kwargs["interactive"]["type"], "button")

    def test_a_word_without_the_offer_has_no_button(self) -> None:
        self.database.save_whatsapp_agent_message(user_id=self.user_id, role="user", text="hi")
        self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(UTC) - timedelta(seconds=1), timezone_name="Asia/Jerusalem",
            payload={"title": "Still needs someone", "instruction": "x", "fallbackText": "Soon: nobody. Who?",
                     "oneOff": True, "source": "family_week"},
        )
        send = self._run()
        self.assertIsNone(send.call_args.kwargs["interactive"])
        self.assertEqual(send.call_args.kwargs["message_text"], "Soon: take Tom to kindergarten at 08:00.")


class TheTapTests(unittest.TestCase):
    """The tap queues the word five minutes before the drive, once."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.now = datetime(2026, 9, 20, 4, 30, tzinfo=UTC)  # 07:30 in Jerusalem

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _ride_word(self, *, due: datetime, recipient: str = "", reader: str = "") -> dict:
        offer = {"dueAt": due.isoformat(), "minutesBefore": 5, "facts": ["take Tom - Kindergarten at 08:00, Gan Rimon"]}
        if reader:
            offer["reader"] = reader
        payload = {"title": "Time to leave soon", "instruction": "x", "fallbackText": "Soon.", "oneOff": True,
                   "source": "family_week", "templateKind": "reminder_again", "remindAgain": offer}
        if recipient:
            payload["recipientWaId"] = recipient
        return self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref=recipient or "owner",
            run_at=self.now, timezone_name="Asia/Jerusalem", payload=payload,
        )

    def _second_words(self) -> list[dict]:
        return [a for a in self.database.list_scheduled_actions_for_user(self.user_id) if a["payload"].get("remindAgainOf")]

    def test_the_button_names_the_reminder_that_sent_it(self) -> None:
        self.assertEqual(parse_remind_again_id("remindagain:42"), 42)
        self.assertEqual(parse_remind_again_id("calpick:2"), 0)
        self.assertEqual(parse_remind_again_id("remindagain:x"), 0)
        self.assertEqual(remind_again_button({"id": 7, "payload": {"remindAgain": {"dueAt": "2026-09-20T08:00:00+00:00"}}}, "he"),
                         {"id": "remindagain:7", "label": REMIND_AGAIN_BUTTON_LABEL["he"], "question": REMIND_AGAIN_QUESTION["he"]})
        self.assertEqual(remind_again_button({"id": 7, "payload": {"title": "A birthday is coming"}}, "en"), {})

    def test_the_tap_queues_the_word_five_minutes_before_once(self) -> None:
        due = self.now + timedelta(minutes=30)
        word = self._ride_word(due=due)
        first = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{word['id']}", now=self.now)
        self.assertEqual(first["outcome"], "scheduled")
        self.assertEqual(first["runAt"].strftime("%H:%M"), "07:55")
        [second] = self._second_words()
        self.assertEqual(second["runAt"], (due - timedelta(minutes=5)).isoformat())
        self.assertEqual(second["status"], "pending")
        self.assertEqual(second["channel"], "whatsapp")
        self.assertEqual(second["recipientRef"], "owner")
        self.assertEqual(second["timezone"], "Asia/Jerusalem")
        payload = second["payload"]
        self.assertEqual(payload["title"], "Time to leave")
        self.assertEqual(payload["templateKind"], "reminder")
        self.assertEqual(payload["source"], "family_week")
        self.assertTrue(payload["oneOff"])
        self.assertNotIn("remindAgain", payload, "the second word offers no third")
        self.assertIn("DRIVE: take Tom - Kindergarten at 08:00, Gan Rimon", payload["instruction"])
        self.assertIn("asked for one more word five minutes before", payload["instruction"])
        self.assertEqual(payload["fallbackText"], "Time to leave: take Tom - Kindergarten at 08:00, Gan Rimon.")
        # A second tap on the same button changes nothing.
        again = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{word['id']}", now=self.now)
        self.assertEqual(again["outcome"], "already")
        self.assertEqual(len(self._second_words()), 1)

    def test_a_partners_tap_sends_the_word_to_their_phone(self) -> None:
        word = self._ride_word(due=self.now + timedelta(minutes=30), recipient=PARTNER_PHONE, reader="Shirly")
        schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{word['id']}", now=self.now)
        [second] = self._second_words()
        self.assertEqual(second["recipientRef"], PARTNER_PHONE)
        self.assertEqual(second["payload"]["recipientWaId"], PARTNER_PHONE)
        self.assertIn("This message is for Shirly", second["payload"]["instruction"])

    def test_a_late_tap_goes_now_and_a_tap_after_the_drive_is_told_so(self) -> None:
        late = self._ride_word(due=self.now + timedelta(minutes=3))
        result = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{late['id']}", now=self.now)
        self.assertEqual(result["outcome"], "scheduled")
        [second] = self._second_words()
        self.assertEqual(second["runAt"], self.now.isoformat())
        gone = self._ride_word(due=self.now - timedelta(minutes=1))
        result = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{gone['id']}", now=self.now)
        self.assertEqual(result["outcome"], "past")
        self.assertEqual(len(self._second_words()), 1)

    def test_a_button_from_somebody_elses_reminder_is_unknown(self) -> None:
        self.database.register_user("other@example.com")
        other = int((self.database.get_user("other@example.com") or {})["id"])
        theirs = self.database.create_scheduled_action(
            user_id=other, action_type="run_task", channel="whatsapp", recipient_ref="owner", run_at=self.now,
            payload={"remindAgain": {"dueAt": (self.now + timedelta(minutes=30)).isoformat()}},
        )
        result = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{theirs['id']}", now=self.now)
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(schedule_second_word(self.database, user_id=self.user_id, interactive_id="remindagain:999")["outcome"], "unknown")
        self.assertEqual(self._second_words(), [])

    def test_the_chat_answers_the_tap_with_the_time(self) -> None:
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=PHONE)
        word = self._ride_word(due=datetime.now(UTC) + timedelta(minutes=30))
        chat = WhatsAppAgentChat(
            database=self.database,
            connection={"userId": self.user_id, "email": "owner@example.com", "ownerWaId": PHONE},
            base_url="http://127.0.0.1:1", session_token_factory=lambda _email: "token",
        )
        with mock.patch.dict("os.environ", {"WHATSAPP_ALLOW_MOCK_SEND": "1"}, clear=False), \
             mock.patch("packages.infrastructure.whatsapp_agent_chat.send_assistyca_text", return_value="wamid.r") as send:
            result = chat.handle_message("Yes, 5 min before", message_type="button", interactive_id=f"remindagain:{word['id']}")
        self.assertEqual(result["outcome"], "remind_again_scheduled")
        [second] = self._second_words()
        expected = datetime.fromisoformat(second["runAt"]).astimezone(chat_zone()).strftime("%H:%M")
        self.assertEqual(send.call_args.kwargs["text"], f"Got it - I'll say so again at {expected}.")
        # The second tap is told it is already set, and the model is never asked.
        with mock.patch.dict("os.environ", {"WHATSAPP_ALLOW_MOCK_SEND": "1"}, clear=False), \
             mock.patch("packages.infrastructure.whatsapp_agent_chat.send_assistyca_text", return_value="wamid.r") as send:
            result = chat.handle_message("Yes, 5 min before", message_type="button", interactive_id=f"remindagain:{word['id']}")
        self.assertEqual(result["outcome"], "remind_again_already")
        self.assertTrue(send.call_args.kwargs["text"].startswith("Already set"))


def chat_zone():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Asia/Jerusalem")


class TheTapOverTheWebhookTests(unittest.TestCase):
    """A quick reply on the template arrives as a button payload; the server
    hands it to the agent, not to the old approval flow."""

    PLATFORM = "platform-phone-1"
    APP_SECRET = "remind-test-secret"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server("127.0.0.1", 0, Path(__file__).resolve().parents[1], PortalConfig(
            db_path=Path(self.temp_dir.name) / "portal.db", session_secret="remind-session-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=PHONE)
        self.env = mock.patch.dict("os.environ", {
            "PORTAL_WHATSAPP_STORE_ROOT": str(Path(self.temp_dir.name) / "portal-whatsapp"),
            "WHATSAPP_APP_SECRET": self.APP_SECRET, "WHATSAPP_ALLOW_MOCK_SEND": "1",
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": self.PLATFORM, "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
            "WHATSAPP_AGENT_LOOP_ENABLED": "1",
        }, clear=False)
        self.env.start()
        self.send_patch = mock.patch("packages.infrastructure.whatsapp_agent_chat.send_whatsapp_message", return_value="wamid.reply")
        self.sent = self.send_patch.start()
        self.model_patch = mock.patch("packages.infrastructure.portal_auth.server.call_openai_response",
                                      side_effect=AssertionError("a tap is settled by code, never by the model"))
        self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop(); self.send_patch.stop(); self.env.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5); self.temp_dir.cleanup()

    def _tap(self, payload: str, *, message_id: str) -> dict:
        message = {"from": PHONE, "id": message_id, "timestamp": "1756700000", "type": "button",
                   "button": {"payload": payload, "text": "Yes, 5 min before"}}
        body = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"display_phone_number": "1555", "phone_number_id": self.PLATFORM},
            "contacts": [{"profile": {"name": "Dana"}, "wa_id": PHONE}], "messages": [message]}}]}]}).encode("utf-8")
        sig = hmac.new(self.APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        request = urllib_request.Request(f"{self.base_url}/webhooks/whatsapp", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={sig}"})
        with urllib_request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_the_template_button_reaches_the_agent_and_queues_the_word(self) -> None:
        word = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(UTC), timezone_name="Asia/Jerusalem",
            payload={"title": "Time to leave soon", "instruction": "x", "fallbackText": "Soon.", "oneOff": True,
                     "source": "family_week", "templateKind": "reminder_again",
                     "remindAgain": {"dueAt": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(), "minutesBefore": 5,
                                     "facts": ["take Tom - Kindergarten at 08:00"]}},
        )
        result = self._tap(f"remindagain:{word['id']}", message_id="wamid.tap-1")
        self.assertEqual(result["results"][0]["action"], "agent_chat_reply")
        self.assertEqual(result["results"][0]["outcome"], "remind_again_scheduled")
        seconds = [a for a in self.database.list_scheduled_actions_for_user(self.user_id) if a["payload"].get("remindAgainOf") == word["id"]]
        self.assertEqual(len(seconds), 1)
        self.assertEqual(seconds[0]["payload"]["title"], "Time to leave")
        self.assertTrue(self.sent.call_args.kwargs["message_text"].startswith("Got it - I'll say so again at "))


if __name__ == "__main__":
    unittest.main()


class SecondWordStillTheirsTests(unittest.TestCase):
    """Oren's question, 2026-10-18: Shirly taps "remind me again" for her
    16:00 pickup, and then the drive stops being hers - she is put on hold,
    or the account holder says they will collect today. The word five
    minutes before is not sent to someone who no longer drives."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=PHONE)
        partner = self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(partner["id"]), code="SHR222", expires_at=datetime.now(UTC) + timedelta(days=14),
        )
        self.assertTrue(self.database.claim_household_invite(code="SHR222", wa_id=PARTNER_PHONE)["ok"])
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child")
        self.gan = self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun"],
            start_time="08:00", end_time="16:00", drop_off_by="me", pick_up_by="Shirly", place="Gan Rimon",
        )
        # The family's clock is Israel's, read off the phone: 15:35 there is 12:35 UTC.
        nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(morning_hour=6, evening_hour=20, ride_lead_minutes=30))
        self.assertEqual(nudger.run_pending(now=at(SUNDAY, 12, 35))["rides"], 1)
        [word] = [a for a in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
                  if a["recipientRef"] == PARTNER_PHONE and a["payload"].get("remindAgain")]
        tapped = schedule_second_word(self.database, user_id=self.user_id, interactive_id=f"remindagain:{word['id']}", now=at(SUNDAY, 12, 37))
        self.assertEqual(tapped["outcome"], "scheduled")
        self.env = mock.patch.dict("os.environ", {
            "ASSISTYCA_WHATSAPP_PHONE_NUMBER_ID": "platform-1", "ASSISTYCA_WHATSAPP_ACCESS_TOKEN": "platform-token",
        }, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def second_word_after_its_time(self) -> dict:
        scheduler = ScheduledActionScheduler(
            self.database, config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: "Time to leave for Tom.",
        )
        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", return_value="wamid.1"):
            scheduler.run_pending(now=at(SUNDAY, 12, 56))
        [second] = [a for a in self.database.list_scheduled_actions_for_user(self.user_id, limit=50) if a["payload"].get("remindAgainOf")]
        return second

    def test_it_goes_when_the_drive_is_still_hers(self) -> None:
        self.assertEqual(self.second_word_after_its_time()["status"], "sent")

    def test_not_after_she_is_put_on_hold(self) -> None:
        self.database.save_schedule_exception(
            user_id=self.user_id, starts_on="2026-09-20", ends_on="2026-09-20", targets=[{"kind": "person", "ref": "Shirly"}],
        )
        self.assertEqual(self.second_word_after_its_time()["status"], "cancelled")

    def test_not_after_somebody_else_says_they_collect_today(self) -> None:
        self.database.save_household_day_drive(
            user_id=self.user_id, activity_id=int(self.gan["id"]), day="2026-09-20", leg="pick_up", who="me",
        )
        self.assertEqual(self.second_word_after_its_time()["status"], "cancelled")

    def test_not_after_the_activity_is_off_today(self) -> None:
        self.database.save_schedule_exception(
            user_id=self.user_id, starts_on="2026-09-20", ends_on="2026-09-20", targets=[{"kind": "person", "ref": "Tom"}],
        )
        self.assertEqual(self.second_word_after_its_time()["status"], "cancelled")

    def test_the_account_holders_own_drive_is_checked_the_same_way(self) -> None:
        from packages.infrastructure.remind_again import second_word_still_theirs

        def word(names: list[str]) -> dict:
            return {"userId": self.user_id, "payload": {"stillTheirs": {
                "day": "2026-09-20", "owner": True, "names": names,
                "drives": [{"activityId": int(self.gan["id"]), "leg": "drop_off"}],
            }}}

        self.assertTrue(second_word_still_theirs(self.database, word(["Dana"])))
        self.database.save_schedule_exception(
            user_id=self.user_id, starts_on="2026-09-20", ends_on="2026-09-20", targets=[{"kind": "person", "ref": "Dana"}],
        )
        self.assertFalse(second_word_still_theirs(self.database, word(["Dana"])))
        self.assertTrue(second_word_still_theirs(self.database, {"userId": self.user_id, "payload": {}}), "an older word goes as it is")
