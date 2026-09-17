"""The family an account keeps, and the week it runs."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from packages.infrastructure import household
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.portal_db import ACCOUNT_FACT_LIMIT
from packages.infrastructure.portal_db import PortalDatabase


class RulesTests(unittest.TestCase):
    def test_times_and_days_are_written_one_way(self) -> None:
        self.assertEqual(household.normalize_time("7:30"), "07:30")
        self.assertEqual(household.normalize_time("17"), "17:00")
        self.assertEqual(household.normalize_time("16.45"), "16:45")
        self.assertEqual(household.normalize_time("25:00"), "")
        self.assertEqual(household.normalize_time("after lunch"), "")
        self.assertEqual(household.normalize_days(["thu", "Sun", "monday", "sun", "xyz"]), ["sun", "mon", "thu"])
        self.assertEqual(household.weekday_code(date(2026, 9, 20)), "sun")

    def test_me_is_the_account_holder_by_word_or_by_name(self) -> None:
        self.assertTrue(household.is_self("me"))
        self.assertTrue(household.is_self("אני"))
        self.assertTrue(household.is_self("Nimrod", owner_names=["Nimrod Shai"]))
        self.assertFalse(household.is_self("Shirly", owner_names=["Nimrod Shai"]))
        self.assertFalse(household.is_self(""))

    def test_an_age_keeps_counting_from_when_it_was_said(self) -> None:
        self.assertEqual(household.current_age(4, "2024-10-01", date(2026, 9, 17)), 5)
        self.assertEqual(household.current_age(4, "2024-09-01", date(2026, 9, 17)), 6)
        self.assertIsNone(household.current_age(None, "", date(2026, 9, 17)))

    def test_a_family_account_is_described_even_before_anyone_is_known(self) -> None:
        self.assertTrue(household.should_describe_household({"accountKind": "family"}, [], []))
        self.assertFalse(household.should_describe_household({"accountKind": "business"}, [], []))
        self.assertFalse(household.should_describe_household(None, [], []))
        self.assertTrue(household.should_describe_household(None, [{"name": "Shirly"}], []))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.path)
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pinned_facts_never_give_way_to_newer_ones(self) -> None:
        self.database.save_account_fact(user_id=self.user_id, key="name", fact="Their name is Dana.", pinned=True)
        for index in range(ACCOUNT_FACT_LIMIT + 10):
            self.database.save_account_fact(user_id=self.user_id, key=f"fact {index}", fact="something")
        facts = self.database.list_account_facts(user_id=self.user_id)
        keys = [fact["key"] for fact in facts]
        self.assertEqual(keys[0], "name")
        self.assertEqual(len(facts), ACCOUNT_FACT_LIMIT + 1)
        self.assertNotIn("fact 0", keys)
        # Saying a pinned fact again without the pin does not unpin it.
        self.database.save_account_fact(user_id=self.user_id, key="name", fact="Their name is Dana Levi.")
        self.assertTrue(self.database.list_account_facts(user_id=self.user_id)[0]["pinned"])

    def test_an_older_database_pins_what_registration_said_and_knows_its_families(self) -> None:
        self.database.save_account_fact(user_id=self.user_id, key="their family", fact="Two kids")
        self.database.save_account_fact(user_id=self.user_id, key="vendor", fact="Bills in dollars")
        with sqlite3.connect(self.path) as conn:
            conn.execute("ALTER TABLE account_facts DROP COLUMN pinned")
            conn.execute("DELETE FROM household_profiles")
        reopened = PortalDatabase(self.path)
        pinned = {fact["key"]: fact["pinned"] for fact in reopened.list_account_facts(user_id=self.user_id)}
        self.assertEqual(pinned, {"their family": True, "vendor": False})
        self.assertEqual((reopened.get_household_profile(user_id=self.user_id) or {})["accountKind"], "family")

    def test_a_member_is_filled_in_over_time_and_keeps_their_spelling(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")
        member = self.database.save_household_member(user_id=self.user_id, name="shirly", email="shirly@example.com")
        self.assertEqual(member["name"], "Shirly")
        self.assertEqual(member["role"], "partner")
        self.assertEqual(member["email"], "shirly@example.com")
        # An empty string clears; None keeps.
        member = self.database.save_household_member(user_id=self.user_id, name="Shirly", email="", notes=None)
        self.assertEqual(member["email"], "")
        with self.assertRaises(ValueError):
            self.database.save_household_member(user_id=self.user_id, name="Shirly", email="not an address")

    def test_a_member_can_be_renamed_and_removed(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", age=4)
        renamed = self.database.save_household_member(user_id=self.user_id, name="Tomer", previous_name="Tom")
        self.assertEqual((renamed["name"], renamed["age"]), ("Tomer", 4))
        with self.assertRaises(ValueError):
            self.database.save_household_member(user_id=self.user_id, name="Noa", previous_name="Nobody")
        self.assertTrue(self.database.remove_household_member(user_id=self.user_id, name="tomer"))
        self.assertEqual(self.database.list_household_members(user_id=self.user_id), [])

    def test_the_partner_comes_before_the_children(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child")
        self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")
        self.assertEqual([m["name"] for m in self.database.list_household_members(user_id=self.user_id)], ["Shirly", "Tom"])

    def test_an_activity_is_added_changed_and_removed(self) -> None:
        activity = self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["thu", "sun"],
            start_time="7:30", end_time="16", drop_off_by="me",
        )
        self.assertEqual(activity["days"], ["sun", "thu"])
        self.assertEqual((activity["startTime"], activity["endTime"]), ("07:30", "16:00"))
        self.assertEqual(household.activity_gaps(activity), ["pick_up"])
        changed = self.database.save_household_activity(user_id=self.user_id, activity_id=activity["id"], pick_up_by="Shirly")
        self.assertEqual((changed["dropOffBy"], changed["pickUpBy"], changed["title"]), ("me", "Shirly", "Kindergarten"))
        with self.assertRaises(ValueError):
            self.database.save_household_activity(user_id=self.user_id, title="Football", days=[])
        with self.assertRaises(ValueError):
            self.database.save_household_activity(user_id=self.user_id, title="Football", days=["tue"], start_time="later")
        with self.assertRaises(LookupError):
            self.database.save_household_activity(user_id=self.user_id, activity_id=999, title="x")
        self.assertTrue(self.database.remove_household_activity(user_id=self.user_id, activity_id=activity["id"]))
        self.assertFalse(self.database.remove_household_activity(user_id=self.user_id, activity_id=activity["id"]))

    def test_another_account_cannot_touch_this_family(self) -> None:
        activity = self.database.save_household_activity(user_id=self.user_id, title="Ballet", days=["mon"])
        self.database.register_user("stranger@example.com")
        stranger = int((self.database.get_user("stranger@example.com") or {})["id"])
        with self.assertRaises(LookupError):
            self.database.save_household_activity(user_id=stranger, activity_id=activity["id"], title="Mine")
        self.assertFalse(self.database.remove_household_activity(user_id=stranger, activity_id=activity["id"]))

    def test_deleting_the_account_takes_the_family_with_it(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, account_kind="family")
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child")
        self.database.save_household_activity(user_id=self.user_id, title="Ballet", days=["mon"])
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM users WHERE id = ?", (self.user_id,))
            counts = [conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("household_profiles", "household_members", "household_activities")]
        self.assertEqual(counts, [0, 0, 0])


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_tool(self, tool: str, **args) -> dict:
        return TOOLS_BY_NAME[tool].run(self.context, args)

    def test_the_family_and_its_week_are_saved_and_shown_by_day(self) -> None:
        saved = self.run_tool("save_family_member", name="Tom", previous_name=None, role="child", age=4, school="Rimon kindergarten", email=None, phone=None, notes=None)
        self.assertTrue(saved["ok"], saved)
        self.run_tool("save_family_member", name="Shirly", previous_name=None, role="partner", age=None, school=None, email="shirly@example.com", phone=None, notes=None)
        added = self.run_tool(
            "save_week_activity", id=None, title="Football", who=["Tom"], days=["tue"], start_time="17:00",
            end_time="18:00", place=None, drop_off_by="me", pick_up_by="", notes=None,
        )
        self.assertTrue(added["ok"], added)
        self.assertEqual(added["saved"]["nobodyDownFor"], ["pick_up"])

        # A change passes null and empty arrays for what stays.
        changed = self.run_tool(
            "save_week_activity", id=added["saved"]["id"], title=None, who=[], days=[], start_time=None,
            end_time=None, place=None, drop_off_by=None, pick_up_by="Shirly", notes=None,
        )
        self.assertEqual((changed["saved"]["days"], changed["saved"]["who"], changed["saved"]["pickUpBy"]), (["tue"], ["Tom"], "Shirly"))

        week = self.run_tool("show_family_week")
        self.assertEqual([m["name"] for m in week["members"]], ["Shirly", "Tom"])
        self.assertEqual(list(week["byDay"]), ["tue"])
        self.assertNotIn("nobodyDownFor", week["byDay"]["tue"][0])

    def test_a_bad_email_or_unknown_activity_is_explained_not_saved(self) -> None:
        refused = self.run_tool("save_family_member", name="Shirly", previous_name=None, role="partner", age=None, school=None, email="shirly at gmail", phone=None, notes=None)
        self.assertEqual(refused["error"]["code"], "choice_required")
        missing = self.run_tool("remove_week_activity", id=42)
        self.assertEqual(missing["error"]["code"], "not_found")
        nobody = self.run_tool("remove_family_member", name="Noa")
        self.assertEqual(nobody["error"]["code"], "not_found")

    def test_not_now_sets_a_day_to_ask_again(self) -> None:
        result = self.run_tool("set_getting_to_know", status="postponed", ask_again_in_days=None)
        self.assertEqual(result["status"], "postponed")
        self.assertRegex(result["askAgainOn"], r"^\d{4}-\d{2}-\d{2}$")
        done = self.run_tool("set_getting_to_know", status="done", ask_again_in_days=None)
        self.assertEqual((done["status"], done["askAgainOn"]), ("done", None))

    def test_the_family_travels_in_the_context_and_the_rules_say_how_to_ask(self) -> None:
        block = household.describe_household(
            profile={"accountKind": "family", "gettingToKnow": "in_progress"},
            members=[{"name": "Tom", "role": "child", "age": 4, "ageNotedOn": "2026-09-17"}],
            activities=[],
            today=date(2026, 9, 17),
        )
        text = build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="Asia/Jerusalem", today="2026-09-17",
            tool_context={}, facts=[], channel="whatsapp", household_block=block,
        )
        context = json.loads(text.split("CONTEXT\n", 1)[1])
        self.assertEqual(context["household"]["members"], [{"name": "Tom", "role": "child", "age": 4}])
        self.assertEqual(context["household"]["gettingToKnow"]["status"], "in_progress")
        from packages.infrastructure.agent_loop import AGENT_LOOP_INSTRUCTIONS
        self.assertIn("one question in a message", AGENT_LOOP_INSTRUCTIONS)
        self.assertIn("never use remember_fact for family", AGENT_LOOP_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
