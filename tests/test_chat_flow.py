"""The opening of the conversation, which is not the same for both kinds of account.

A business is steered towards connecting its mail and its calendar. A family
is asked who is at home and what their week looks like, and only once that is
in is connecting offered. Either way a "not now" is remembered, so nobody is
asked the same thing the next morning.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure import chat_flow
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.portal_db import PortalDatabase

TODAY = "2026-09-17"


class WhichOpeningTests(unittest.TestCase):
    def flow(self, **kwargs) -> dict:
        kwargs.setdefault("profile", None)
        kwargs.setdefault("connected", [])
        kwargs.setdefault("today", TODAY)
        return chat_flow.describe_chat_flow(**kwargs)

    def test_a_business_opens_on_getting_connected(self) -> None:
        flow = self.flow(account_type="business")
        self.assertEqual((flow["goal"], flow["notConnected"]), ("connect", ["mailbox", "calendar"]))
        self.assertTrue(flow["askNow"])

    def test_a_business_is_asked_only_for_what_is_missing_and_then_left_alone(self) -> None:
        self.assertEqual(self.flow(account_type="business", connected=["mailbox"])["notConnected"], ["calendar"])
        done = self.flow(account_type="business", connected=["mailbox", "calendar"])
        self.assertEqual(done, {"accountType": "business", "goal": "done"})

    def test_a_family_is_got_to_know_before_anything_is_offered(self) -> None:
        # Nothing connected, but connecting is not what a family needs first.
        flow = self.flow(account_type="family")
        self.assertEqual((flow["goal"], flow["status"]), ("family", "not_started"))
        self.assertNotIn("notConnected", flow)
        started = self.flow(account_type="family", profile={"gettingToKnow": "in_progress"})
        self.assertEqual(started["goal"], "family")

    def test_a_family_whose_week_is_in_is_then_offered_the_calendar_and_the_mail(self) -> None:
        flow = self.flow(account_type="family", profile={"gettingToKnow": "done"})
        self.assertEqual((flow["accountType"], flow["goal"]), ("family", "connect"))
        self.assertEqual(flow["notConnected"], ["mailbox", "calendar"])

    def test_a_family_the_house_switched_the_week_off_for_opens_on_connecting(self) -> None:
        flow = self.flow(account_type="family", family_flow_allowed=False)
        self.assertEqual(flow["goal"], "connect")

    def test_not_now_is_kept_until_the_day_it_named(self) -> None:
        holding = self.flow(account_type="business", profile={"connectOffer": "postponed", "connectAskAgainOn": "2026-09-20"})
        self.assertEqual((holding["status"], holding["askNow"]), ("postponed", False))
        due = self.flow(account_type="business", profile={"connectOffer": "postponed", "connectAskAgainOn": TODAY})
        self.assertTrue(due["askNow"])
        settled = self.flow(account_type="business", profile={"connectOffer": "done"})
        self.assertEqual(settled["goal"], "done")

    def test_a_family_putting_it_off_is_not_pushed_on_to_connecting(self) -> None:
        # Postponed is not done: the opening is still getting to know them,
        # it is only on hold.
        flow = self.flow(account_type="family", profile={"gettingToKnow": "postponed", "askAgainOn": "2026-09-30"})
        self.assertEqual((flow["goal"], flow["askNow"]), ("family", False))

    def test_an_account_registered_before_the_page_asked_is_a_business(self) -> None:
        self.assertEqual(self.flow(account_type="")["accountType"], "business")


class RulesTests(unittest.TestCase):
    def test_a_family_is_never_spoken_to_as_a_business(self) -> None:
        rules = chat_flow.chat_flow_rules({"accountType": "family", "goal": "done"})
        self.assertIn("registered as a family", rules)
        self.assertEqual(chat_flow.chat_flow_rules({"accountType": "business", "goal": "done"}), "")

    def test_each_opening_carries_its_own_rules(self) -> None:
        business = chat_flow.chat_flow_rules({"accountType": "business", "goal": "connect"})
        self.assertIn("behind their mail and their calendar", business)
        self.assertIn("set_connect_offer", business)
        self.assertNotIn("registered as a family", business)

        getting_to_know = chat_flow.chat_flow_rules({"accountType": "family", "goal": "family"})
        self.assertIn("one question in a message", getting_to_know)
        self.assertIn("set_getting_to_know", getting_to_know)
        self.assertNotIn("set_connect_offer", getting_to_know)

        then_connecting = chat_flow.chat_flow_rules({"accountType": "family", "goal": "connect"})
        self.assertIn("registered as a family", then_connecting)
        self.assertIn("Their family and their week are in", then_connecting)

    def test_nothing_is_said_when_there_is_no_block(self) -> None:
        self.assertEqual(chat_flow.chat_flow_rules(None), "")


class TurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.path)
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])
        self.context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="owner@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_the_opening_travels_in_the_context_with_its_rules(self) -> None:
        flow = chat_flow.describe_chat_flow(account_type="family", profile=None, connected=[], today=TODAY)
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="Asia/Jerusalem", today=TODAY,
            tool_context={}, facts=[], channel="whatsapp", chat_flow=flow,
        )
        context = json.loads(text.split("CONTEXT\n", 1)[1])
        self.assertEqual(context["chatFlow"]["goal"], "family")
        self.assertIn("one question in a message", text)

    def test_an_ended_trial_is_not_asked_to_connect_anything(self) -> None:
        flow = chat_flow.describe_chat_flow(account_type="business", profile=None, connected=[], today=TODAY)
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="Asia/Jerusalem", today=TODAY,
            tool_context={}, facts=[], channel="whatsapp", chat_flow=flow, trial_ended=True,
        )
        self.assertNotIn("set_connect_offer", text)

    def test_a_not_now_about_connecting_is_written_down_and_read_back(self) -> None:
        offered = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "in_progress"})
        self.assertEqual(offered["status"], "in_progress")
        held = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "postponed", "ask_again_in_days": None})
        self.assertRegex(held["askAgainOn"], r"^\d{4}-\d{2}-\d{2}$")

        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        flow = chat_flow.describe_chat_flow(
            account_type="business", profile=profile, connected=[], today=date.today().isoformat(),
        )
        self.assertFalse(flow["askNow"], "a not now said today is not asked again today")

        # Getting to know the family and the offer to connect are two
        # separate answers: one does not overwrite the other.
        TOOLS_BY_NAME["set_getting_to_know"].run(self.context, {"status": "done"})
        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual((profile["gettingToKnow"], profile["connectOffer"]), ("done", "postponed"))

    def test_a_bad_status_is_refused(self) -> None:
        refused = TOOLS_BY_NAME["set_connect_offer"].run(self.context, {"status": "later"})
        self.assertEqual(refused["error"]["code"], "choice_required")

    def test_a_database_from_before_the_offer_existed_reads_as_not_started(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, connect_offer="postponed", connect_ask_again_on="2026-09-30")
        with sqlite3.connect(self.path) as conn:
            conn.execute("ALTER TABLE household_profiles DROP COLUMN connect_offer")
            conn.execute("ALTER TABLE household_profiles DROP COLUMN connect_ask_again_on")
        reopened = PortalDatabase(self.path)
        profile = reopened.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual((profile["connectOffer"], profile["connectAskAgainOn"]), ("not_started", ""))


if __name__ == "__main__":
    unittest.main()
