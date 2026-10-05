"""The morning plan, tomorrow's gaps, and the drive the owner is down for."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from datetime import timezone
from pathlib import Path

from packages.infrastructure.family_week_nudges import FamilyWeekNudgeConfig
from packages.infrastructure.family_week_nudges import FamilyWeekNudger
from packages.infrastructure.family_week_nudges import describe_activity_line
from packages.infrastructure.family_week_nudges import gap_lines
from packages.infrastructure.family_week_nudges import owner_is_driving
from packages.infrastructure.family_week_nudges import ride_clashes
from packages.infrastructure.family_week_nudges import rides_due
from packages.infrastructure.family_week_nudges import rides_due_for_anyone
from packages.infrastructure.family_week_nudges import rides_leaving_together
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.school_days import SchoolCalendar

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

    def test_a_grown_ups_own_week_has_nobody_to_collect_them(self) -> None:
        # The owner's work hours sit in the same week so the pickups can be
        # told apart; the morning line says them plainly and never that
        # nobody is collecting them.
        members = [{"name": "Tom", "role": "child"}, {"name": "Yoav", "role": "partner"}]
        work = {"id": 2, "title": "Work", "who": ["me"], "days": ["sun"], "startTime": "09:00", "endTime": "17:00", "dropOffBy": "", "pickUpBy": ""}
        self.assertEqual(describe_activity_line(work, ["Dana Levi"], members), "09:00-17:00 Work (you)")
        self.assertEqual(gap_lines([work, self.football], members, ["Dana Levi"]), ["Football (Tom) at 18:00: nobody is down for the pickup"])
        # Without the family it cannot tell, and says what it always said.
        self.assertEqual(gap_lines([work]), ["Work (you) at 17:00: nobody is down for the drop-off and the pickup"])
        # Nobody drives a grown-up anywhere, so it is never a ride due.
        self.assertEqual(rides_due([work], owner_names=["Dana"], local_now=at(SUNDAY, 8, 40), lead_minutes=30), [])

    def test_a_drive_that_lands_in_a_meeting_is_a_clash(self) -> None:
        # Everyone is named for Sunday, and Dana's own calendar has her in a
        # meeting when she is down to take Tom. That is the evening's other
        # question: not who is missing, but who can take it instead.
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("UTC")
        day = SUNDAY.date()
        meeting = {"title": "Team meeting", "start": "2026-09-20T16:45:00+00:00", "end": "2026-09-20T17:30:00+00:00", "allDay": False}
        self.assertEqual(
            ride_clashes([self.football], owner_names=["Dana Levi"], day=day, zone=zone, events=[meeting], lead_minutes=30),
            ["Football (Tom), the drop-off at 17:00: you are down for it, but your calendar has Team meeting 16:45-17:30"],
        )
        # Leaving takes the half hour before: a meeting that ends inside it still clashes.
        early = {**meeting, "start": "2026-09-20T15:30:00+00:00", "end": "2026-09-20T16:40:00+00:00"}
        self.assertEqual(len(ride_clashes([self.football], owner_names=["Dana"], day=day, zone=zone, events=[early], lead_minutes=30)), 1)
        self.assertEqual(ride_clashes([self.football], owner_names=["Dana"], day=day, zone=zone, events=[early], lead_minutes=10), [])
        # A birthday or a holiday is all day and takes nobody out of the car;
        # a drive someone else does is not theirs to clash with; the pickup
        # nobody has taken is a gap, not a clash.
        birthday = {"title": "Grandma's birthday", "start": "2026-09-20T00:00:00+00:00", "end": "2026-09-21T00:00:00+00:00", "allDay": True}
        self.assertEqual(ride_clashes([self.football], owner_names=["Dana"], day=day, zone=zone, events=[birthday], lead_minutes=30), [])
        theirs = {**self.football, "dropOffBy": "Yoav"}
        self.assertEqual(ride_clashes([theirs], owner_names=["Dana"], day=day, zone=zone, events=[meeting], lead_minutes=30), [])
        self.assertFalse(owner_is_driving([theirs], ["Dana"]))
        self.assertTrue(owner_is_driving([self.football], ["Dana"]))
        # Another day's meeting is another day's problem.
        self.assertEqual(ride_clashes([self.football], owner_names=["Dana"], day=day.replace(day=21), zone=zone, events=[meeting], lead_minutes=30), [])

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

    def test_drives_at_the_same_time_or_just_after_leave_together(self) -> None:
        school = {"id": 4, "title": "School", "who": ["Lahav"], "days": ["sun"], "startTime": "08:00", "endTime": "13:30", "dropOffBy": "me", "pickUpBy": ""}
        gan = {"id": 5, "title": "Gan", "who": ["Laor"], "days": ["sun"], "startTime": "08:00", "endTime": "16:15", "dropOffBy": "me", "pickUpBy": ""}
        music = {"id": 6, "title": "Music", "who": ["Lahav"], "days": ["sun"], "startTime": "08:25", "endTime": "09:00", "dropOffBy": "me", "pickUpBy": "me"}
        late = {"id": 7, "title": "Dentist", "who": ["Laor"], "days": ["sun"], "startTime": "08:45", "endTime": "09:15", "dropOffBy": "me", "pickUpBy": ""}

        def together(hour: int, minute: int) -> list[str]:
            return [
                f"{ride['activity']['title']} {ride['at']}" for ride in rides_leaving_together(
                    [late, music, gan, school], owner_names=["Dana"], local_now=at(SUNDAY, hour, minute),
                    lead_minutes=30, merge_minutes=30,
                )
            ]

        self.assertEqual(together(7, 20), [])
        # In time order, with what follows inside the half hour after the first; not the one at 08:45.
        self.assertEqual(together(7, 35), ["School 08:00", "Gan 08:00", "Music 08:25"])
        # When only the later ones are left, they go with whatever is due then.
        self.assertEqual(together(8, 20), ["Music 08:25", "Dentist 08:45"])

    def test_a_drive_the_morning_message_already_names_is_not_said_again_beside_it(self) -> None:
        # Leaving at 07:00, 07:10 and 06:45 is within twenty minutes of the
        # 07:00 message either side: those drives are in it and get no word
        # of their own. Leaving at 07:20 or 06:40 is far enough off to be told.
        def drive(number: int, title: str, start: str) -> dict:
            return {"id": number, "title": title, "who": ["Noa"], "days": ["sun"], "startTime": start, "endTime": "13:00", "dropOffBy": "me", "pickUpBy": ""}

        drives = [drive(1, "Gan", "07:30"), drive(2, "School", "07:40"), drive(3, "Early", "07:15"), drive(4, "Later", "07:50"), drive(5, "Dawn", "07:10")]

        def together(hour: int, minute: int, digest: bool = True) -> list[str]:
            return [
                f"{ride['activity']['title']} {ride['at']}" for ride in rides_leaving_together(
                    drives, owner_names=["Dana"], local_now=at(SUNDAY, hour, minute), lead_minutes=30, merge_minutes=30,
                    digest_at=at(SUNDAY, 7, 0) if digest else None, digest_gap_minutes=20,
                )
            ]

        self.assertEqual(together(6, 41), ["Dawn 07:10"])
        # Still due at 06:46 - and nothing nearer the message rides along with it.
        self.assertEqual(together(6, 46), ["Dawn 07:10"])
        # At 07:02 the dawn run is still ahead; the ones leaving within
        # twenty minutes of the message never are. By 07:12 nothing is due.
        self.assertEqual(together(7, 2), ["Dawn 07:10"])
        self.assertEqual(together(7, 12), [])
        # Exactly twenty minutes after is far enough, and nothing nearer rides along with it.
        self.assertEqual(together(7, 21), ["Later 07:50"])
        # Without a morning message, every drive gets its word.
        self.assertEqual(together(7, 2, digest=False), ["Dawn 07:10", "Early 07:15", "Gan 07:30", "School 07:40"])

    def test_a_child_on_the_bus_is_in_the_plan_and_is_nobodys_drive(self) -> None:
        # The big one comes home on the bus: the morning says so, nobody is
        # asked to cover it, and through the day nothing is said about it -
        # not to the owner, and not into a group either.
        school = {
            "id": 3, "title": "School", "who": ["Lotan"], "days": ["sun"], "startTime": "08:00", "endTime": "14:30",
            "dropOffBy": "me", "pickUpBy": "the bus",
        }
        self.assertEqual(describe_activity_line(school, ["Dana"]), "08:00-14:30 School (Lotan), takes: you, collects: the bus")
        self.assertEqual(gap_lines([school]), [])
        self.assertEqual([r["leg"] for r in rides_due([school], owner_names=["Dana"], local_now=at(SUNDAY, 7, 40), lead_minutes=30)], ["drop_off"])
        self.assertEqual(rides_due([school], owner_names=["Dana"], local_now=at(SUNDAY, 14, 10), lead_minutes=30), [])
        self.assertEqual(rides_due([school], owner_names=["Bus"], local_now=at(SUNDAY, 14, 10), lead_minutes=30), [])
        self.assertEqual(rides_due_for_anyone([school], local_now=at(SUNDAY, 14, 10), lead_minutes=30), [])


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
        # The big one goes by bus both ways.
        self.database.save_household_activity(
            user_id=self.user_id, title="Junior high", who=["Lotan"], days=["sun", "mon"],
            start_time="08:00", end_time="14:30", drop_off_by="the bus", pick_up_by="the bus",
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
        self.assertIn("08:00-14:30 Junior high (Lotan), takes: the bus, collects: the bus", payload["instruction"])
        # The facts go once, as bullets: a second "nobody down for" block
        # came back as the same pickup said twice.
        self.assertIn("one bullet per thing", payload["instruction"])
        self.assertIn("Say each fact once", payload["instruction"])
        self.assertNotIn("NOBODY DOWN FOR", payload["instruction"])
        self.assertTrue(payload["fallbackText"].startswith("Today:\n• "))
        self.assertNotIn("offerInstruction", payload)

    def test_a_morning_missed_by_hours_is_not_sent_late(self) -> None:
        self.nudger.run_pending(now=at(SUNDAY, 13, 0))
        self.assertEqual(self.queued(), [])

    def test_the_evening_before_names_what_nobody_is_down_for(self) -> None:
        summary = self.nudger.run_pending(now=at(SUNDAY, 20, 15))
        self.assertEqual(summary["evening"], 1)
        [action] = self.queued()
        self.assertIn("Ballet (Noa) at 16:30: nobody is down for the drop-off", action["payload"]["instruction"])

    def test_the_evening_before_asks_her_to_decide_not_just_tells_her(self) -> None:
        # The evening before is the moment to settle tomorrow: a message that
        # only reports the gap was read and left, and the morning still said
        # "nobody collects yet". So it ends on the question, with a name as
        # the easy answer.
        self.nudger.run_pending(now=at(SUNDAY, 20, 15))
        [action] = self.queued()
        self.assertIn("asking them to decide now who does each drop-off or pickup still open", action["payload"]["instruction"])
        self.assertIn("easy to answer with a name", action["payload"]["instruction"])
        self.assertTrue(action["payload"]["fallbackText"].startswith("Tomorrow still needs someone - who will do it?\n• "))

    def test_the_evening_before_holds_the_owners_drives_up_against_her_calendar(self) -> None:
        # Monday: Dana collects Noa from ballet at 17:30, and her calendar has
        # a meeting then. Sunday evening says so, in the same message as the
        # drop-off nobody has taken, and the calendar is read once.
        calls: list[tuple] = []

        def reader(user_id: int, day, timezone_name: str) -> list[dict]:
            calls.append((user_id, day, timezone_name))
            return [{"title": "Team meeting", "start": "2026-09-21T17:00:00+00:00", "end": "2026-09-21T18:00:00+00:00", "allDay": False}]

        nudger = FamilyWeekNudger(
            self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30),
            calendar_reader=reader,
        )
        summary = nudger.run_pending(now=at(SUNDAY, 20, 15))
        self.assertEqual(summary["evening"], 1)
        self.assertEqual(calls, [(self.user_id, SUNDAY.date().replace(day=21), "UTC")])
        [action] = self.queued()
        instruction = action["payload"]["instruction"]
        self.assertIn("Ballet (Noa) at 16:30: nobody is down for the drop-off", instruction)
        self.assertIn("CLASHES WITH YOUR CALENDAR:\nBallet (Noa), the pickup at 17:30: you are down for it, but your calendar has Team meeting 17:00-18:00", instruction)
        self.assertIn("ask who could take that drive instead", instruction)
        self.assertIn("Tomorrow clashes with your calendar:\n• Ballet (Noa), the pickup at 17:30", action["payload"]["fallbackText"])
        # The next poll neither reads the calendar again nor says it twice.
        nudger.run_pending(now=at(SUNDAY, 20, 20))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.queued()), 1)

    def test_a_clash_alone_is_worth_an_evening_message(self) -> None:
        # Every ride on Monday is taken, so without the calendar the evening
        # would be quiet. The meeting is the only reason to write.
        activities = self.database.list_household_activities(user_id=self.user_id)
        ballet = next(activity for activity in activities if activity["title"] == "Ballet")
        self.database.save_household_activity(user_id=self.user_id, activity_id=int(ballet["id"]), drop_off_by="Yoav")
        reader = lambda user_id, day, timezone_name: [  # noqa: E731
            {"title": "Dentist", "start": "2026-09-21T17:15:00+00:00", "end": "2026-09-21T17:45:00+00:00", "allDay": False},
        ]
        quiet = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30))
        self.assertEqual(quiet.run_pending(now=at(SUNDAY, 20, 15))["evening"], 0)
        self.assertEqual(self.queued(), [])
        nudger = FamilyWeekNudger(
            self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30),
            calendar_reader=reader,
        )
        self.assertEqual(nudger.run_pending(now=at(SUNDAY, 20, 15))["evening"], 1)
        [action] = self.queued()
        self.assertNotIn("TOMORROW:", action["payload"]["instruction"])
        self.assertIn("Dentist 17:15-17:45", action["payload"]["instruction"])
        self.assertTrue(action["payload"]["fallbackText"].startswith("Tomorrow clashes with your calendar:"))

    def test_the_calendar_is_not_read_when_the_owner_is_not_driving_and_never_holds_the_evening_up(self) -> None:
        calls: list[tuple] = []

        def reader(user_id: int, day, timezone_name: str) -> list[dict]:
            calls.append((user_id, day))
            raise RuntimeError("calendar down")

        nudger = FamilyWeekNudger(
            self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30),
            calendar_reader=reader,
        )
        # Monday evening, about Tuesday: nothing on, nobody driving, no read.
        nudger.run_pending(now=at(SUNDAY.replace(day=21), 20, 15))
        self.assertEqual(calls, [])
        # Sunday evening, about Monday: the read fails, and the gap still goes.
        summary = nudger.run_pending(now=at(SUNDAY, 20, 15))
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["evening"], 1)
        [action] = self.queued()
        self.assertIn("nobody is down for the drop-off", action["payload"]["instruction"])
        self.assertNotIn("CLASHES", action["payload"]["instruction"])

    def test_the_owner_is_told_before_their_own_drive(self) -> None:
        monday = SUNDAY.replace(day=21)
        # Dana takes Tom at 07:30 (named, not "me") - that one the morning
        # message names, so no word goes beside it - and collects Noa at 17:30.
        self.assertEqual(self.nudger.run_pending(now=at(monday, 7, 5))["rides"], 0)
        self.assertEqual(self.nudger.run_pending(now=at(monday, 7, 10))["rides"], 0)
        self.assertEqual(self.nudger.run_pending(now=at(monday, 17, 5))["rides"], 1)
        [ride] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertIn("collect Noa - Ballet at 17:30", ride["payload"]["instruction"])

    def test_a_drive_right_after_the_morning_message_is_in_it_and_not_said_again(self) -> None:
        # Dana takes Tom to kindergarten at 07:30: leaving at 07:00, the very
        # minute the morning message goes. Two messages at once saying the
        # same thing look like a fault, so the morning message carries it
        # and no "time to leave" follows. A drive leaving twenty minutes
        # later still gets its own word.
        self.database.save_household_activity(
            user_id=self.user_id, title="Gymnastics", who=["Noa"], days=["sun"],
            start_time="07:50", end_time="08:30", drop_off_by="me", pick_up_by="Shirly",
        )
        first = self.nudger.run_pending(now=at(SUNDAY, 7, 0))
        self.assertEqual((first["morning"], first["rides"]), (1, 0))
        for hour, minute in ((7, 5), (7, 12), (7, 19)):
            self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, hour, minute))["rides"], 0, f"{hour}:{minute}")
        [morning] = [a for a in self.queued() if a["payload"]["title"] == "Today in your family's week"]
        self.assertIn("07:30-16:00 Kindergarten (Tom), takes: you", morning["payload"]["instruction"])
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 7, 21))["rides"], 1)
        [ride] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertIn("DRIVE: take Noa - Gymnastics at 07:50", ride["payload"]["instruction"])
        self.assertNotIn("Kindergarten", ride["payload"]["instruction"])

    def test_two_drives_close_together_are_one_word_planned_as_one_trip(self) -> None:
        # Sunday: Dana takes Tom at 07:50 this week and, from now, Noa to
        # school at 08:05 - one trip, said once at 07:20 and never again;
        # and a third run at 09:00 is far enough off to wait for its own word.
        kindergarten = next(a for a in self.database.list_household_activities(user_id=self.user_id) if a["title"] == "Kindergarten")
        self.database.save_household_activity(user_id=self.user_id, activity_id=int(kindergarten["id"]), start_time="07:50")
        self.database.save_household_activity(
            user_id=self.user_id, title="School", who=["Noa"], days=["sun"],
            start_time="08:05", end_time="13:30", drop_off_by="me", pick_up_by="Shirly", place="Shaked",
        )
        self.database.save_household_activity(
            user_id=self.user_id, title="Physio", who=["Tom"], days=["sun"],
            start_time="09:00", end_time="09:40", drop_off_by="me", pick_up_by="me",
        )
        self.nudger.run_pending(now=at(SUNDAY, 7, 10))
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 7, 22))["rides"], 1)
        for hour, minute in ((7, 40), (7, 55), (8, 4)):
            self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, hour, minute))["rides"], 0, f"{hour}:{minute}")
        [trip] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertIn("one trip", trip["payload"]["instruction"])
        self.assertIn("DRIVES:\ntake Tom - Kindergarten at 07:50\ntake Noa - School at 08:05, Shaked", trip["payload"]["instruction"])
        self.assertNotIn("Physio", trip["payload"]["instruction"])
        self.assertTrue(trip["payload"]["fallbackText"].startswith("Soon, one trip:\n• take Tom"))
        # The 09:00 run comes on its own, worded as the single drive it is.
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 8, 32))["rides"], 1)
        later = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertEqual(len(later), 2)
        single = next(a for a in later if "Physio" in a["payload"]["instruction"])
        self.assertIn("DRIVE: take Tom - Physio at 09:00", single["payload"]["instruction"])
        self.assertNotIn("DRIVES", single["payload"]["instruction"])

    def test_nothing_is_said_through_the_day_about_a_drive_that_is_not_theirs(self) -> None:
        # Sunday: the morning plan lists everything, as it should, Dana's
        # 07:30 run with Tom among it. Then the bus takes Lotan at 08:00 and
        # brings them home at 14:30, and Shirly collects Tom at 16:00 - none
        # of it the owner's drive, so the rest of the day is quiet.
        first = self.nudger.run_pending(now=at(SUNDAY, 7, 5))
        self.assertEqual((first["morning"], first["rides"]), (1, 0))
        for hour, minute in ((7, 35), (7, 50), (14, 5), (14, 20), (15, 35), (15, 50)):
            self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, hour, minute))["rides"], 0, f"{hour}:{minute}")
        titles = sorted(a["payload"]["title"] for a in self.queued())
        self.assertEqual(titles, ["Today in your family's week"])

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


    def test_the_family_on_their_own_phones_each_hear_about_what_is_theirs(self) -> None:
        # Shirly, the partner, joined from her phone; Rina, a grandmother,
        # from hers. Shirly collects Tom at 16:00; Rina takes Noa to ballet
        # on Monday. The morning plan goes to both parents, worded for each;
        # Rina hears only about her own drive, when it is time to leave.
        from datetime import datetime, timedelta, timezone as tz

        shirly = self.database.save_household_member(user_id=self.user_id, name="Shirly", role="partner")
        rina = self.database.save_household_member(user_id=self.user_id, name="Rina", role="other")
        for member, code, phone in ((shirly, "SHR222", "972500000002"), (rina, "RNA333", "972500000003")):
            self.database.create_household_invite(
                user_id=self.user_id, member_id=int(member["id"]), code=code,
                expires_at=datetime.now(tz.utc) + timedelta(days=14),
            )
            self.assertTrue(self.database.claim_household_invite(code=code, wa_id=phone)["ok"])
        activities = self.database.list_household_activities(user_id=self.user_id)
        ballet = next(activity for activity in activities if activity["title"] == "Ballet")
        self.database.save_household_activity(user_id=self.user_id, activity_id=int(ballet["id"]), drop_off_by="Rina")
        # Monday's swimming has nobody down for it yet: the evening's question.
        self.database.save_household_activity(
            user_id=self.user_id, title="Swimming", who=["Tom"], days=["mon"],
            start_time="17:00", end_time="18:00", drop_off_by="", pick_up_by="",
        )

        summary = self.nudger.run_pending(now=at(SUNDAY, 7, 5))
        self.assertEqual(summary["morning"], 2)
        mornings = {a["recipientRef"]: a["payload"] for a in self.queued() if a["payload"]["title"] == "Today in your family's week"}
        self.assertEqual(set(mornings), {"owner", "972500000002"})
        self.assertIn("07:30-16:00 Kindergarten (Tom), takes: you, collects: Shirly", mornings["owner"]["instruction"])
        self.assertIn("07:30-16:00 Kindergarten (Tom), takes: Dana, collects: you", mornings["972500000002"]["instruction"])
        self.assertIn("'you' is Shirly", mornings["972500000002"]["instruction"])
        self.assertEqual(mornings["972500000002"]["recipientWaId"], "972500000002")
        # The next poll says nothing twice to either of them.
        self.nudger.run_pending(now=at(SUNDAY, 7, 10))
        self.assertEqual(len([a for a in self.queued() if a["payload"]["title"] == "Today in your family's week"]), 2)

        # Shirly's pickup at 16:00: her phone, nobody else's.
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 15, 35))["rides"], 1)
        [ride] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon" and a["recipientRef"] != "owner"]
        self.assertEqual(ride["recipientRef"], "972500000002")
        self.assertIn("DRIVE: collect Tom - Kindergarten at 16:00", ride["payload"]["instruction"])
        self.assertIn("for Shirly", ride["payload"]["instruction"])

        # Rina, who gets no morning plan, is still told before a run of hers
        # that leaves as the plan goes out; Shirly, who got the plan, is not.
        self.database.save_household_activity(
            user_id=self.user_id, title="Chess", who=["Noa"], days=["sun"],
            start_time="07:30", end_time="08:30", drop_off_by="Rina", pick_up_by="Shirly",
        )
        self.database.save_household_activity(
            user_id=self.user_id, title="Choir", who=["Tom"], days=["sun"],
            start_time="07:35", end_time="08:30", drop_off_by="Shirly", pick_up_by="Rina",
        )
        early = self.nudger.run_pending(now=at(SUNDAY, 7, 1))
        self.assertEqual(early["rides"], 1)
        [chess] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon" and "Chess" in a["payload"]["instruction"]]
        self.assertEqual(chess["recipientRef"], "972500000003")
        self.assertFalse(any("Choir" in a["payload"]["instruction"] for a in self.queued() if a["payload"]["title"] == "Time to leave soon"))

        # Monday: Rina takes Noa at 16:30, and Dana collects her at 17:30.
        monday = SUNDAY.replace(day=21)
        self.nudger.run_pending(now=at(monday, 16, 5))
        rides = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertEqual([r["recipientRef"] for r in rides], ["972500000003", "972500000002", "972500000003"])
        self.assertIn("take Noa - Ballet at 16:30", rides[-1]["payload"]["instruction"])
        self.nudger.run_pending(now=at(monday, 17, 5))
        rides = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertEqual(rides[-1]["recipientRef"], "owner")
        self.assertIn("collect Noa - Ballet at 17:30", rides[-1]["payload"]["instruction"])
        # The grandmother never gets the morning plan or the evening before.
        self.nudger.run_pending(now=at(SUNDAY, 20, 15))
        evenings = [a for a in self.queued() if a["payload"]["title"] == "Tomorrow still needs someone"]
        self.assertEqual(sorted(a["recipientRef"] for a in evenings), ["972500000002", "owner"])
        for evening in evenings:
            self.assertIn("Swimming (Tom) at 18:00: nobody is down for the drop-off and the pickup", evening["payload"]["instruction"])
        self.assertFalse(any(a["recipientRef"] == "972500000003" for a in self.queued() if a["payload"]["title"] != "Time to leave soon"))


if __name__ == "__main__":
    unittest.main()


class DriveDuringWorkNudgeTests(unittest.TestCase):
    """Dana works 09:00-17:00 on Mondays and is down to collect Noa from
    school at 13:30: the week itself says those cannot both be true."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        self.database.update_user_account_type("dana@example.com", account_type="family")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        self.database.save_household_member(user_id=self.user_id, name="Noa", role="child")
        self.database.save_household_member(user_id=self.user_id, name="Yoav", role="partner")
        self.database.save_household_activity(
            user_id=self.user_id, title="Work", who=["me"], days=["mon"], start_time="09:00", end_time="17:00", place="the office",
        )
        self.school = self.database.save_household_activity(
            user_id=self.user_id, title="Gretz school", who=["Noa"], days=["mon"],
            start_time="08:00", end_time="13:30", drop_off_by="Yoav", pick_up_by="me",
        )
        self.nudger = FamilyWeekNudger(self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def queued(self) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("source") == "family_week"
        ]

    def test_the_evening_before_says_the_pickup_is_inside_her_work_hours(self) -> None:
        # Everyone is named, so without this the evening would be quiet.
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 20, 15))["evening"], 1)
        [action] = self.queued()
        instruction = action["payload"]["instruction"]
        self.assertNotIn("TOMORROW:", instruction)
        self.assertIn(
            "INSIDE YOUR OWN WORK HOURS:\nGretz school (Noa), the pickup at 13:30: you are down for it, but it falls "
            "inside your own Work at the office 09:00-17:00",
            instruction,
        )
        self.assertIn("whether it is fine as it is", instruction)
        self.assertEqual(
            action["payload"]["fallbackText"],
            "Tomorrow, inside your own work hours:\n• Gretz school (Noa), the pickup at 13:30: you are down for it, but it "
            "falls inside your own Work at the office 09:00-17:00",
        )
        self.nudger.run_pending(now=at(SUNDAY, 20, 25))
        self.assertEqual(len(self.queued()), 1)

    def test_the_morning_says_it_in_the_bullet_while_it_is_not_settled(self) -> None:
        monday = SUNDAY.replace(day=21)
        self.assertEqual(self.nudger.run_pending(now=at(monday, 7, 5))["morning"], 1)
        [action] = self.queued()
        instruction = action["payload"]["instruction"]
        self.assertIn(
            "08:00-13:30 Gretz school (Noa), takes: Yoav, collects: you (inside your own Work at the office 09:00-17:00, not settled yet)",
            instruction,
        )
        self.assertIn("09:00-17:00 Work (you)", instruction)
        self.assertIn("who could take it or whether it is fine as it is", instruction)

    def test_once_she_says_it_is_fine_nobody_mentions_it_again(self) -> None:
        kept = self.database.mark_household_drive_fine_during_work(user_id=self.user_id, activity_id=int(self.school["id"]), leg="pick_up")
        self.assertEqual(kept["fineDuringWork"], ["pick_up"])
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 20, 15))["evening"], 0)
        monday = SUNDAY.replace(day=21)
        self.nudger.run_pending(now=at(monday, 7, 5))
        [action] = self.queued()
        self.assertIn("collects: you\n", action["payload"]["instruction"] + "\n")
        self.assertNotIn("not settled", action["payload"]["instruction"])
        self.assertNotIn("fine as it is", action["payload"]["instruction"])
        # Saying so twice keeps one leg, and the other leg is still open to ask about.
        again = self.database.mark_household_drive_fine_during_work(user_id=self.user_id, activity_id=int(self.school["id"]), leg="pickup")
        self.assertEqual(again["fineDuringWork"], ["pick_up"])
        with self.assertRaises(LookupError):
            self.database.mark_household_drive_fine_during_work(user_id=self.user_id, activity_id=999, leg="pick_up")

    def test_somebody_else_on_the_pickup_settles_it_too(self) -> None:
        self.database.save_household_activity(user_id=self.user_id, activity_id=int(self.school["id"]), pick_up_by="Yoav")
        self.assertEqual(self.nudger.run_pending(now=at(SUNDAY, 20, 15))["evening"], 0)
        self.assertEqual(self.queued(), [])


