"""The morning plan, tomorrow's gaps, and the drive the owner is down for."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timezone
from pathlib import Path

from packages.infrastructure.family_week_nudges import FamilyWeekNudgeConfig
from packages.infrastructure.family_week_nudges import FamilyWeekNudger
from packages.infrastructure.family_week_nudges import describe_activity_line
from packages.infrastructure.family_week_nudges import gap_lines
from packages.infrastructure.family_week_nudges import rides_due
from packages.infrastructure.portal_db import PortalDatabase

UTC = timezone.utc
# 2026-09-20 is a Sunday.
SUNDAY = datetime(2026, 9, 20, tzinfo=UTC)


def at(day: datetime, hour: int, minute: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute)


class RulesTests(unittest.TestCase):
    football = {
        "id": 1, "title": "Football", "who": ["Tom"], "days": ["sun"], "startTime": "17:00", "endTime": "18:00",
        "dropOffBy": "me", "pickUpBy": "", "place": "Park",
    }

    def test_a_line_says_who_takes_and_who_collects(self) -> None:
        line = describe_activity_line(self.football, ["Dana Levi"])
        self.assertEqual(line, "17:00-18:00 Football (Tom), takes: you, nobody collects them yet")
        self.assertEqual(gap_lines([self.football]), ["Football (Tom) at 18:00: nobody is down for the pickup"])

    def test_a_drive_is_due_only_in_the_minutes_before_it(self) -> None:
        def due(hour: int, minute: int) -> list:
            return rides_due([self.football], owner_names=["Dana"], local_now=at(SUNDAY, hour, minute), lead_minutes=30)

        self.assertEqual(due(16, 25), [])
        self.assertEqual([ride["leg"] for ride in due(16, 35)], ["drop_off"])
        self.assertEqual(due(17, 0), [])
        # Someone else collecting is not the owner's drive.
        self.assertEqual(due(17, 40), [])
        monday = SUNDAY.replace(day=21)
        self.assertEqual(rides_due([self.football], owner_names=[], local_now=at(monday, 16, 40), lead_minutes=30), [])


class NudgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        self.database.update_user_account_type("dana@example.com", account_type="family")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["sun", "mon"],
            start_time="07:30", end_time="16:00", drop_off_by="Dana", pick_up_by="Shirly",
        )
        self.database.save_household_activity(
            user_id=self.user_id, title="Ballet", who=["Noa"], days=["mon"],
            start_time="16:30", end_time="17:30", drop_off_by="", pick_up_by="me",
        )
        self.nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def queued(self) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("source") == "family_week"
        ]

    def test_the_morning_plan_goes_once_and_only_in_the_morning(self) -> None:
        self.nudger.run_pending(now=at(SUNDAY, 6, 50))
        self.assertEqual(self.queued(), [])
        summary = self.nudger.run_pending(now=at(SUNDAY, 7, 5))
        self.assertEqual(summary["morning"], 1)
        self.nudger.run_pending(now=at(SUNDAY, 7, 10))
        [action] = [a for a in self.queued() if a["payload"]["title"] == "Today in your family's week"]
        payload = action["payload"]
        self.assertEqual(action["actionType"], "run_task")
        self.assertIn("07:30-16:00 Kindergarten (Tom), takes: you, collects: Shirly", payload["instruction"])
        self.assertTrue(payload["fallbackText"].startswith("Today:"))
        self.assertNotIn("offerInstruction", payload)

    def test_a_morning_missed_by_hours_is_not_sent_late(self) -> None:
        self.nudger.run_pending(now=at(SUNDAY, 13, 0))
        self.assertEqual(self.queued(), [])

    def test_the_evening_before_names_what_nobody_is_down_for(self) -> None:
        summary = self.nudger.run_pending(now=at(SUNDAY, 20, 15))
        self.assertEqual(summary["evening"], 1)
        [action] = self.queued()
        self.assertIn("Ballet (Noa) at 16:30: nobody is down for the drop-off", action["payload"]["instruction"])

    def test_the_owner_is_told_before_their_own_drive(self) -> None:
        monday = SUNDAY.replace(day=21)
        # Dana takes Tom at 07:30 (named, not "me"), and collects Noa at 17:30.
        self.assertEqual(self.nudger.run_pending(now=at(monday, 7, 5))["rides"], 1)
        self.assertEqual(self.nudger.run_pending(now=at(monday, 7, 10))["rides"], 0)
        self.assertEqual(self.nudger.run_pending(now=at(monday, 17, 5))["rides"], 1)
        rides = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertEqual(len(rides), 2)
        self.assertIn("collect Noa - Ballet at 17:30", rides[-1]["payload"]["instruction"])

    def test_nothing_goes_when_the_family_week_is_switched_off(self) -> None:
        self.database.set_account_type_feature(account_type="family", feature_id="family_week", allowed=False)
        self.nudger.run_pending(now=at(SUNDAY, 7, 5))
        self.assertEqual(self.queued(), [])

    def test_a_family_that_said_not_now_is_asked_once_on_the_day(self) -> None:
        self.database.save_household_profile(user_id=self.user_id, getting_to_know="postponed", ask_again_on="2026-09-20")
        self.nudger.run_pending(now=at(SUNDAY, 9, 0))
        self.assertNotIn("Getting to know your family", [a["payload"]["title"] for a in self.queued()], "not before ten")
        self.nudger.run_pending(now=at(SUNDAY, 11, 0))
        asks = [a for a in self.queued() if a["payload"]["title"] == "Getting to know your family"]
        self.assertEqual(len(asks), 1)
        self.assertIn("ask whether now is a good time to carry on", asks[0]["payload"]["offerInstruction"])
        self.assertEqual((self.database.get_household_profile(user_id=self.user_id) or {})["askAgainOn"], "")
        self.nudger.run_pending(now=at(SUNDAY, 12, 0))
        self.assertEqual(len([a for a in self.queued() if a["payload"]["title"] == "Getting to know your family"]), 1)

    def test_a_birthday_a_month_away_is_raised_once_with_the_list_offered(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Tom", role="child", birthday="2021-10-20")
        self.nudger.run_pending(now=at(SUNDAY, 9, 30))
        self.assertEqual(self.birthdays(), [], "not before ten")
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 11, 0))["birthdays"], 1)
        self.nudger.run_pending(now=at(SUNDAY.replace(day=21), 11, 0))
        [action] = self.birthdays()
        self.assertIn("Tom (child) has a birthday on 2026-10-20 (Tuesday), in 30 days, turning 5", action["payload"]["instruction"])
        self.assertIn("ready-made to-do list", action["payload"]["offerInstruction"])

    def test_a_birthday_too_far_or_too_close_is_left_alone(self) -> None:
        self.database.save_household_member(user_id=self.user_id, name="Noa", role="child", birthday="--11-01")
        self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner", birthday="--09-22")
        self.nudger.run_pending(now=at(SUNDAY, 11, 0))
        self.assertEqual(self.birthdays(), [])

    def birthdays(self) -> list[dict]:
        return [a for a in self.queued() if a["payload"]["title"] == "A birthday is coming"]


if __name__ == "__main__":
    unittest.main()
