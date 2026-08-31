"""When the diary is free, rather than what is on it.

The summary reads the meetings out in order, which answers "what is on next
week". "Am I free Thursday afternoon" is the question people actually ask a
calendar, and it is about the gaps between the meetings - arithmetic, and so
worked out here rather than in a sentence while it is being written.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.calendar_summary import CalendarDateRange
from packages.infrastructure.calendar_summary import describe_availability
from packages.infrastructure.calendar_summary import find_calendar_conflicts

ZONE = ZoneInfo("Asia/Jerusalem")


def at(hour: int, minute: int = 0, day: int = 3) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=ZONE)


def meeting(title: str, start: datetime, end: datetime, all_day: bool = False) -> dict:
    return {"title": title, "start": start, "end": end, "allDay": all_day}


def one_day(day: int = 3) -> CalendarDateRange:
    return CalendarDateRange(
        label="2026-08-03",
        start=datetime(2026, 8, day, 0, 0, tzinfo=ZONE),
        end=datetime(2026, 8, day + 1, 0, 0, tzinfo=ZONE),
    )


class FreeSlotTests(unittest.TestCase):
    def test_an_empty_day_is_free_all_through_working_hours(self) -> None:
        availability = describe_availability([], one_day(), timezone_name="Asia/Jerusalem")

        self.assertEqual(availability["workingHours"], "09:00-18:00")
        self.assertEqual(availability["freeByDay"][0]["free"], [{"from": "09:00", "to": "18:00"}])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 0)

    def test_a_meeting_splits_the_day_around_it(self) -> None:
        availability = describe_availability(
            [meeting("Standup", at(11), at(12))],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [
            {"from": "09:00", "to": "11:00"},
            {"from": "12:00", "to": "18:00"},
        ])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 60)

    def test_a_gap_too_short_to_use_is_not_offered(self) -> None:
        # Twenty minutes between two meetings is not a slot anybody can put a
        # meeting in, and offering it makes the whole answer untrustworthy.
        availability = describe_availability(
            [
                meeting("First", at(11), at(12)),
                meeting("Second", at(12, 20), at(13)),
            ],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [
            {"from": "09:00", "to": "11:00"},
            {"from": "13:00", "to": "18:00"},
        ])

    def test_overlapping_meetings_do_not_double_count_the_time(self) -> None:
        availability = describe_availability(
            [
                meeting("First", at(11), at(13)),
                meeting("Second", at(12), at(14)),
            ],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [
            {"from": "09:00", "to": "11:00"},
            {"from": "14:00", "to": "18:00"},
        ])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 180)

    def test_time_outside_working_hours_is_neither_free_nor_busy(self) -> None:
        availability = describe_availability(
            [meeting("Early", at(6), at(7))],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [{"from": "09:00", "to": "18:00"}])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 0)

    def test_a_meeting_running_into_the_day_takes_the_morning_with_it(self) -> None:
        availability = describe_availability(
            [meeting("Long one", at(8), at(10, 30))],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [{"from": "10:30", "to": "18:00"}])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 90)

    def test_a_day_with_no_usable_gap_is_offered_as_nothing(self) -> None:
        availability = describe_availability(
            [meeting("All of it", at(9), at(18))],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [])
        self.assertEqual(availability["freeByDay"][0]["bookedMinutes"], 540)

    def test_an_all_day_entry_does_not_make_the_day_busy(self) -> None:
        # A birthday and a public holiday are all-day entries. Reporting a
        # whole day gone over something nobody attends is worse than useless.
        availability = describe_availability(
            [meeting("Ploni's birthday", at(0), at(0, 0, 4), all_day=True)],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(availability["freeByDay"][0]["free"], [{"from": "09:00", "to": "18:00"}])
        self.assertEqual(availability["allDayEntries"], ["Ploni's birthday"])

    def test_every_day_in_the_range_is_answered_for(self) -> None:
        date_range = CalendarDateRange(
            label="week",
            start=datetime(2026, 8, 3, 0, 0, tzinfo=ZONE),
            end=datetime(2026, 8, 6, 0, 0, tzinfo=ZONE),
        )

        availability = describe_availability(
            [meeting("Standup", at(11), at(12))],
            date_range,
            timezone_name="Asia/Jerusalem",
        )

        self.assertEqual(
            [day["day"] for day in availability["freeByDay"]],
            ["2026-08-03", "2026-08-04", "2026-08-05"],
        )
        # Only the day with the meeting on it is broken up.
        self.assertEqual(len(availability["freeByDay"][0]["free"]), 2)
        self.assertEqual(len(availability["freeByDay"][1]["free"]), 1)


class TruncationTests(unittest.TestCase):
    """A fortnight of an answer must not pass for a month of one."""

    def test_a_range_longer_than_one_answer_says_what_it_left(self) -> None:
        date_range = CalendarDateRange(
            label="next month",
            start=datetime(2026, 8, 1, 0, 0, tzinfo=ZONE),
            end=datetime(2026, 9, 1, 0, 0, tzinfo=ZONE),
        )

        availability = describe_availability([], date_range, timezone_name="Asia/Jerusalem")

        self.assertEqual(len(availability["freeByDay"]), 14)
        self.assertEqual(availability["daysNotChecked"], 17)
        self.assertEqual(availability["checkedThrough"], "2026-08-14")

    def test_a_range_that_fits_says_nothing_about_leaving_anything(self) -> None:
        date_range = CalendarDateRange(
            label="this week",
            start=datetime(2026, 8, 3, 0, 0, tzinfo=ZONE),
            end=datetime(2026, 8, 10, 0, 0, tzinfo=ZONE),
        )

        availability = describe_availability([], date_range, timezone_name="Asia/Jerusalem")

        self.assertNotIn("daysNotChecked", availability)
        self.assertNotIn("checkedThrough", availability)


class ConflictTests(unittest.TestCase):
    def test_two_meetings_at_once_are_named_as_a_clash(self) -> None:
        conflicts = find_calendar_conflicts([
            meeting("Client call", at(11), at(12)),
            meeting("Dentist", at(11, 30), at(12, 30)),
        ])

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["first"], "Client call")
        self.assertEqual(conflicts[0]["second"], "Dentist")
        self.assertEqual(conflicts[0]["overlapFrom"], "11:30")
        self.assertEqual(conflicts[0]["overlapTo"], "12:00")

    def test_meetings_that_only_touch_do_not_clash(self) -> None:
        # One ending as the next begins is a normal day, not a problem.
        conflicts = find_calendar_conflicts([
            meeting("First", at(11), at(12)),
            meeting("Second", at(12), at(13)),
        ])

        self.assertEqual(conflicts, [])

    def test_an_all_day_entry_clashes_with_nothing(self) -> None:
        conflicts = find_calendar_conflicts([
            meeting("Ploni's birthday", at(0), at(0, 0, 4), all_day=True),
            meeting("Client call", at(11), at(12)),
        ])

        self.assertEqual(conflicts, [])

    def test_a_clean_diary_reports_no_conflicts_at_all(self) -> None:
        availability = describe_availability(
            [meeting("Standup", at(11), at(12))],
            one_day(),
            timezone_name="Asia/Jerusalem",
        )

        self.assertNotIn("overlappingMeetings", availability)


if __name__ == "__main__":
    unittest.main()
