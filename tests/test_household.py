"""The family an account keeps, and the week it runs."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error as urllib_error
import urllib.request as urllib_request
from datetime import date
from pathlib import Path

from packages.infrastructure import household
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.portal_db import ACCOUNT_FACT_LIMIT
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
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

    def test_a_birthday_is_kept_with_or_without_its_year(self) -> None:
        self.assertEqual(household.normalize_birthday("2021-10-12"), "2021-10-12")
        self.assertEqual(household.normalize_birthday("10-12"), "--10-12")
        self.assertEqual(household.normalize_birthday("--2-29"), "--02-29")
        self.assertEqual(household.normalize_birthday("2021-02-30"), "")
        self.assertEqual(household.normalize_birthday("next Tuesday"), "")
        today = date(2026, 9, 17)
        self.assertEqual(household.next_birthday("2021-10-12", today), date(2026, 10, 12))
        self.assertEqual(household.next_birthday("2021-09-17", today), today)
        self.assertEqual(household.next_birthday("2021-03-01", today), date(2027, 3, 1))
        self.assertEqual(household.next_birthday("--02-29", date(2026, 3, 1)), date(2027, 2, 28))
        self.assertEqual(household.age_from_birthday("2021-10-12", today), 4)
        self.assertIsNone(household.age_from_birthday("--10-12", today))
        self.assertEqual(household.current_age(9, "2026-01-01", today, "2021-10-12"), 4, "the birthday wins")

    def test_the_ready_made_list_counts_back_from_the_birthday(self) -> None:
        items = household.birthday_list_items("child", date(2026, 10, 12), date(2026, 9, 17))
        self.assertEqual(items[0], {"step": 1, "text": "Decide what kind of party, where, and roughly how many children", "dueOn": "2026-09-17"})
        self.assertEqual([i["dueOn"] for i in items if i["text"] == "Send the invitations"], ["2026-09-21"])
        self.assertEqual(items[-1]["dueOn"], "2026-10-11")
        partner = household.birthday_list_items("partner", date(2026, 10, 12), date(2026, 9, 1))
        self.assertIn("Write the card", [i["text"] for i in partner])

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

    def test_an_older_database_pins_what_registration_said(self) -> None:
        self.database.save_account_fact(user_id=self.user_id, key="their family", fact="Two kids")
        self.database.save_account_fact(user_id=self.user_id, key="vendor", fact="Bills in dollars")
        with sqlite3.connect(self.path) as conn:
            conn.execute("ALTER TABLE account_facts DROP COLUMN pinned")
            conn.execute("ALTER TABLE household_members DROP COLUMN birthday")
        reopened = PortalDatabase(self.path)
        pinned = {fact["key"]: fact["pinned"] for fact in reopened.list_account_facts(user_id=self.user_id)}
        self.assertEqual(pinned, {"their family": True, "vendor": False})
        self.assertEqual(reopened.save_household_member(user_id=self.user_id, name="Tom", birthday="10-12")["birthday"], "--10-12")

    def test_the_kind_of_account_is_the_one_signup_and_the_admin_set(self) -> None:
        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual((profile["accountKind"], profile["gettingToKnow"]), ("business", "not_started"))
        self.database.update_user_account_type("parent@example.com", account_type="family")
        self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {})["accountKind"], "family")

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

    def test_a_birthday_is_saved_checked_and_cleared(self) -> None:
        member = self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", birthday="2021-10-12")
        self.assertEqual(member["birthday"], "2021-10-12")
        with self.assertRaises(ValueError):
            self.database.save_household_member(user_id=self.user_id, name="Tom", birthday="soon")
        self.assertEqual(self.database.save_household_member(user_id=self.user_id, name="Tom", notes="x")["birthday"], "2021-10-12")
        self.assertEqual(self.database.save_household_member(user_id=self.user_id, name="Tom", birthday="")["birthday"], "")

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
        self.database.save_household_profile(user_id=self.user_id, getting_to_know="in_progress")
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
        self.assertIn("never use remember_fact for family", AGENT_LOOP_INSTRUCTIONS)
        # How to ask travels with the opening this account is on, not with
        # every account's instructions: see tests/test_chat_flow.py.
        self.assertNotIn("one question in a message", AGENT_LOOP_INSTRUCTIONS)

    def _birthday_member(self, **extra) -> None:
        self.run_tool(
            "save_family_member", name="Tom", previous_name=None, role="child", age=None, birthday="2021-10-12",
            school=None, email=None, phone=None, notes=None, **extra,
        )

    def test_the_birthday_list_is_worded_by_the_model_and_dated_by_code(self) -> None:
        self._birthday_member()
        from unittest import mock
        with mock.patch("packages.infrastructure.agent_loop._household_today", return_value=date(2026, 9, 12)):
            made = self.run_tool(
                "start_birthday_list", name="tom", list_name="יום הולדת לתום",
                items=[
                    {"step": 1, "text": "להחליט איזו מסיבה ואיפה"},
                    {"step": 4, "text": "לשלוח הזמנות"},
                    {"step": None, "text": "להזמין את סבתא"},
                ],
            )
        self.assertTrue(made["ok"], made)
        self.assertEqual(made["list"]["name"], "יום הולדת לתום")
        self.assertEqual(made["birthday"], {"name": "Tom", "on": "2026-10-12", "turning": 5})
        due = {item["text"]: item["dueOn"] for item in made["list"]["items"]}
        self.assertEqual(due, {"להחליט איזו מסיבה ואיפה": "2026-09-14", "לשלוח הזמנות": "2026-09-21", "להזמין את סבתא": "2026-10-12"})
        again = self.run_tool("start_birthday_list", name="Tom", list_name="יום הולדת לתום", items=[])
        self.assertEqual(again["error"]["code"], "already_exists")

    def test_the_ready_made_steps_are_used_when_none_are_worded(self) -> None:
        self._birthday_member()
        made = self.run_tool("start_birthday_list", name="Tom", list_name=None, items=[])
        self.assertEqual(made["list"]["name"], "Tom's birthday")
        self.assertEqual(made["list"]["itemCount"], len(household.BIRTHDAY_LIST_TEMPLATES["child"]))

    def test_no_list_without_a_birthday(self) -> None:
        self.run_tool("save_family_member", name="Noa", previous_name=None, role="child", age=8, birthday=None, school=None, email=None, phone=None, notes=None)
        refused = self.run_tool("start_birthday_list", name="Noa", list_name=None, items=[])
        self.assertEqual(refused["error"]["code"], "choice_required")

    def test_showing_the_week_hands_over_the_page_link(self) -> None:
        self.context.week_link = lambda: "https://assistyca.com/week/open/abc"
        week = self.run_tool("show_family_week")
        self.assertEqual(week["weekPage"], "https://assistyca.com/week/open/abc")
        self.assertIn("https://assistyca.com/week/open/abc", self.context.links_offered)
        done = self.run_tool("set_getting_to_know", status="done", ask_again_in_days=None)
        self.assertEqual(done["weekPage"], "https://assistyca.com/week/open/abc")


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


class WeekPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(__file__).resolve().parents[1]
        self.server = create_server(
            "127.0.0.1", 0, self.root,
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="week-page-test-secret-0123456789abcdef"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("parent@example.com", display_name="Dana Levi")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        code, _ = self.server.store.issue_challenge("parent@example.com")
        ok, error, result = self.server.store.verify_code("parent@example.com", code)
        self.assertTrue(ok, error)
        self.token = str((result or {}).get("token") or "")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, *, signed_in: bool = True) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "Origin": self.base_url}
        if signed_in:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers,
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                return int(response.status), json.loads(response.read().decode() or "{}")
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode() or "{}"
            try:
                return int(exc.code), json.loads(raw)
            except ValueError:
                return int(exc.code), {}

    def test_the_week_is_read_changed_and_emptied_from_the_page(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", age=4, email=None)
        status, created = self.request("POST", "/api/household/activities", {
            "title": "Football", "who": ["Tom"], "days": ["tue"], "startTime": "17:00", "endTime": "18:00",
            "place": "Park", "dropOffBy": "me", "pickUpBy": "",
        })
        self.assertEqual(status, 200, created)
        self.assertEqual(created["ownerName"], "Dana Levi")
        self.assertEqual([m["name"] for m in created["members"]], ["Tom"])
        activity = created["activities"][0]
        self.assertNotIn("userId", activity)

        status, changed = self.request("POST", f"/api/household/activities/{activity['id']}", {"pickUpBy": "Shirly"})
        self.assertEqual(status, 200, changed)
        self.assertEqual(changed["activities"][0]["pickUpBy"], "Shirly")
        self.assertEqual(changed["activities"][0]["title"], "Football")

        status, refused = self.request("POST", "/api/household/activities", {"title": "Ballet", "days": []})
        self.assertEqual((status, refused["error"]), (400, "invalid_activity"))

        status, removed = self.request("DELETE", f"/api/household/activities/{activity['id']}")
        self.assertEqual((status, removed["activities"]), (200, []))
        status, _ = self.request("DELETE", f"/api/household/activities/{activity['id']}")
        self.assertEqual(status, 404)

    def test_the_page_needs_a_sign_in(self) -> None:
        status, _ = self.request("GET", "/api/household", signed_in=False)
        self.assertEqual(status, 401)

    def test_a_shared_link_shows_who_drives_and_nothing_private(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner", email="shirly@example.com", phone="0501234567")
        self.database.save_household_activity(user_id=self.user_id, title="Ballet", who=["Noa"], days=["mon"], drop_off_by="me", notes="bring water")
        status, shared = self.request("POST", "/api/household/share", {"enabled": True})
        self.assertEqual(status, 200)
        url = shared["share"]["url"]
        token = url.rsplit("/w/", 1)[1]

        status, public = self.request("GET", f"/api/public/week/{token}", signed_in=False)
        self.assertEqual(status, 200, public)
        self.assertEqual(public["ownerName"], "Dana")
        self.assertEqual(public["members"], [{"name": "Shirly", "role": "partner"}])
        raw = json.dumps(public)
        for private in ("shirly@example.com", "0501234567", "bring water", "parent@example.com"):
            self.assertNotIn(private, raw)
        with urllib_request.urlopen(f"{self.base_url}/w/{token}", timeout=10) as response:
            self.assertIn("week-share.js", response.read().decode())

        self.request("POST", "/api/household/share", {"enabled": False})
        status, _ = self.request("GET", f"/api/public/week/{token}", signed_in=False)
        self.assertEqual(status, 404)

    def test_a_whatsapp_link_signs_the_phone_in_and_opens_the_week(self) -> None:
        with urllib_request.urlopen(f"{self.base_url}/week", timeout=10) as response:
            self.assertIn("week.js", response.read().decode())
        code = self.database.create_list_open_code(user_id=self.user_id, list_id=0, expires_at=time.time() + 60)
        opener = urllib_request.build_opener(_NoRedirect)
        try:
            opener.open(f"{self.base_url}/week/open/{code}", timeout=10)
            self.fail("expected a redirect")
        except urllib_error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertEqual(exc.headers["Location"], "/week")
            self.assertIn("assistyca_portal_session", exc.headers.get("Set-Cookie", ""))


if __name__ == "__main__":
    unittest.main()