class GroupNudgeTests(unittest.TestCase):
    """A group's rota: ask the room the night before, remind the one who took it."""

    GROUP = "120363@g.us"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("dana@example.com", display_name="Dana Levi")
        self.database.update_user_account_type("dana@example.com", account_type="family")
        self.user_id = int((self.database.get_user("dana@example.com") or {})["id"])
        # The account's own week, which a group nudge must never speak about.
        self.database.save_household_activity(
            user_id=self.user_id, title="Kindergarten", who=["Tom"], days=["mon"],
            start_time="07:30", end_time="16:00", drop_off_by="", pick_up_by="",
        )
        # The group's week, from what the room said.
        self.database.save_household_activity(
            user_id=self.user_id, group_id=self.GROUP, title="Football", who=["Noam"], days=["mon"],
            start_time="16:00", end_time="17:30", drop_off_by="Yonatan", pick_up_by="",
        )
        self.nudger = FamilyWeekNudger(
            self.database, config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30),
        )
        self.groups_on = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.whatsapp_groups_enabled", return_value=True,
        )
        self.groups_on.start()

    def tearDown(self) -> None:
        self.groups_on.stop()
        self.temp_dir.cleanup()

    def queued(self) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("source") == "family_week"
        ]

    def test_the_room_is_asked_the_evening_before_about_a_run_nobody_took(self) -> None:
        summary = self.nudger.run_pending_for_groups(now=at(SUNDAY, 20, 15))
        self.assertEqual((summary["groups"], summary["groupEvening"]), (1, 1))
        [action] = self.queued()
        self.assertEqual(action["recipientRef"], f"group:{self.GROUP}")
        self.assertEqual(action["payload"]["group"]["id"], self.GROUP)
        self.assertIn("Football (Noam) at 17:30: nobody is down for the pickup", action["payload"]["instruction"])
        self.assertIn("asking who can take it", action["payload"]["instruction"])
        self.assertNotIn("Kindergarten", action["payload"]["instruction"], "the account's own week is not the group's")
        # Once, not every poll.
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(SUNDAY, 20, 45))["groupEvening"], 0)

    def test_whoever_took_the_run_is_reminded_in_the_room_by_name(self) -> None:
        monday = SUNDAY.replace(day=21)
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(monday, 15, 10))["groupRides"], 0)
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(monday, 15, 40))["groupRides"], 1)
        [action] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertIn("Yonatan takes Noam - Football at 16:00", action["payload"]["instruction"])
        self.assertEqual(action["recipientRef"], f"group:{self.GROUP}")

    def test_a_group_is_left_alone_while_groups_are_switched_off(self) -> None:
        self.groups_on.stop()
        with mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.whatsapp_groups_enabled", return_value=False,
        ):
            self.assertEqual(self.nudger.run_pending_for_groups(now=at(SUNDAY, 20, 15)), {
                "ok": True, "groups": 0, "groupEvening": 0, "groupRides": 0,
            })
        self.assertEqual(self.queued(), [])
        self.groups_on.start()

    def test_a_child_who_comes_by_bus_is_not_announced_to_the_room(self) -> None:
        self.database.save_household_activity(
            user_id=self.user_id, group_id=self.GROUP, title="Swimming", who=["Noam"], days=["mon"],
            start_time="18:00", end_time="19:00", drop_off_by="the bus", pick_up_by="Yonatan",
        )
        monday = SUNDAY.replace(day=21)
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(monday, 17, 40))["groupRides"], 0)
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(monday, 18, 40))["groupRides"], 1)
        [action] = [a for a in self.queued() if a["payload"]["title"] == "Time to leave soon"]
        self.assertIn("Yonatan collects Noam - Swimming at 19:00", action["payload"]["instruction"])

    def test_a_run_nobody_took_reminds_nobody(self) -> None:
        football = self.database.list_household_activities(user_id=self.user_id, group_id=self.GROUP)[0]
        monday = SUNDAY.replace(day=21)
        self.assertEqual(
            [ride["driver"] for ride in rides_due_for_anyone(
                [football], local_now=at(monday, 17, 10), lead_minutes=30,
            )],
            [],
            "the pickup at 17:30 has nobody down for it, so there is nobody to remind",
        )


