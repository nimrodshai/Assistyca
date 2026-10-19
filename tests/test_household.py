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
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from packages.infrastructure import household
from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import _household_today
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import build_loop_context_text
from packages.infrastructure.portal_db import ACCOUNT_FACT_LIMIT
from packages.infrastructure.portal_auth.server import PortalAuthHandler
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

    def test_the_bus_and_their_own_feet_are_nobody_driving(self) -> None:
        # Written in "who drives" so the morning can say it and nobody is
        # asked to cover it; not anyone's drive, so nobody is told to leave.
        for value in ("the bus", "Bus", "takes the bus home", "walks", "on their own", "by herself",
                      "אוטובוס", "הסעה", "הולכת לבד הביתה"):
            self.assertTrue(household.nobody_drives(value), value)
            self.assertFalse(household.is_self(value, ["Bus Levi"]), value)
        # A person next to one of the words is still a person, and an empty
        # value is a gap, not this.
        for value in ("Dana", "Dana, by bus", "Grandma walks them", "me", "", None, "דנה"):
            self.assertFalse(household.nobody_drives(value), repr(value))
        on_the_bus = {"title": "School", "who": ["Lotan"], "dropOffBy": "the bus", "pickUpBy": "the bus"}
        self.assertEqual(household.activity_gaps(on_the_bus), [])

    def test_a_who_drives_word_is_kept_only_when_the_week_knows_who_it_is(self) -> None:
        # On 2026-10-07 "It differs", said about a Friday pickup, could have
        # been kept as the collector: a word that is nobody the week knows
        # files the drive under a stranger, and the pickup goes quiet - no
        # reminder, no question. So the word is checked before it is kept.
        family = [{"name": "Stav", "role": "partner"}, {"name": "Lahav", "role": "child"}, {"name": "Grandma Rina", "role": "other"}]
        owners = ["Nimrod Shai"]
        self.assertEqual(household.resolve_driver("me", family, owners), ("me", ""))
        self.assertEqual(household.resolve_driver("Nimrod", family, owners), ("me", ""))
        self.assertEqual(household.resolve_driver("stav", family, owners), ("Stav", ""))
        self.assertEqual(household.resolve_driver("Grandma", family, owners), ("Grandma Rina", ""))
        self.assertEqual(household.resolve_driver("the bus", family, owners), ("the bus", ""))
        self.assertEqual(household.resolve_driver("", family, owners), ("", ""))
        for word in ("Dad", "אבא", "varies", "differs", "ask me on Friday", "the neighbour"):
            self.assertEqual(household.resolve_driver(word, family, owners), (word, "unknown"), word)
        # A group has no "me": the word stays as said, so the room reads a name.
        self.assertEqual(household.resolve_driver("me", family, [], in_group=True), ("me", ""))

    def test_a_days_answer_sits_over_the_usual_week_for_that_day_alone(self) -> None:
        # "I'll pick up Lahav" answered the evening's question about one day.
        # The usual week keeps saying nobody; that Wednesday says him.
        school = {"id": 10, "title": "School", "who": ["Lahav"], "days": ["sun", "mon", "tue", "wed", "thu"], "dropOffBy": "me", "pickUpBy": ""}
        gan = {"id": 12, "title": "Gan", "who": ["Laor"], "days": ["sun", "mon", "tue", "wed", "thu"], "dropOffBy": "me", "pickUpBy": "Stav"}
        drives = [
            {"id": 1, "activityId": 10, "day": "2026-10-07", "leg": "pick_up", "who": "me"},
            {"id": 2, "activityId": 12, "day": "2026-10-07", "leg": "pick_up", "who": ""},
        ]
        wednesday = household.apply_day_drives([school, gan], drives, date(2026, 10, 7))
        self.assertEqual([(a["pickUpBy"], a.get("dayDriveLegs")) for a in wednesday], [("me", ["pick_up"]), ("", ["pick_up"])])
        thursday = household.apply_day_drives([school, gan], drives, date(2026, 10, 8))
        self.assertEqual([(a["pickUpBy"], a.get("dayDriveLegs")) for a in thursday], [("", None), ("Stav", None)])
        # The originals are untouched.
        self.assertEqual((school["pickUpBy"], gan["pickUpBy"]), ("", "Stav"))
        # The assistant reads them as a list from today on, each saying what and who.
        described = household.describe_day_drives(drives + [{"id": 0, "activityId": 10, "day": "2026-10-01", "leg": "pick_up", "who": "me"}], [school, gan], date(2026, 10, 7))
        self.assertEqual(
            [(d["id"], d["day"], d["weekday"], d["activity"], d["leg"], d.get("driver"), d.get("nobodyYet")) for d in described],
            [(1, "2026-10-07", "Wednesday", "School", "pick_up", "me", None), (2, "2026-10-07", "Wednesday", "Gan", "pick_up", None, True)],
        )
        block = household.describe_household(profile=None, members=[{"name": "Lahav", "role": "child"}], activities=[school, gan], today=date(2026, 10, 7), day_drives=drives)
        self.assertEqual([d["id"] for d in block["dayDrives"]], [1, 2])
        self.assertNotIn("dayDrives", household.describe_household(profile=None, members=[], activities=[school], today=date(2026, 10, 7)))

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

    def test_a_week_is_not_ready_until_every_child_is_placed_and_every_pickup_taken(self) -> None:
        # Nobody known yet is one question, not a list of them.
        self.assertEqual(household.week_setup_gaps([], []), [{"missing": "people"}])

        members = [{"name": "Stav", "role": "partner"}, {"name": "Lotan", "role": "child"}, {"name": "Laor", "role": "child"}]
        self.assertEqual(
            household.week_setup_gaps(members, []),
            [{"missing": "week", "who": "Lotan"}, {"missing": "week", "who": "Laor"}],
            "a partner needs no week of their own; a child does",
        )

        week = [
            {"id": 1, "title": "School", "who": ["Lotan"], "days": ["sun", "mon"], "endTime": "13:30", "dropOffBy": "me"},
            {"id": 2, "title": "Ballet", "who": ["Laor"], "days": [], "endTime": "", "dropOffBy": "Stav", "pickUpBy": "Stav"},
        ]
        self.assertEqual(
            household.week_setup_gaps(members, week),
            [
                {"missing": "days", "activity": "Ballet", "id": 2},
                {"missing": "times", "activity": "Ballet", "id": 2},
                {"missing": "pick_up", "activity": "School", "id": 1},
            ],
            "the bigger question comes first, and the pickup is never skipped",
        )
        self.assertFalse(household.week_is_ready(members, week))

        week[1].update({"days": ["wed"], "endTime": "17:00"})
        week[0]["pickUpBy"] = "Stav"
        self.assertTrue(household.week_is_ready(members, week))

    def test_school_hours_alone_are_not_a_finished_week(self) -> None:
        # The bug this is here for: a child's school went in, every pickup was
        # taken, the week called itself ready, and nobody was ever asked what
        # happens at four o'clock.
        members = [{"name": "Lahav", "role": "child"}, {"name": "Laor", "role": "child"}]
        week = [
            {"id": 1, "title": "School", "who": ["Lahav"], "days": ["sun", "mon"], "endTime": "13:45", "dropOffBy": "me", "pickUpBy": "Stav"},
            {"id": 2, "title": "Gan", "who": ["Laor"], "days": ["sun", "mon"], "endTime": "16:00", "dropOffBy": "me", "pickUpBy": "me"},
        ]
        self.assertEqual(household.week_setup_gaps(members, week), [], "nothing is missing from what was told")
        self.assertEqual(
            household.afternoon_gaps(members, week),
            [{"missing": "afternoons", "who": "Lahav", "after": "School"},
             {"missing": "afternoons", "who": "Laor", "after": "Gan"}],
        )

        block = household.describe_household(
            profile={"gettingToKnow": "in_progress"},
            members=members, activities=week, today=date(2026, 9, 24),
        )
        self.assertTrue(block["weekReady"], "a week they can be run is ready; this is a question, not a hole")
        # The children's afternoons first, and then the parent's own week.
        self.assertEqual([gap["who"] for gap in block["weekGaps"]], ["Lahav", "Laor", "me"])

        # A club after school is the answer, and the question does not come back.
        week.append({"id": 3, "title": "Football", "who": ["Lahav"], "days": ["tue"], "endTime": "17:30", "dropOffBy": "Stav", "pickUpBy": "Stav"})
        self.assertEqual([gap["who"] for gap in household.afternoon_gaps(members, week)], ["Laor"])

        # And once they have said that is everything, it is never asked again.
        closed = household.describe_household(
            profile={"gettingToKnow": "done"},
            members=members, activities=week, today=date(2026, 9, 24),
        )
        self.assertNotIn("weekGaps", closed)

    def test_the_parent_is_asked_about_their_own_week_once_the_children_are_in(self) -> None:
        # The point of the week is who collects, and the parent's work hours
        # are what says when it cannot be them. So they are asked - and it is
        # a question, never a hole: the week is ready whatever they answer.
        members = [{"name": "Stav", "role": "partner"}, {"name": "Lahav", "role": "child"}]
        week = [
            {"id": 1, "title": "School", "who": ["Lahav"], "days": ["sun"], "endTime": "13:45", "dropOffBy": "me", "pickUpBy": "Stav"},
            {"id": 2, "title": "Football", "who": ["Lahav"], "days": ["tue"], "endTime": "17:30", "dropOffBy": "Stav", "pickUpBy": "Stav"},
        ]
        self.assertEqual(household.own_week_gaps(members, week), [{"missing": "own_week", "who": "me"}])
        self.assertEqual(household.own_week_gaps([], []), [], "nobody known yet is the people question, not this one")
        self.assertEqual(household.own_week_gaps(members, week, calendar_connected=True), [], "their calendar already holds the answer")

        # Their work goes into the same week, as theirs: nobody takes or
        # collects a grown-up, so it has no gaps and the question is closed.
        work = {"id": 3, "title": "Work", "who": ["me"], "days": ["sun", "mon", "tue", "wed", "thu"], "startTime": "09:00", "endTime": "17:00"}
        self.assertTrue(household.is_grown_up_activity(work, members))
        self.assertEqual(household.activity_gaps(work, members), [])
        self.assertEqual(household.activity_gaps(work), ["drop_off", "pick_up"], "without the family it cannot tell")
        self.assertEqual(household.week_setup_gaps(members, week + [work]), [])
        self.assertEqual(household.own_week_gaps(members, week + [work]), [])

        # The partner's shift is theirs too; a child's club never is, and
        # neither is something for a name nobody knows.
        shift = {"id": 4, "title": "Night shift", "who": ["Stav"], "days": ["wed"], "startTime": "20:00", "endTime": "06:00"}
        self.assertTrue(household.is_grown_up_activity(shift, members))
        self.assertFalse(household.is_grown_up_activity(week[1], members))
        self.assertFalse(household.is_grown_up_activity({"who": ["Noa"]}, members))
        self.assertFalse(household.is_grown_up_activity({"who": []}, members))

        # Saved under their own name from the week page, it is still theirs.
        by_name = {"id": 5, "title": "Work", "who": ["Dana"], "days": ["sun"], "startTime": "09:00", "endTime": "17:00"}
        self.assertFalse(household.is_grown_up_activity(by_name, members))
        self.assertTrue(household.is_grown_up_activity(by_name, members, ["Dana Levi"]))
        self.assertEqual(household.own_week_gaps(members, week + [by_name], owner_names=["Dana Levi"]), [])

        block = household.describe_household(
            profile={"gettingToKnow": "in_progress"},
            members=members, activities=week + [work], today=date(2026, 9, 24),
        )
        self.assertTrue(block["weekReady"])
        self.assertTrue(block["week"][2]["grownUp"])
        self.assertNotIn("grownUp", block["week"][0])
        self.assertNotIn("nobodyDownFor", block["week"][2])
        self.assertNotIn("weekGaps", block, "the children are in and the parent has answered")

        asked = household.describe_household(
            profile={"gettingToKnow": "in_progress"},
            members=members, activities=week, today=date(2026, 9, 24),
        )
        self.assertEqual(asked["weekGaps"], [{"missing": "own_week", "who": "me"}])
        with_calendar = household.describe_household(
            profile={"gettingToKnow": "in_progress"},
            members=members, activities=week, today=date(2026, 9, 24), calendar_connected=True,
        )
        self.assertNotIn("weekGaps", with_calendar)

        # It is put once, in the first getting to know, and the profile
        # remembers that it was. A no, a later or no answer at all leaves
        # the week without their hours, and adding a chess club to it a
        # month on - with its own questions of who collects - never brings
        # the question of their own week back with it.
        self.assertEqual(household.own_week_gaps(members, week, asked=True), [])
        already_asked = {"gettingToKnow": "in_progress", "ownWeekAskedOn": "2026-09-10"}
        self.assertNotIn("weekGaps", household.describe_household(
            profile=already_asked, members=members, activities=week, today=date(2026, 9, 24),
        ))
        chess = {"id": 6, "title": "Chess", "who": ["Lahav"], "days": ["mon"], "endTime": "17:15", "dropOffBy": "Stav"}
        later = household.describe_household(
            profile=already_asked, members=members, activities=week + [chess], today=date(2026, 10, 11),
        )
        self.assertEqual([gap["missing"] for gap in later["weekGaps"]], ["pick_up"])

    def test_a_group_is_not_asked_the_afternoons_question(self) -> None:
        # A room of parents is keeping a rota, not being got to know.
        block = household.describe_household(
            profile=None,
            members=[{"name": "Noam", "role": "child"}],
            activities=[{"id": 1, "title": "Football", "who": ["Noam"], "days": ["tue"], "endTime": "17:30", "dropOffBy": "Dana", "pickUpBy": "Yonatan"}],
            today=date(2026, 9, 24),
            group_name="School run",
        )
        self.assertNotIn("weekGaps", block)

    def test_an_account_is_described_even_before_anyone_is_known(self) -> None:
        block = household.describe_household(profile={}, members=[], activities=[], today=date(2026, 9, 20))
        self.assertEqual(block["gettingToKnow"]["status"], "not_started")
        self.assertNotIn("accountKind", block)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.path)
        self.database.register_user("parent@example.com")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_a_days_answer_is_kept_for_its_date_and_replaced_by_the_next_one(self) -> None:
        school = self.database.save_household_activity(
            user_id=self.user_id, title="School", who=["Lahav"], days=["wed"], start_time="08:00", end_time="12:45",
            drop_off_by="me", pick_up_by="",
        )
        first = self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"], day="2026-10-07", leg="pickup", who="me")
        self.assertEqual((first["day"], first["leg"], first["who"]), ("2026-10-07", "pick_up", "me"))
        again = self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"], day="2026-10-07", leg="pick_up", who="Stav")
        self.assertEqual((again["id"], again["who"]), (first["id"], "Stav"))
        self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"], day="2026-10-14", leg="pick_up", who="")
        listed = self.database.list_household_day_drives(user_id=self.user_id, from_day="2026-10-07", to_day="2026-10-07")
        self.assertEqual([(d["day"], d["who"]) for d in listed], [("2026-10-07", "Stav")])
        self.assertEqual(len(self.database.list_household_day_drives(user_id=self.user_id)), 2)
        # Another scope's week is another store; a wrong day, leg or activity is refused.
        self.assertEqual(self.database.list_household_day_drives(user_id=self.user_id, group_id="g"), [])
        with self.assertRaises(ValueError):
            self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"], day="tomorrow", leg="pick_up", who="me")
        with self.assertRaises(ValueError):
            self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"], day="2026-10-07", leg="sideways", who="me")
        with self.assertRaises(LookupError):
            self.database.save_household_day_drive(user_id=self.user_id, activity_id=school["id"] + 9, day="2026-10-07", leg="pick_up", who="me")
        self.assertTrue(self.database.remove_household_day_drive(user_id=self.user_id, drive_id=first["id"]))
        self.assertFalse(self.database.remove_household_day_drive(user_id=self.user_id, drive_id=first["id"]))
        # The activity going takes its days with it.
        self.database.remove_household_activity(user_id=self.user_id, activity_id=school["id"])
        self.assertEqual(self.database.list_household_day_drives(user_id=self.user_id), [])

    def test_the_own_week_question_is_written_down_when_it_is_the_next_thing_to_ask(self) -> None:
        # The turn handler marks the profile at the moment the question is
        # the first gap in a turn that will speak to the person: that turn
        # asks it, and from then on the gap logic reads the mark and never
        # raises it again. A quiet "not now" (askNow false), another gap
        # ahead of it, or an account past getting to know marks nothing.
        handler = SimpleNamespace(database=self.database)
        own_week = {"goal": "family", "askNow": True, "weekGaps": [{"missing": "own_week", "who": "me"}]}
        pickup_first = {"goal": "family", "askNow": True, "weekGaps": [{"missing": "pick_up", "activity": 1}, {"missing": "own_week", "who": "me"}]}
        not_now = {"goal": "family", "askNow": False, "weekGaps": [{"missing": "own_week", "who": "me"}]}
        connecting = {"goal": "connect", "askNow": True, "weekGaps": [{"missing": "own_week", "who": "me"}]}
        for flow in (pickup_first, not_now, connecting, None):
            PortalAuthHandler._note_own_week_asked(handler, self.user_id, flow, "2026-10-11")
            self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {}).get("ownWeekAskedOn"), "")
        PortalAuthHandler._note_own_week_asked(handler, self.user_id, own_week, "2026-10-11")
        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual(profile["ownWeekAskedOn"], "2026-10-11")

        # And the mark is read back by the block the assistant sees.
        members = [{"name": "Lahav", "role": "child"}]
        week = [{"id": 1, "title": "School", "who": ["Lahav"], "days": ["sun"], "endTime": "13:45", "dropOffBy": "me", "pickUpBy": "me"},
                {"id": 2, "title": "Chess", "who": ["Lahav"], "days": ["mon"], "endTime": "17:15", "dropOffBy": "me", "pickUpBy": "me"}]
        self.assertNotIn("weekGaps", household.describe_household(profile=profile, members=members, activities=week, today=date(2026, 10, 11)))

    def test_a_database_from_before_the_mark_treats_a_week_already_begun_as_asked(self) -> None:
        # Before the mark existed the question was put whenever the week was
        # ready, so a family mid-way or further - getting to know begun, a
        # week with something in it - has had it. Catching up marks them,
        # which is what keeps the question from coming to them once more
        # after the deploy. A family who has not started is left to be asked.
        self.database.save_household_profile(user_id=self.user_id, getting_to_know="in_progress")
        self.database.save_household_activity(
            user_id=self.user_id, title="School", who=["Lahav"], days=["sun"], end_time="13:45", drop_off_by="me", pick_up_by="me",
        )
        self.database.register_user("new@example.com")
        new_user = int((self.database.get_user("new@example.com") or {})["id"])
        self.database.save_household_profile(user_id=new_user)
        with self.database._connection() as conn:
            conn.execute("ALTER TABLE household_profiles DROP COLUMN own_week_asked_on")

        reopened = PortalDatabase(self.path)

        self.assertRegex((reopened.get_household_profile(user_id=self.user_id) or {})["ownWeekAskedOn"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((reopened.get_household_profile(user_id=new_user) or {})["ownWeekAskedOn"], "")

    def test_a_database_from_before_groups_opens_and_catches_up(self) -> None:
        # What a deploy meets: a database written by the previous build. On
        # 2026-09-24 production would not start on one - the schema script
        # created an index over group_id in the same batch that was supposed
        # to add the column, so the deploy died with "no such column:
        # group_id" and the old instance stayed up instead.
        with self.database._connection() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_household_members_scope_name")
            conn.execute("DROP INDEX IF EXISTS idx_household_activities_user")
            conn.execute("ALTER TABLE household_members DROP COLUMN group_id")
            conn.execute("ALTER TABLE household_activities DROP COLUMN group_id")
            conn.execute("CREATE UNIQUE INDEX idx_household_members_name ON household_members(user_id, name_key)")

        reopened = PortalDatabase(self.path)

        with reopened._connection() as conn:
            members = {row["name"] for row in conn.execute("PRAGMA table_info(household_members)")}
            activities = {row["name"] for row in conn.execute("PRAGMA table_info(household_activities)")}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(household_members)")}
        self.assertIn("group_id", members)
        self.assertIn("group_id", activities)
        self.assertIn("idx_household_members_scope_name", indexes)
        self.assertNotIn("idx_household_members_name", indexes)

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

    def test_every_account_starts_with_the_family_still_to_be_met(self) -> None:
        profile = self.database.get_household_profile(user_id=self.user_id) or {}
        self.assertEqual(profile["gettingToKnow"], "not_started")
        self.assertNotIn("accountKind", profile)

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

        # The parent's own work hours: theirs, with nobody to collect them.
        work = self.run_tool(
            "save_week_activity", id=None, title="Work", who=["me"], days=["sun", "mon"], start_time="09:00",
            end_time="17:00", place=None, drop_off_by="", pick_up_by="", notes=None,
        )
        self.assertTrue(work["ok"], work)
        self.assertTrue(work["saved"]["grownUp"])
        self.assertEqual(work["saved"]["nobodyDownFor"], [])
        self.assertNotIn("grownUp", added["saved"])
        self.assertNotIn("nobodyDownFor", self.run_tool("show_family_week")["byDay"]["sun"][0])

    def test_a_collector_the_week_does_not_know_is_refused_not_kept(self) -> None:
        self.run_tool("save_family_member", name="Lahav", previous_name=None, role="child", age=8, school=None, email=None, phone=None, notes=None)
        self.run_tool("save_family_member", name="Stav", previous_name=None, role="partner", age=None, school=None, email=None, phone=None, notes=None)
        refused = self.run_tool(
            "save_week_activity", id=None, title="School", who=["Lahav"], days=["sun"], start_time="08:00",
            end_time="12:45", place=None, drop_off_by="me", pick_up_by="varies", notes=None,
        )
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["error"]["code"], "choice_required")
        self.assertIn("'varies' is not anyone the week knows", refused["error"]["whatHappened"])
        self.assertIn("assign_day_drive", refused["error"]["whatHappened"])
        self.assertEqual(refused["error"]["family"], ["Lahav", "Stav"])
        self.assertEqual(self.run_tool("show_family_week")["byDay"], {})
        # A member by first name, however spelt, is kept under their name.
        kept = self.run_tool(
            "save_week_activity", id=None, title="School", who=["Lahav"], days=["sun"], start_time="08:00",
            end_time="12:45", place=None, drop_off_by="me", pick_up_by="stav", notes=None,
        )
        self.assertEqual(kept["saved"]["pickUpBy"], "Stav")

    def test_an_answer_about_one_day_is_kept_for_that_day_and_the_week_is_untouched(self) -> None:
        from datetime import timedelta
        from packages.infrastructure.agent_loop import _household_payload
        from packages.infrastructure.agent_loop import _household_today

        self.run_tool("save_family_member", name="Lahav", previous_name=None, role="child", age=8, school=None, email=None, phone=None, notes=None)
        self.run_tool("save_family_member", name="Stav", previous_name=None, role="partner", age=None, school=None, email=None, phone=None, notes=None)
        school = self.run_tool(
            "save_week_activity", id=None, title="School", who=["Lahav"], days=list(household.WEEKDAY_CODES), start_time="08:00",
            end_time="12:45", place="Shaked", drop_off_by="me", pick_up_by="", notes=None,
        )["saved"]
        today = _household_today(self.context)
        tomorrow = (today + timedelta(days=1)).isoformat()
        saved = self.run_tool("assign_day_drive", id=school["id"], day=tomorrow, leg="pick_up", who="me")
        self.assertTrue(saved["ok"], saved)
        self.assertEqual((saved["saved"]["day"], saved["saved"]["leg"], saved["saved"]["driver"]), (tomorrow, "pick_up", "me"))
        self.assertIn("the week still says nobody", saved["note"])
        # The week itself still has nobody, and the day's answer rides beside it.
        block = _household_payload(self.context)
        self.assertEqual(block["week"][0]["nobodyDownFor"], ["pick_up"])
        self.assertEqual([(d["day"], d["driver"]) for d in block["dayDrives"]], [(tomorrow, "me")])
        self.assertEqual(self.run_tool("show_family_week")["dayDrives"][0]["activity"], "School")
        # "Stav can't tomorrow" leaves the day open; a stranger is refused here too.
        opened = self.run_tool("assign_day_drive", id=school["id"], day=tomorrow, leg="pick_up", who="")
        self.assertTrue(opened["saved"]["nobodyYet"])
        self.assertIn("raised again", opened["note"])
        self.assertFalse(self.run_tool("assign_day_drive", id=school["id"], day=tomorrow, leg="pick_up", who="Dad")["ok"])
        self.assertEqual(self.run_tool("assign_day_drive", id=school["id"], day="2020-01-01", leg="pick_up", who="me")["error"]["code"], "choice_required")
        self.assertEqual(self.run_tool("assign_day_drive", id=school["id"] + 9, day=tomorrow, leg="pick_up", who="me")["error"]["code"], "not_found")
        removed = self.run_tool("remove_day_drive", id=opened["saved"]["id"])
        self.assertTrue(removed["ok"])
        self.assertNotIn("dayDrives", _household_payload(self.context))
        self.assertEqual(self.run_tool("remove_day_drive", id=opened["saved"]["id"])["error"]["code"], "not_found")

    def test_saving_work_hours_names_the_drive_they_swallow_until_she_says_it_is_fine(self) -> None:
        self.run_tool("save_family_member", name="Noa", previous_name=None, role="child", age=7, school=None, email=None, phone=None, notes=None)
        self.run_tool("save_family_member", name="Yoav", previous_name=None, role="partner", age=None, school=None, email=None, phone=None, notes=None)
        school = self.run_tool(
            "save_week_activity", id=None, title="Gretz school", who=["Noa"], days=["mon"], start_time="08:00",
            end_time="13:30", place=None, drop_off_by="Yoav", pick_up_by="me", notes=None,
        )
        self.assertEqual(school["saved"]["driveDuringWork"], [])
        work = self.run_tool(
            "save_week_activity", id=None, title="Work", who=["me"], days=["mon"], start_time="09:00",
            end_time="17:00", place="the office", drop_off_by="", pick_up_by="", notes=None,
        )
        self.assertEqual(work["saved"]["driveDuringWork"], [{
            "id": school["saved"]["id"], "title": "Gretz school", "leg": "pick_up", "at": "13:30",
            "inside": "Work at the office 09:00-17:00", "days": ["mon"],
        }])
        shown = self.run_tool("show_family_week")["byDay"]["mon"]
        self.assertIn("driveDuringWork", next(entry for entry in shown if entry["title"] == "Gretz school"))
        accepted = self.run_tool("accept_drive_during_work", id=school["saved"]["id"], leg="pick_up")
        self.assertEqual(accepted["accepted"], {"id": school["saved"]["id"], "title": "Gretz school", "leg": "pick_up", "fineDuringWork": ["pick_up"]})
        shown = self.run_tool("show_family_week")["byDay"]["mon"]
        self.assertNotIn("driveDuringWork", next(entry for entry in shown if entry["title"] == "Gretz school"))
        self.assertEqual(self.run_tool("accept_drive_during_work", id=999, leg="pick_up")["error"]["code"], "not_found")
        self.assertEqual(self.run_tool("accept_drive_during_work", id=school["saved"]["id"], leg="lunch")["error"]["code"], "choice_required")

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
            profile={"gettingToKnow": "in_progress"},
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
        # The model is told the week link is the family's to share.
        for result in (week, done):
            self.assertIn("safe to forward to the family", result["weekPageSharing"])

    def test_asking_to_see_a_day_or_the_week_is_answered_with_the_picture_not_the_page(self) -> None:
        # "What's on today?" / "show me this week" used to get the week page
        # link. The page is for changing the week; seeing it is the picture.
        self.run_tool("save_family_member", name="Tom", previous_name=None, role="child", age=4, school=None, email=None, phone=None, notes=None)
        self.run_tool(
            "save_week_activity", id=None, title="Football", who=["Tom"], days=["tue"], start_time="17:00",
            end_time="18:00", place=None, drop_off_by="me", pick_up_by="", notes=None,
        )
        asked: list[tuple] = []
        self.context.week_link = lambda: "https://assistyca.com/week/open/abc"
        self.context.week_picture = lambda first, last, title: (
            asked.append((first, last, title)) or f"https://assistyca.com/week/image/{title}.png"
        )
        today = _household_today(self.context)
        sunday = today - timedelta(days=(today.weekday() + 1) % 7)

        shown = self.run_tool("show_family_week", picture="today")
        self.assertEqual(shown["picture"]["url"], "https://assistyca.com/week/image/today.png")
        self.assertIn("Do not offer the week page", shown["picture"]["note"])
        self.assertNotIn("weekPage", shown)
        self.assertIn("byDay", shown, "the facts stay, so the caption can say what still has nobody")
        self.assertEqual(self.context.pictures, ["https://assistyca.com/week/image/today.png"])
        self.assertEqual(asked[-1], (today, today, "today"))

        self.run_tool("show_family_week", picture="tomorrow")
        self.assertEqual(asked[-1], (today + timedelta(days=1), today + timedelta(days=1), "tomorrow"))
        self.run_tool("show_family_week", picture="this_week")
        self.assertEqual(asked[-1], (sunday, sunday + timedelta(days=6), "this_week"))
        self.run_tool("show_family_week", picture="next_week")
        self.assertEqual(asked[-1], (sunday + timedelta(days=7), sunday + timedelta(days=13), "week_ahead"))
        self.assertEqual(len(self.context.pictures), 4)

        # A question about one thing is not a request to see the day.
        plain = self.run_tool("show_family_week", picture="none")
        self.assertNotIn("picture", plain)
        self.assertEqual(plain["weekPage"], "https://assistyca.com/week/open/abc")
        self.assertEqual(len(asked), 4)

    def test_a_picture_that_cannot_be_drawn_falls_back_to_words_and_the_page(self) -> None:
        self.context.week_link = lambda: "https://assistyca.com/week/open/abc"
        for builder in (None, lambda *a: "", lambda *a: (_ for _ in ()).throw(RuntimeError("no fonts"))):
            self.context.week_picture = builder
            shown = self.run_tool("show_family_week", picture="today")
            self.assertNotIn("picture", shown)
            self.assertIn("answer in words", shown["pictureNote"])
            self.assertEqual(shown["weekPage"], "https://assistyca.com/week/open/abc")
        self.assertEqual(self.context.pictures, [])


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

    def test_the_nudger_can_ask_for_one_day_of_the_owners_calendar(self) -> None:
        # Read over loopback with a session for the account, like the inbox
        # watch poll. Nothing connected is an empty day, not an error.
        status, body = self.request("POST", "/api/family-week/calendar-day", {"day": "2026-09-21", "timezone": "Asia/Jerusalem"})
        self.assertEqual((status, body["ok"], body["day"], body["events"]), (200, True, "2026-09-21", []))
        status, body = self.request("POST", "/api/family-week/calendar-day", {"day": "tomorrow", "timezone": "Asia/Jerusalem"})
        self.assertEqual((status, body["error"]), (400, "invalid_day"))
        status, _ = self.request("POST", "/api/family-week/calendar-day", {"day": "2026-09-21"}, signed_in=False)
        self.assertEqual(status, 401)

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
            page = response.read().decode()
        self.assertIn("week.js", page)
        # People are picked as chips, and Save waits for a complete row.
        for marker in ('id="fieldWho" class="chips"', 'id="fieldDropOff" class="chips"', 'id="fieldPickUp" class="chips"', 'id="saveButton" class="button primary" type="submit" disabled'):
            self.assertIn(marker, page)
        code = self.database.create_list_open_code(user_id=self.user_id, list_id=0, expires_at=time.time() + 60)
        opener = urllib_request.build_opener(_NoRedirect)
        try:
            opener.open(f"{self.base_url}/week/open/{code}", timeout=10)
            self.fail("expected a redirect")
        except urllib_error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            self.assertEqual(exc.headers["Location"], "/week")
            self.assertIn("assistyca_portal_session", exc.headers.get("Set-Cookie", ""))



class FamilyOnTheirOwnPhonesTests(unittest.TestCase):
    """The partner and the grandparents on the same account, from their own
    phones: brought in by a link, told about the drives that are theirs, and
    - unless they are a parent - never changing the week."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portal.db"
        self.database = PortalDatabase(self.path)
        self.database.register_user("parent@example.com", display_name="Dana Levi")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.yoav = self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")
        self.rina = self.database.save_household_member(user_id=self.user_id, name="Rina", role="other")
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", age=4)
        self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun"],
            start_time="07:30", end_time="16:00", drop_off_by="me", pick_up_by="Yoav",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def invite(self, member: dict, code: str, *, days: int = 14) -> dict:
        from datetime import datetime, timedelta, timezone

        return self.database.create_household_invite(
            user_id=self.user_id, member_id=int(member["id"]), code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        )

    def test_a_name_is_not_me_and_only_the_parents_change_the_week(self) -> None:
        self.assertTrue(household.is_named("Yoav", ["Yoav Levi"]))
        self.assertTrue(household.is_named("yoav levi", ["Yoav Levi"]))
        self.assertFalse(household.is_named("me", ["Yoav"]), "'me' is the account holder, never a named member")
        self.assertFalse(household.is_named("the bus", ["Bus"]))
        self.assertTrue(household.can_change_week("owner"))
        self.assertTrue(household.can_change_week("partner"))
        self.assertFalse(household.can_change_week("other"))
        self.assertEqual(household.member_nudges("partner"), ("morning", "evening", "rides"))
        self.assertEqual(household.member_nudges("other"), ("rides",))
        self.assertEqual(household.member_thread_id("+972 50-000-0002"), "phone:972500000002")

        partner = household.describe_speaker({"name": "Yoav", "role": "partner"}, owner_name="Dana Levi")
        self.assertEqual(partner, {"name": "Yoav", "role": "partner", "isOwner": False, "canChangeWeek": True, "drivesAs": "Yoav", "accountHolder": "Dana Levi"})
        self.assertFalse(household.describe_speaker({"name": "Rina", "role": "other"})["canChangeWeek"])
        self.assertEqual(household.describe_speaker(None), {})

        # The grown-ups not yet on the account, partner first; a child never.
        members = self.database.list_household_members(user_id=self.user_id)
        self.assertEqual([c["name"] for c in household.invite_candidates(members)], ["Yoav", "Rina"])
        self.assertEqual(household.invite_candidates(members)[0]["theyGet"], ("morning", "evening", "rides"))
        joined = [{**m, "waId": "972500000002"} if m["name"] == "Yoav" else m for m in members]
        self.assertEqual([c["name"] for c in household.invite_candidates(joined)], ["Rina"])
        block = household.describe_household(profile={}, members=joined, activities=[], today=date(2026, 9, 20))
        self.assertEqual([m.get("onWhatsApp") for m in block["members"]], [True, None, None])

    def test_an_invitation_brings_a_phone_onto_the_account_as_that_person(self) -> None:
        from datetime import datetime, timedelta, timezone

        made = self.invite(self.yoav, "ABC234")
        self.assertEqual((made["memberName"], made["role"]), ("Yoav", "partner"))
        self.assertEqual(self.database.get_household_invite("abc234")["status"], "live")
        with self.assertRaises(ValueError):
            tom = next(m for m in self.database.list_household_members(user_id=self.user_id) if m["name"] == "Tom")
            self.invite(tom, "TOM234")

        joined = self.database.claim_household_invite(code="ABC234", wa_id="972500000002", label="Yoav")
        self.assertTrue(joined["ok"], joined)
        self.assertEqual(joined["member"]["waId"], "972500000002")
        # The phone reaches this account, as this member, and the code is spent.
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("972500000002"), self.user_id)
        self.assertEqual(self.database.get_household_member_by_wa_id("972500000002", user_id=self.user_id)["name"], "Yoav")
        self.assertEqual(self.database.get_household_invite("ABC234")["status"], "claimed")
        self.assertEqual(self.database.claim_household_invite(code="ABC234", wa_id="972500000003")["reason"], "already_claimed")
        self.assertEqual(self.database.claim_household_invite(code="NOPE22", wa_id="972500000003")["reason"], "unknown_code")

        # A phone that already has an account of its own is not moved.
        self.database.register_user("other@example.com")
        other_id = int((self.database.get_user("other@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=other_id, wa_id="972500000009")
        self.invite(self.rina, "RINA22")
        self.assertEqual(self.database.claim_household_invite(code="RINA22", wa_id="972500000009")["reason"], "number_taken")
        # One live invitation per person: a fresh one retires the last. The
        # retired one is still known, so whoever opens it later is told to
        # use the newer link rather than taken for a stranger.
        stale = self.database.create_household_invite(
            user_id=self.user_id, member_id=int(self.rina["id"]), code="RINA44",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.assertEqual(self.database.get_household_invite("RINA22")["status"], "expired")
        self.assertEqual(self.database.get_household_invite(stale["code"])["status"], "expired")
        self.assertEqual(self.database.claim_household_invite(code="RINA44", wa_id="972500000005")["reason"], "expired")
        self.invite(self.rina, "RINA33")
        self.assertEqual(self.database.get_household_invite("RINA44")["status"], "expired")
        self.assertEqual(self.database.get_household_invite("RINA33")["status"], "live")
        # The account holder's own phone is the one "the owner" means, however
        # many family phones joined after it.
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id="972500000001")
        self.assertEqual(self.database.get_owner_whatsapp_number(user_id=self.user_id), "972500000001")

        # Each phone has a conversation of its own, with its own open question.
        thread = household.member_thread_id("972500000002")
        self.database.save_whatsapp_agent_pending(user_id=self.user_id, pending={"kind": "tool_confirmation"}, thread_id=thread)
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=self.user_id))
        self.assertEqual(self.database.get_whatsapp_agent_pending(user_id=self.user_id, thread_id=thread)["kind"], "tool_confirmation")
        self.database.save_whatsapp_agent_active_proposal(user_id=self.user_id, proposal={"type": "x"}, thread_id=thread)
        self.assertIsNone(self.database.get_whatsapp_agent_active_proposal(user_id=self.user_id))

        # Signing the phone out keeps the person in the family and takes the
        # phone, and its thread's state, off the account.
        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id="972500000002"))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("972500000002"), 0)
        self.assertEqual(next(m for m in self.database.list_household_members(user_id=self.user_id) if m["name"] == "Yoav")["waId"], "")
        self.assertIsNone(self.database.get_whatsapp_agent_pending(user_id=self.user_id, thread_id=thread))

        # Taking someone out of the family takes their phone off with them.
        self.database.claim_household_invite(code="RINA33", wa_id="972500000005")
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("972500000005"), self.user_id)
        self.assertTrue(self.database.remove_household_member(user_id=self.user_id, name="Rina"))
        self.assertEqual(self.database.get_user_id_for_whatsapp_number("972500000005"), 0)
        self.assertIsNone(self.database.get_household_invite("RINA33"))

    def test_a_database_from_before_invitations_opens_and_catches_up(self) -> None:
        with self.database._connection() as conn:
            conn.execute("DROP TABLE household_invites")
            conn.execute("DROP TABLE whatsapp_agent_thread_state")
            conn.execute("ALTER TABLE household_members DROP COLUMN wa_id")
            conn.execute("ALTER TABLE household_members DROP COLUMN wa_linked_at")
        reopened = PortalDatabase(self.path)
        with reopened._connection() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(household_members)")}
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("wa_id", columns)
        self.assertIn("household_invites", tables)
        self.assertIn("whatsapp_agent_thread_state", tables)
        self.assertEqual(reopened.list_household_members(user_id=self.user_id)[0]["waId"], "")

    def test_done_offers_the_partner_and_the_invitation_is_a_link_to_forward(self) -> None:
        context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp",
            join_link=lambda code: f"https://assistyca.com/join/{code}",
        )
        done = TOOLS_BY_NAME["set_getting_to_know"].run(context, {"status": "done", "ask_again_in_days": None})
        self.assertEqual([c["name"] for c in done["inviteOffer"]], ["Yoav", "Rina"])

        invited = TOOLS_BY_NAME["invite_family_member"].run(context, {"name": "yoav"})
        self.assertTrue(invited["ok"], invited)
        self.assertEqual((invited["forName"], invited["role"], invited["canChangeWeek"]), ("Yoav", "partner", True))
        # What a partner shares and what stays the holder's, said before the link goes out.
        self.assertEqual(invited["sharing"]["shared"], ["the family's week", "the lists", "the scheduled tasks"])
        self.assertEqual(invited["sharing"]["staysTheAccountHolders"], ["their mail", "their calendar", "their receipts"])
        self.assertIn("only when each parent is busy, never what", invited["sharing"]["calendarsCross"])
        self.assertRegex(invited["link"], r"^https://assistyca\.com/join/[A-Z2-9]{6}$")
        code = invited["link"].rsplit("/", 1)[1]
        self.assertEqual(self.database.get_household_invite(code)["memberName"], "Yoav")
        # The link stays written in the reply for forwarding: it is offered,
        # so the guard keeps it, and it is not turned into a button.
        self.assertIn(invited["link"], context.links_offered)
        self.assertIn(invited["link"], context.links_in_text)

        refused = TOOLS_BY_NAME["invite_family_member"].run(context, {"name": "Tom"})
        self.assertEqual(refused["error"]["code"], "not_supported")
        nobody = TOOLS_BY_NAME["invite_family_member"].run(context, {"name": "Noa"})
        self.assertEqual((nobody["error"]["code"], nobody["error"]["known"]), ("not_found", ["Yoav", "Tom", "Rina"]))
        self.database.claim_household_invite(code=code, wa_id="972500000002")
        again = TOOLS_BY_NAME["invite_family_member"].run(context, {"name": "Yoav"})
        self.assertEqual(again["error"]["code"], "not_supported")
        self.assertEqual(TOOLS_BY_NAME["set_getting_to_know"].run(context, {"status": "done", "ask_again_in_days": None})["inviteOffer"][0]["name"], "Rina")
        # Without a way to build the link, nothing is promised.
        bare = LoopContext(api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com", user_id=self.user_id)
        self.assertEqual(TOOLS_BY_NAME["invite_family_member"].run(bare, {"name": "Rina"})["error"]["code"], "not_supported")

    def test_a_grandparent_reads_the_week_and_a_partner_cannot_close_the_account(self) -> None:
        from packages.infrastructure.agent_loop import FAMILY_GUEST_TOOLS
        from packages.infrastructure.agent_loop import WEEK_CHANGE_TOOLS
        from packages.infrastructure.agent_loop import tool_availability
        from packages.infrastructure.agent_loop import tool_definitions

        grandparent = household.describe_speaker({"name": "Rina", "role": "other"}, owner_name="Dana")
        partner = household.describe_speaker({"name": "Yoav", "role": "partner"}, owner_name="Dana")
        for name in WEEK_CHANGE_TOOLS | {"read_inbox", "search_receipts", "show_lists", "delete_account", "connect_link", "check_family_busy"}:
            self.assertFalse(tool_availability(TOOLS_BY_NAME[name], {}, {}, speaker=grandparent).usable, name)
        for name in FAMILY_GUEST_TOOLS:
            self.assertTrue(tool_availability(TOOLS_BY_NAME[name], {}, {}, speaker=grandparent).usable, name)
        self.assertEqual(tool_availability(TOOLS_BY_NAME["save_week_activity"], {}, {}, speaker=grandparent).code, "not_theirs")
        # A partner has the week, the lists, the scheduled actions and their
        # own mail and calendar - which the tools read as theirs alone. The
        # account holder's own records, and closing the account, are not.
        mine = {"gmail": {"platformConnected": True}, "calendar": {"platformConnected": True}}
        for name in (
            "save_week_activity", "invite_family_member", "create_list", "show_lists", "schedule_task",
            "show_scheduled", "cancel_scheduled", "read_inbox", "read_calendar", "search_receipts",
            "connect_link", "disconnect", "check_family_busy",
        ):
            self.assertTrue(tool_availability(TOOLS_BY_NAME[name], mine, {}, speaker=partner).usable, name)
        for name in ("delete_account", "open_receipts", "show_insurance_policies"):
            self.assertFalse(tool_availability(TOOLS_BY_NAME[name], mine, {}, speaker=partner).usable, name)
        self.assertTrue(tool_availability(TOOLS_BY_NAME["delete_account"], {}, {}).usable)
        self.assertTrue(tool_availability(TOOLS_BY_NAME["open_receipts"], {}, {}).usable)
        shown = {tool["name"]: tool for tool in tool_definitions({}, {}, speaker=grandparent)}
        self.assertIn("UNAVAILABLE RIGHT NOW", shown["save_week_activity"]["description"])
        self.assertNotIn("UNAVAILABLE", shown["show_family_week"]["description"])

        # The turn says who is writing, and how to read "me" and their name.
        text = build_loop_context_text(
            user_message="can you pick Tom up today?", conversation=[], timezone_name="Asia/Jerusalem", today="2026-09-20",
            tool_context={}, facts=[], channel="whatsapp", speaker={**grandparent, "firstConversation": True, "theyGet": ["rides"]},
        )
        self.assertIn("CONTEXT.speaker says the person writing is not the account holder", text)
        self.assertIn("'me' is always the account holder", text)
        self.assertIn('"speaker":{"name":"Rina","role":"other","isOwner":false,"canChangeWeek":false,"drivesAs":"Rina","accountHolder":"Dana","firstConversation":true,"theyGet":["rides"]}', text)
        self.assertNotIn("CONTEXT.speaker", build_loop_context_text(
            user_message="hi", conversation=[], timezone_name="UTC", today="2026-09-20", tool_context={}, facts=[], channel="whatsapp",
        ))


class LeavingTheFamilyTests(unittest.TestCase):
    """Someone taken off the family leaves nothing behind that still acts
    for them: no reminder, no standing action, and no drive still written
    under their name. Signing a phone out ends nothing, for anyone: what
    was set for it waits until the phone is back, and only being taken off
    the family or the account being deleted ends it."""

    YOAV_PHONE = "972500000002"

    def setUp(self) -> None:
        from datetime import datetime, timedelta, timezone

        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("parent@example.com", display_name="Dana Levi")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id="972500000001")
        yoav = self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", age=4)
        self.activity = self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun", "tue"],
            start_time="07:30", end_time="16:00", drop_off_by="me", pick_up_by="Yoav",
        )
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(yoav["id"]), code="ABC234",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        self.database.claim_household_invite(code="ABC234", wa_id=self.YOAV_PHONE, label="Yoav")
        self.tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _action(self, recipient: str, *, action_type: str = "send_message") -> dict:
        from datetime import datetime, timedelta, timezone

        payload = {"messageText": "Take the bins out", "instruction": "Summarise the news", "recipientWaId": recipient}
        return self.database.create_scheduled_action(
            user_id=self.user_id, action_type=action_type, channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(timezone.utc) + timedelta(hours=1), timezone_name="Asia/Jerusalem", payload=payload,
        )

    def _status(self, action: dict) -> str:
        return str((self.database.get_scheduled_action(int(action["id"])) or {}).get("status"))

    def test_taking_someone_off_calls_off_what_was_set_for_their_phone(self) -> None:
        reminder = self._action(self.YOAV_PHONE)
        standing = self._action(self.YOAV_PHONE, action_type="run_task")
        owners = self._action("972500000001")

        removed = self.database.remove_household_member(user_id=self.user_id, name="yoav")

        self.assertTrue(removed["phoneUnlinked"])
        self.assertEqual((self._status(reminder), self._status(standing)), ("cancelled", "cancelled"))
        self.assertEqual(self._status(owners), "pending", "the account holder's own reminders stay")

    def test_a_member_signing_their_phone_out_holds_what_was_set_for_it_until_they_are_back(self) -> None:
        from datetime import datetime, timedelta, timezone
        from unittest import mock

        from packages.infrastructure.scheduled_actions import ScheduledActionConfig
        from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

        now = datetime.now(timezone.utc)
        reminder = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="send_message", channel="whatsapp", recipient_ref="owner",
            run_at=now - timedelta(seconds=5), timezone_name="Asia/Jerusalem",
            payload={"messageText": "Take the bins out", "recipientWaId": self.YOAV_PHONE, "oneOff": True},
        )
        standing = self._action(self.YOAV_PHONE, action_type="run_task")

        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=self.YOAV_PHONE))
        self.assertEqual((self._status(reminder), self._status(standing)), ("pending", "pending"))

        ran: list[dict] = []
        scheduler = ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: ran.append(action) or "done",
        )
        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", return_value="wamid.1") as send:
            scheduler.run_pending(now=now)
            # Signed out: nothing goes to the phone, and nothing is called off.
            send.assert_not_called()
            self.assertEqual(ran, [])
            self.assertEqual((self._status(reminder), self._status(standing)), ("pending", "pending"))

            # Back through a fresh invitation from the same phone: it goes.
            yoav = next(m for m in self.database.list_household_members(user_id=self.user_id) if m["name"] == "Yoav")
            self.database.create_household_invite(
                user_id=self.user_id, member_id=int(yoav["id"]), code="DEF567", expires_at=now + timedelta(days=14),
            )
            self.database.claim_household_invite(code="DEF567", wa_id=self.YOAV_PHONE, label="Yoav")
            scheduler.run_pending(now=now + timedelta(hours=2))
        self.assertEqual(self._status(reminder), "sent")

    def test_taking_off_a_member_who_signed_out_still_ends_what_was_set_for_their_phone(self) -> None:
        reminder = self._action(self.YOAV_PHONE)
        standing = self._action(self.YOAV_PHONE, action_type="run_task")
        self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=self.YOAV_PHONE)

        removed = self.database.remove_household_member(user_id=self.user_id, name="Yoav")

        self.assertFalse(removed["phoneUnlinked"], "the phone was already signed out")
        self.assertEqual((self._status(reminder), self._status(standing)), ("cancelled", "cancelled"))
        self.assertTrue(self.database.phone_left_family(user_id=self.user_id, wa_id=self.YOAV_PHONE))

    def test_deleting_the_account_ends_every_scheduled_action_it_had(self) -> None:
        actions = [
            self._action("972500000001"),
            self._action("972500000001", action_type="run_task"),
            self._action(self.YOAV_PHONE),
            self._action(self.YOAV_PHONE, action_type="run_task"),
        ]
        self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=self.YOAV_PHONE)

        self.database.delete_user("parent@example.com")

        self.assertEqual([self.database.get_scheduled_action(int(action["id"])) for action in actions], [None] * 4)

    def test_the_scheduler_never_acts_for_a_phone_that_left_the_account(self) -> None:
        from datetime import datetime, timedelta, timezone
        from unittest import mock

        from packages.infrastructure.scheduled_actions import ScheduledActionConfig
        from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

        # Written straight to the store after the phone went, the way a
        # standing action already running when it was removed comes back.
        self.database.remove_household_member(user_id=self.user_id, name="Yoav")
        orphan = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=5), timezone_name="Asia/Jerusalem",
            payload={"instruction": "Read my inbox", "recipientWaId": self.YOAV_PHONE},
        )
        ran: list[dict] = []
        scheduler = ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: ran.append(action) or "done",
        )
        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", return_value="wamid.1") as send:
            scheduler.run_pending(now=datetime.now(timezone.utc))
        self.assertEqual(ran, [], "the standing action never ran with the account's reach")
        send.assert_not_called()
        self.assertEqual(self._status(orphan), "cancelled")

    def test_the_account_holder_signing_out_keeps_what_they_set_and_it_runs_when_they_are_back(self) -> None:
        from datetime import datetime, timedelta, timezone
        from unittest import mock

        from packages.infrastructure.scheduled_actions import ScheduledActionConfig
        from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

        holder = "972500000001"
        now = datetime.now(timezone.utc)
        standing = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="run_task", channel="whatsapp", recipient_ref="owner",
            run_at=now - timedelta(seconds=5), timezone_name="Asia/Jerusalem",
            payload={"instruction": "Read my inbox", "recipientWaId": holder,
                     "schedule": {"frequency": "daily", "timeLocal": "08:00"}},
        )
        reminder = self.database.create_scheduled_action(
            user_id=self.user_id, action_type="send_message", channel="whatsapp", recipient_ref="owner",
            run_at=now - timedelta(seconds=5), timezone_name="Asia/Jerusalem",
            payload={"messageText": "Take the bins out", "recipientWaId": holder, "oneOff": True},
        )

        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=holder))
        self.assertEqual((self._status(standing), self._status(reminder)), ("pending", "pending"))

        ran: list[dict] = []
        scheduler = ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: ran.append(action) or "done",
        )
        with mock.patch("packages.infrastructure.whatsapp_messaging.send_whatsapp_message", return_value="wamid.1") as send:
            scheduler.run_pending(now=now)
            # Signed out: nothing goes to the phone, and nothing is called off.
            self.assertEqual(ran, [])
            send.assert_not_called()
            self.assertEqual((self._status(standing), self._status(reminder)), ("pending", "pending"))

            # Back on the account: the reminder goes, and the standing
            # action runs at its next time.
            self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=holder)
            later = datetime.fromisoformat(str(self.database.get_scheduled_action(int(standing["id"]))["runAt"]))
            scheduler.run_pending(now=max(later, now + timedelta(hours=2)) + timedelta(seconds=1))
        self.assertEqual(len(ran), 1, "the standing action ran once the phone was back")
        self.assertEqual(self._status(reminder), "sent")
        self.assertEqual(self._status(standing), "pending", "and stays on for its next run")

    def test_the_note_that_someone_joined_waits_for_a_signed_out_holder(self) -> None:
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from unittest import mock

        from packages.infrastructure.portal_auth.server import PortalAuthHandler
        from packages.infrastructure.scheduled_actions import ScheduledActionConfig
        from packages.infrastructure.scheduled_actions import ScheduledActionScheduler

        holder = "972500000001"
        self.assertTrue(self.database.delete_user_whatsapp_number(user_id=self.user_id, wa_id=holder))
        PortalAuthHandler._tell_owner_someone_joined(
            SimpleNamespace(database=self.database), self.user_id, {"name": "Rina", "role": "other"},
        )
        [note] = [a for a in self.database.list_scheduled_actions_for_user(self.user_id, limit=20) if a["payload"].get("title") == "Rina joined"]
        self.assertEqual((note["channel"], note["recipientRef"]), ("whatsapp", "owner"))

        scheduler = ScheduledActionScheduler(
            self.database,
            config=ScheduledActionConfig(enabled=True, poll_seconds=1, batch_size=10),
            task_runner=lambda action: "Rina is in",
        )
        now = datetime.now(timezone.utc) + timedelta(seconds=5)
        with mock.patch.object(ScheduledActionScheduler, "_deliver_whatsapp", return_value="wamid.1") as send:
            scheduler.run_pending(now=now)
            send.assert_not_called()
            self.assertEqual(self._status(note), "pending", "held, not marked sent into a feed nobody reads")

            self.database.link_user_whatsapp_number(user_id=self.user_id, wa_id=holder)
            scheduler.run_pending(now=now + timedelta(hours=2))
            send.assert_called_once()
        self.assertEqual(self._status(note), "sent")
        self.assertEqual(self.database.get_scheduled_action(int(note["id"]))["payload"]["deliveredVia"], "whatsapp")

    def test_taking_one_savta_off_leaves_a_drive_that_could_be_the_other(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Savta Ruti", role="other")
        self.database.save_household_member(user_id=self.user_id, name="Savta Miri", role="other")
        self.database.save_household_day_drive(
            user_id=self.user_id, activity_id=int(self.activity["id"]), day=self.tomorrow, leg="drop_off", who="Savta",
        )
        self.database.save_household_day_drive(
            user_id=self.user_id, activity_id=int(self.activity["id"]), day=self.tomorrow, leg="pick_up", who="Savta Ruti",
        )

        removed = self.database.remove_household_member(user_id=self.user_id, name="Savta Ruti")

        self.assertEqual([(d["leg"], d.get("day")) for d in removed["drivesNowOpen"]], [("pick_up", self.tomorrow)])
        whose = {
            row["leg"]: row["who"] for row in self.database.list_household_day_drives(
                user_id=self.user_id, from_day=self.tomorrow, to_day=self.tomorrow,
            )
        }
        self.assertEqual(whose, {"drop_off": "Savta", "pick_up": ""})

    def test_their_drives_are_left_open_so_the_week_asks_about_them(self) -> None:
        self.database.save_household_day_drive(
            user_id=self.user_id, activity_id=int(self.activity["id"]), day=self.tomorrow, leg="drop_off", who="Yoav",
        )
        removed = self.database.remove_household_member(user_id=self.user_id, name="Yoav")

        self.assertEqual(removed["drivesNowOpen"], [
            {"activityId": self.activity["id"], "title": "Kindergarten", "leg": "pick_up"},
            {"activityId": self.activity["id"], "title": "Kindergarten", "leg": "drop_off", "day": self.tomorrow},
        ])
        [kindergarten] = self.database.list_household_activities(user_id=self.user_id)
        self.assertEqual((kindergarten["dropOffBy"], kindergarten["pickUpBy"]), ("me", ""))
        self.assertEqual(household.activity_gaps(kindergarten), ["pick_up"])
        [day] = self.database.list_household_day_drives(user_id=self.user_id)
        self.assertEqual((day["day"], day["leg"], day["who"]), (self.tomorrow, "drop_off", ""))

    def test_taking_someone_off_needs_a_yes_that_names_what_goes_with_them(self) -> None:
        tool = TOOLS_BY_NAME["remove_family_member"]
        self.assertTrue(tool.confirm)
        context = LoopContext(
            api=lambda *a, **k: ({}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", sender_wa_id="972500000001",
        )
        from packages.infrastructure.agent_loop import _describe_call

        described = _describe_call(context, tool, {"name": "Yoav"})
        self.assertIn("take Yoav out of the family", described)
        self.assertIn("phone stops reaching the account", described)
        self.assertIn("1 drive(s)", described)
        self.assertEqual(tool.preflight(context, {"name": "Noa"})["error"]["code"], "not_found")

        done = tool.run(context, {"name": "Yoav"})
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["drivesNowOpen"][0]["leg"], "pick_up")
        self.assertIn("Nobody is down for these drives", done["note"])

    def test_a_member_signing_out_is_told_how_to_come_back_without_an_email(self) -> None:
        context = LoopContext(
            api=lambda *a, **k: ({"ok": True}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", sender_wa_id=self.YOAV_PHONE,
            speaker=household.describe_speaker({"name": "Yoav", "role": "partner"}, owner_name="Dana Levi"),
        )
        note = TOOLS_BY_NAME["sign_out"].run(context, {})["note"]
        self.assertIn("Dana Levi sends them a fresh invitation link", note)
        self.assertNotIn("email", note)
        # The account holder whose account this phone opened comes back by
        # writing in; nobody is asked for an email.
        from packages.infrastructure.whatsapp_agent_chat import whatsapp_account_email

        owner = LoopContext(
            api=lambda *a, **k: ({"ok": True}, 200), database=self.database, email=whatsapp_account_email("972500000001"),
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", sender_wa_id="972500000001",
        )
        note = TOOLS_BY_NAME["sign_out"].run(owner, {})["note"]
        self.assertIn("Writing to this number again", note)
        self.assertNotIn("email", note)

    def test_the_sign_out_yes_says_reminders_wait_for_the_phone_whoever_it_is(self) -> None:
        from packages.infrastructure.agent_loop import _describe_call

        member = LoopContext(
            api=lambda *a, **k: ({"ok": True}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", sender_wa_id=self.YOAV_PHONE,
            speaker=household.describe_speaker({"name": "Yoav", "role": "partner"}, owner_name="Dana Levi"),
        )
        owner = LoopContext(
            api=lambda *a, **k: ({"ok": True}, 200), database=self.database, email="parent@example.com",
            user_id=self.user_id, timezone_name="Asia/Jerusalem", channel="whatsapp", sender_wa_id="972500000001",
        )
        for context in (member, owner):
            said = _describe_call(context, TOOLS_BY_NAME["sign_out"], {})
            self.assertIn("reminders included", said)
            self.assertIn("go on once it is linked again", said)
            self.assertNotIn("which stop", said)

    def test_an_account_that_is_only_a_conversation_holds_nothing(self) -> None:
        self.database.register_user("wa-447700900123@whatsapp.assistyca.com")
        own = int(self.database.get_user("wa-447700900123@whatsapp.assistyca.com")["id"])
        self.database.link_user_whatsapp_number(user_id=own, wa_id="447700900123")
        self.database.save_whatsapp_agent_message(user_id=own, role="user", text="hi")
        self.database.save_account_fact(user_id=own, key="name", fact="Their name is Yoav.", pinned=True)
        self.assertTrue(self.database.account_holds_nothing(user_id=own, wa_id="447700900123"))
        self.assertFalse(self.database.account_holds_nothing(user_id=own, wa_id="447700900999"), "another phone reaches it")
        self.database.create_account_list(user_id=own, name="Groceries", kind="shopping", items=[])
        self.assertFalse(self.database.account_holds_nothing(user_id=own, wa_id="447700900123"))


class JoinPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server(
            "127.0.0.1", 0, Path(__file__).resolve().parents[1],
            PortalConfig(db_path=Path(self.temp_dir.name) / "portal.db", session_secret="join-page-test-secret-0123456789abcdef"),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.database = self.server.database
        self.database.register_user("parent@example.com", display_name="Dana Levi")
        self.user_id = int((self.database.get_user("parent@example.com") or {})["id"])
        self.yoav = self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def open(self, path: str) -> tuple[int, dict, str]:
        opener = urllib_request.build_opener(_NoRedirect)
        try:
            with opener.open(f"{self.base_url}{path}", timeout=10) as response:
                return int(response.status), dict(response.headers), response.read().decode()
        except urllib_error.HTTPError as exc:
            return int(exc.code), dict(exc.headers), exc.read().decode()

    def test_the_join_link_opens_whatsapp_with_the_code_and_dies_with_the_invitation(self) -> None:
        from datetime import datetime, timedelta, timezone
        from unittest import mock

        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(self.yoav["id"]), code="ABC234",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        with mock.patch.dict("os.environ", {"ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": "972559196101"}):
            status, headers, _ = self.open("/join/abc234")
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "https://wa.me/972559196101?text=Assistyca%20family%20ABC234")
            status, _, body = self.open("/join/ZZZ999")
            self.assertEqual(status, 404)
            self.assertIn("no longer valid", body)
            self.database.claim_household_invite(code="ABC234", wa_id="972500000002")
            status, _, body = self.open("/join/ABC234")
            self.assertEqual(status, 410)
            self.assertIn("no longer valid", body)
        # Without the Assistyca number to open, the page says what to send.
        self.database.create_household_invite(
            user_id=self.user_id, member_id=int(self.yoav["id"]), code="DEF567",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        with mock.patch.dict("os.environ", {"ASSISTYCA_WHATSAPP_DISPLAY_NUMBER": ""}):
            status, _, body = self.open("/join/DEF567")
        self.assertEqual(status, 410)
        self.assertIn("Assistyca family DEF567", body)


if __name__ == "__main__":
    unittest.main()


class DrivesDuringWorkTests(unittest.TestCase):
    members = [{"name": "Noa", "role": "child"}, {"name": "Yoav", "role": "partner"}]
    work = {"id": 1, "title": "Work", "who": ["me"], "days": ["mon", "tue"], "startTime": "09:00", "endTime": "17:00", "place": "the office"}
    school = {
        "id": 2, "title": "Gretz school", "who": ["Noa"], "days": ["mon", "tue", "wed"], "startTime": "08:00",
        "endTime": "13:30", "dropOffBy": "Yoav", "pickUpBy": "me", "fineDuringWork": [],
    }

    def test_a_pickup_inside_the_owners_work_hours_is_found_for_the_days_they_share(self) -> None:
        [found] = household.drives_during_work([self.work, self.school], self.members, ["Dana Levi"])
        self.assertEqual((found["leg"], found["at"], found["days"], found["accepted"]), ("pick_up", "13:30", ["mon", "tue"], False))
        self.assertEqual(household.describe_work_hours(found["work"]), "Work at the office 09:00-17:00")
        # Wednesday she does not work, so that day has nothing to say.
        self.assertEqual(household.drives_during_work([self.work, self.school], self.members, ["Dana"], day=date(2026, 9, 23)), [])
        self.assertEqual(len(household.drives_during_work([self.work, self.school], self.members, ["Dana"], day=date(2026, 9, 21))), 1)

    def test_the_ends_of_the_day_and_other_drivers_are_not_inside(self) -> None:
        # Dropping off at 08:00 before work, and a pickup exactly when work ends, are her drives home and in.
        at_the_edges = dict(self.school, dropOffBy="me", endTime="17:00")
        self.assertEqual(household.drives_during_work([self.work, at_the_edges], self.members, ["Dana"]), [])
        # The partner's pickup is theirs, not hers, and the partner's own hours say nothing about her.
        yoav_works = dict(self.work, id=3, who=["Yoav"])
        theirs = dict(self.school, pickUpBy="Yoav")
        self.assertEqual(household.drives_during_work([yoav_works, theirs], self.members, ["Dana"]), [])
        self.assertEqual(household.drives_during_work([yoav_works, self.school], self.members, ["Dana"]), [])
        # Her own name on the week counts as her.
        self.assertEqual(len(household.drives_during_work([dict(self.work, who=["Dana"]), self.school], self.members, ["Dana Levi"])), 1)

    def test_a_drive_she_has_said_is_fine_is_settled(self) -> None:
        settled = dict(self.school, fineDuringWork=["pick_up"])
        self.assertEqual(household.drives_during_work([self.work, settled], self.members, ["Dana"]), [])
        [kept] = household.drives_during_work([self.work, settled], self.members, ["Dana"], include_accepted=True)
        self.assertTrue(kept["accepted"])
        self.assertEqual(household.normalize_legs(["pickup", "Drop-off", "pick_up", "lunch"]), ["drop_off", "pick_up"])

    def test_the_block_marks_the_drive_and_what_was_accepted(self) -> None:
        described = household.describe_household(
            profile={}, members=self.members, activities=[self.work, self.school],
            today=date(2026, 9, 20), owner_names=["Dana"],
        )
        school = next(entry for entry in described["week"] if entry["id"] == 2)
        self.assertEqual(school["driveDuringWork"], {"pick_up": {"at": "13:30", "inside": "Work at the office 09:00-17:00", "days": ["mon", "tue"]}})
        self.assertNotIn("fineDuringWork", school)
        settled = household.describe_household(
            profile={}, members=self.members,
            activities=[self.work, dict(self.school, fineDuringWork=["pick_up"])], today=date(2026, 9, 20), owner_names=["Dana"],
        )
        school = next(entry for entry in settled["week"] if entry["id"] == 2)
        self.assertNotIn("driveDuringWork", school)
        self.assertEqual(school["fineDuringWork"], ["pick_up"])
        # A group's week has no owner, so it is never marked.
        group = household.describe_household(profile=None, members=self.members, activities=[self.work, self.school], today=date(2026, 9, 20), group_name="Class")
        self.assertNotIn("driveDuringWork", next(entry for entry in group["week"] if entry["id"] == 2))
