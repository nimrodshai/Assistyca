"""Whether a day in the family's week is really on.

What these prove: a day is looked up once per place and shared by every
family there; an answer that calls a shut school ordinary is not believed;
only an out-of-the-ordinary day asks which activities it touches, and only
about the ones it was given; a clock that says nothing about where someone
lives looks nothing up; and when a step cannot run, the usual week stands
and the step is not retried on every poll.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from packages.infrastructure import household
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.school_days import RETRY_AFTER_SECONDS
from packages.infrastructure.school_days import SchoolCalendar
from packages.infrastructure.school_days import build_day_plan_prompt
from packages.infrastructure.school_days import describe_day
from packages.infrastructure.school_days import normalize_day_status
from packages.infrastructure.school_days import parse_off_activities

JERUSALEM = "Asia/Jerusalem"
# 2026-09-25 is a Friday, the eve of Sukkot.
EVE = date(2026, 9, 25)
SUKKOT_EVE = {
    "country": "Israel", "schools": "closed", "kindergartens": "closed", "occasion": "Erev Sukkot",
    "note": "Schools and kindergartens are on the Sukkot break until 2026-10-04.", "ordinary": False,
    "sourceUrl": "https://example.edu/calendar",
}
ORDINARY = {
    "country": "Israel", "schools": "open", "kindergartens": "open", "occasion": "", "note": "", "ordinary": True,
    "sourceUrl": "",
}
SCHOOL = {"id": 1, "title": "School at Shaked Elementary", "who": ["Lahav"], "startTime": "08:00", "endTime": "11:45"}
GAN = {"id": 2, "title": "gan", "who": ["Laor"], "startTime": "08:00", "endTime": "12:00"}
CHESS = {"id": 3, "title": "Chess club", "who": ["Lahav"], "startTime": "16:00", "endTime": "17:00"}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ReadingTheAnswerTests(unittest.TestCase):
    def test_a_shut_school_is_not_an_ordinary_day_whatever_it_is_called(self) -> None:
        status = normalize_day_status({**SUKKOT_EVE, "ordinary": True})
        self.assertFalse(status["ordinary"])
        self.assertTrue(normalize_day_status(ORDINARY)["ordinary"])
        self.assertIsNone(normalize_day_status({**ORDINARY, "schools": "maybe"}))
        self.assertEqual(normalize_day_status({**ORDINARY, "sourceUrl": "javascript:alert(1)"})["sourceUrl"], "")

    def test_only_the_activities_asked_about_can_be_off(self) -> None:
        text = json.dumps({"off": [{"id": 2, "why": "Kindergartens are closed"}, {"id": 99, "why": "made up"}]})
        self.assertEqual(parse_off_activities(text, [SCHOOL, GAN]), {2: "Kindergartens are closed"})
        self.assertEqual(parse_off_activities("not json", [SCHOOL, GAN]), {})

    def test_the_day_reads_as_one_line(self) -> None:
        self.assertEqual(
            describe_day(EVE, normalize_day_status(SUKKOT_EVE)),
            "2026-09-25 (Friday), Erev Sukkot: schools closed, kindergartens closed. "
            "Schools and kindergartens are on the Sukkot break until 2026-10-04.",
        )

    def test_the_question_carries_the_day_and_the_activities(self) -> None:
        prompt = build_day_plan_prompt(day=EVE, status=normalize_day_status(SUKKOT_EVE), activities=[GAN])
        self.assertIn('"title": "gan"', prompt)
        self.assertIn("Erev Sukkot", prompt)
        self.assertIn("when you cannot tell, leave it on", prompt)


class SchoolCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.lookups: list[tuple[str, date]] = []
        self.questions: list[str] = []
        self.day_answer: dict | Exception = SUKKOT_EVE
        self.plan_answer: str | Exception = json.dumps({"off": [{"id": 1, "why": "school break"}, {"id": 2, "why": "gan closed"}]})
        self.clock = Clock()
        self.calendar = SchoolCalendar(self.database, look_up=self._look_up, ask=self._ask, clock=self.clock)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _look_up(self, *, place: str, day: date) -> dict:
        self.lookups.append((place, day))
        if isinstance(self.day_answer, Exception):
            raise self.day_answer
        return self.day_answer

    def _ask(self, *, prompt: str, billing_email: str = "") -> str:
        self.questions.append(prompt)
        if isinstance(self.plan_answer, Exception):
            raise self.plan_answer
        return self.plan_answer

    def still_on(self, user_id: int = 1, activities: list[dict] | None = None) -> tuple[list[dict], dict | None]:
        return self.calendar.activities_still_on(
            user_id=user_id, scope="", place=JERUSALEM, day=EVE, activities=activities or [SCHOOL, GAN, CHESS],
        )

    def test_a_holiday_takes_what_it_closes_out_of_the_day(self) -> None:
        on, status = self.still_on()
        self.assertEqual([activity["title"] for activity in on], ["Chess club"])
        self.assertEqual(status["occasion"], "Erev Sukkot")

    def test_the_day_is_looked_up_once_and_shared_by_every_family_there(self) -> None:
        self.still_on(user_id=1)
        self.still_on(user_id=1)
        self.still_on(user_id=2)
        self.assertEqual(self.lookups, [(JERUSALEM, EVE)])
        self.assertEqual(len(self.questions), 2, "each family's own week is read once for the day")
        # Another instance - a restarted server - reads the day from the database.
        fresh = SchoolCalendar(self.database, look_up=self._look_up, ask=self._ask, clock=self.clock)
        self.assertEqual(fresh.day(JERUSALEM, EVE)["occasion"], "Erev Sukkot")
        self.assertEqual(len(self.lookups), 1)

    def test_a_changed_week_is_read_again(self) -> None:
        self.still_on(activities=[SCHOOL, GAN])
        self.still_on(activities=[SCHOOL, GAN, CHESS])
        self.assertEqual(len(self.questions), 2)

    def test_an_ordinary_day_asks_nothing_about_the_family(self) -> None:
        self.day_answer = ORDINARY
        on, status = self.still_on()
        self.assertEqual(len(on), 3)
        self.assertTrue(status["ordinary"])
        self.assertEqual(self.questions, [])

    def test_a_clock_that_says_nothing_about_a_place_looks_nothing_up(self) -> None:
        on, status = self.calendar.activities_still_on(user_id=1, scope="", place="UTC", day=EVE, activities=[SCHOOL])
        self.assertEqual((on, status), ([SCHOOL], None))
        self.assertEqual(self.lookups, [])

    def test_when_the_calendar_cannot_be_read_the_usual_week_stands_and_is_not_retried_every_poll(self) -> None:
        self.day_answer = RuntimeError("search is down")
        self.assertEqual(self.still_on(), ([SCHOOL, GAN, CHESS], None))
        self.still_on()
        self.assertEqual(len(self.lookups), 1)
        self.clock.now += RETRY_AFTER_SECONDS + 1
        self.day_answer = SUKKOT_EVE
        on, _ = self.still_on()
        self.assertEqual(len(self.lookups), 2)
        self.assertEqual([activity["title"] for activity in on], ["Chess club"])

    def test_when_the_family_cannot_be_read_the_usual_week_stands(self) -> None:
        self.plan_answer = RuntimeError("model is down")
        on, status = self.still_on()
        self.assertEqual(len(on), 3)
        self.assertEqual(status["occasion"], "Erev Sukkot")
        self.still_on()
        self.assertEqual(len(self.questions), 1, "not asked again on the next poll")


class HouseholdBlockTests(unittest.TestCase):
    def test_the_calendar_rides_on_the_household_only_when_there_is_one(self) -> None:
        plain = household.describe_household(profile=None, members=[], activities=[], today=EVE)
        self.assertNotIn("calendar", plain)
        entry = {"date": "2026-09-25", "weekday": "Friday", "occasion": "Erev Sukkot", "schools": "closed"}
        described = household.describe_household(profile=None, members=[], activities=[], today=EVE, calendar=[entry])
        self.assertEqual(described["calendar"], [entry])


if __name__ == "__main__":
    unittest.main()