class HolidayNudgeTests(unittest.TestCase):
    """The usual week, held up against the school calendar where they live."""

    GROUP = "120363@g.us"

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
        self.database.save_household_activity(
            user_id=self.user_id, group_id=self.GROUP, title="Football", who=["Noam"], days=["mon"],
            start_time="16:00", end_time="17:30", drop_off_by="Yonatan", pick_up_by="",
        )
        # What the calendar says, by day, and which titles each closes.
        self.days: dict[str, dict] = {}
        self.closes: dict[str, set[str]] = {}
        self.lookups: list[str] = []
        calendar = SchoolCalendar(self.database, look_up=self._look_up, ask=self._ask)
        self.nudger = FamilyWeekNudger(
            self.database,
            config=FamilyWeekNudgeConfig(morning_hour=7, evening_hour=20, ride_lead_minutes=30),
            school_calendar=calendar,
        )
        # The family lives in Israel: 07:05 there is 04:05 UTC in September.
        self.zone = mock.patch.object(FamilyWeekNudger, "_timezone_for_user", return_value="Asia/Jerusalem")
        self.zone.start()
        self.groups_on = mock.patch(
            "packages.infrastructure.whatsapp_agent_chat.whatsapp_groups_enabled", return_value=True,
        )
        self.groups_on.start()

    def tearDown(self) -> None:
        self.groups_on.stop()
        self.zone.stop()
        self.temp_dir.cleanup()

    def _look_up(self, *, place: str, day) -> dict:
        self.lookups.append(day.isoformat())
        return self.days.get(day.isoformat(), {
            "country": "Israel", "schools": "open", "kindergartens": "open", "occasion": "", "note": "",
            "ordinary": True, "sourceUrl": "",
        })

    def _ask(self, *, prompt: str, billing_email: str = "") -> str:
        question = json.loads(prompt[prompt.index('{"date"'):])
        closed = self.closes.get(question["date"], set())
        return json.dumps({"off": [
            {"id": activity["id"], "why": "closed"} for activity in question["activities"] if activity["title"] in closed
        ]})

    def holiday(self, day: str, occasion: str, *titles: str) -> None:
        self.days[day] = {
            "country": "Israel", "schools": "closed", "kindergartens": "closed", "occasion": occasion,
            "note": f"{occasion}: schools and kindergartens are closed.", "ordinary": False, "sourceUrl": "",
        }
        self.closes[day] = set(titles)

    def queued(self, title: str) -> list[dict]:
        return [
            action for action in self.database.list_scheduled_actions_for_user(self.user_id, limit=50)
            if (action.get("payload") or {}).get("source") == "family_week" and action["payload"]["title"] == title
        ]

    def test_a_day_the_holiday_empties_sends_no_morning_and_no_drive(self) -> None:
        self.holiday("2026-09-20", "Erev Sukkot", "Kindergarten")
        # 07:05 local: the morning window, and ahead of Dana's 07:30 drop-off.
        summary = self.nudger.run_pending(now=at(SUNDAY, 4, 5))
        self.assertEqual((summary["morning"], summary["rides"]), (0, 0))
        self.nudger.run_pending(now=at(SUNDAY, 4, 20))
        self.assertEqual(self.queued("Today in your family's week"), [])
        self.assertEqual(self.queued("Time to leave soon"), [])
        self.assertEqual(self.lookups, ["2026-09-20"], "the day is looked up once, not every poll")

    def test_the_morning_leaves_out_what_is_closed_and_says_why(self) -> None:
        monday = SUNDAY.replace(day=21)
        self.days["2026-09-21"] = {
            "country": "Israel", "schools": "closed", "kindergartens": "closed", "occasion": "Sukkot break",
            "note": "Kindergartens are closed until 2026-10-04.", "ordinary": False, "sourceUrl": "",
        }
        self.closes["2026-09-21"] = {"Kindergarten"}
        summary = self.nudger.run_pending(now=at(monday, 4, 5))
        self.assertEqual((summary["morning"], summary["rides"]), (1, 0))
        [action] = self.queued("Today in your family's week")
        instruction = action["payload"]["instruction"]
        listed = instruction[instruction.index("TODAY:"):instruction.index("CALENDAR:")]
        self.assertIn("Ballet (Noa)", listed)
        self.assertNotIn("Kindergarten (Tom)", listed)
        self.assertIn("CALENDAR: 2026-09-21 (Monday), Sukkot break", instruction)
        self.assertNotIn("Kindergarten", action["payload"]["fallbackText"])

    def test_an_ordinary_day_goes_as_it_always_did(self) -> None:
        # 07:05 in Israel: the morning plan goes, with the 07:30 kindergarten
        # run in it, and no second word about that run beside it.
        summary = self.nudger.run_pending(now=at(SUNDAY, 4, 5))
        self.assertEqual((summary["morning"], summary["rides"]), (1, 0))
        [action] = self.queued("Today in your family's week")
        self.assertIn("Kindergarten", action["payload"]["instruction"])
        self.assertNotIn("CALENDAR", action["payload"]["instruction"])

    def test_the_evening_before_a_holiday_asks_nobody_to_cover_it(self) -> None:
        self.holiday("2026-09-21", "Sukkot", "Kindergarten", "Ballet")
        # 20:15 local on Sunday; Monday's Ballet drop-off has nobody, but Monday is off.
        summary = self.nudger.run_pending(now=at(SUNDAY, 17, 15))
        self.assertEqual(summary["evening"], 0)
        self.assertEqual(self.queued("Tomorrow still needs someone"), [])

    def test_a_group_run_on_a_holiday_reminds_nobody(self) -> None:
        self.holiday("2026-09-21", "Sukkot", "Football", "Kindergarten", "Ballet")
        monday = SUNDAY.replace(day=21)
        # 15:40 local, twenty minutes before Yonatan's 16:00 run.
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(monday, 12, 40))["groupRides"], 0)
        self.assertEqual(self.nudger.run_pending_for_groups(now=at(SUNDAY, 17, 15))["groupEvening"], 0)
