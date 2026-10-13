"""The week ahead as one picture: a colour per person, a row per day."""

from __future__ import annotations

import unittest
from datetime import date
from datetime import timedelta

from packages.infrastructure.week_summary_image import WeekDayPlan
from packages.infrastructure.week_summary_image import build_week_summary
from packages.infrastructure.week_summary_image import detect_language
from packages.infrastructure.week_summary_image import next_week_start
from packages.infrastructure.week_summary_image import pdf_to_png
from packages.infrastructure.week_summary_image import person_colours
from packages.infrastructure.week_summary_image import render_week_pdf

SUNDAY = date(2026, 10, 18)
MEMBERS = [{"name": "Stav", "role": "partner"}, {"name": "Lahav", "role": "child"}, {"name": "Laor", "role": "child"}]
OWNER = ["Nimrod Shai"]


def plan(title: str, who: list[str], start: str, end: str, takes: str, collects: str, place: str = "") -> dict:
    return {
        "id": 1, "title": title, "who": who, "startTime": start, "endTime": end,
        "dropOffBy": takes, "pickUpBy": collects, "place": place, "days": [],
    }


def week(plans_by_offset: dict[int, list[dict]], notes: dict[int, str] | None = None) -> list[WeekDayPlan]:
    return [
        WeekDayPlan(day=SUNDAY + timedelta(days=offset), plans=plans_by_offset.get(offset, []), note=(notes or {}).get(offset, ""))
        for offset in range(7)
    ]


class WeekSummaryFactsTests(unittest.TestCase):
    def test_each_person_has_one_colour_and_the_key_shows_only_who_appears(self) -> None:
        days = week({0: [plan("School", ["Lahav"], "08:00", "12:45", "me", "Stav"), plan("Work", ["me"], "09:00", "17:00", "", "")]})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=MEMBERS, owner_names=OWNER)
        self.assertEqual([name for name, _ in summary.legend], ["Nimrod", "Stav", "Lahav"], "Stav collects; Laor has nothing this week")
        colours = {name: colour for name, colour in summary.legend}
        self.assertNotEqual(colours["Nimrod"], colours["Lahav"])
        # The owner's two name forms share one colour and take one slot.
        palette = person_colours(MEMBERS, OWNER, [], language="en")
        self.assertEqual(palette["nimrod"], palette["nimrod shai"])
        self.assertEqual(palette["me"], palette["nimrod"])
        self.assertEqual(len({colour for _, colour in palette.values()}), 4, "owner, partner and two children")

    def test_the_facts_say_who_takes_and_collects_and_count_what_has_nobody(self) -> None:
        days = week({
            0: [plan("School", ["Lahav"], "08:00", "12:45", "me", "", "Shaked")],
            2: [plan("Ballet", ["Lahav"], "16:30", "17:30", "Stav", "Grandma", "Studio")],
        }, notes={3: "Sukkot"})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=MEMBERS, owner_names=OWNER)
        self.assertEqual(summary.open_legs, 1)
        self.assertEqual(summary.language, "en")
        self.assertIn("Sunday 2026-10-18: 08:00–12:45 School · Lahav (Shaked · takes: Nimrod · collects: nobody) - a leg still has nobody", summary.facts[0])
        self.assertEqual(summary.facts[1], "Monday 2026-10-19: nothing planned")
        self.assertIn("takes: Stav · collects: Grandma", summary.facts[2])
        self.assertEqual(summary.facts[3], "Wednesday 2026-10-21: nothing planned (Sukkot)")

    def test_a_hebrew_family_gets_hebrew_words(self) -> None:
        members = [{"name": "סתיו", "role": "partner"}, {"name": "להב", "role": "child"}]
        days = week({1: [plan("בית ספר", ["להב"], "08:00", "12:45", "אני", "הסעה")]})
        self.assertEqual(detect_language(members, days[1].plans), "he")
        summary = build_week_summary(week_start=SUNDAY, days=days, members=members, owner_names=["נמרוד"])
        self.assertEqual(summary.language, "he")
        self.assertIn("מביא/ה: נמרוד · אוסף/ת: הסעה", summary.facts[1])
        self.assertNotIn("‪", summary.facts[1], "no bidi controls reach the model")

    def test_the_week_starts_on_the_sunday_after_a_saturday(self) -> None:
        self.assertEqual(next_week_start(date(2026, 10, 17)), SUNDAY)  # Saturday
        self.assertEqual(next_week_start(SUNDAY), SUNDAY + timedelta(days=7))
        self.assertEqual(next_week_start(date(2026, 10, 21)), SUNDAY + timedelta(days=7))


class WeekSummaryDrawingTests(unittest.TestCase):
    def test_the_page_is_drawn_and_rasterised_at_screen_width(self) -> None:
        days = week({
            0: [plan("School", ["Lahav"], "08:00", "12:45", "me", "Stav", "Shaked"), plan("Gan", ["Laor"], "08:00", "16:15", "me", "")],
            1: [plan("Ballet", ["Lahav"], "16:30", "17:30", "Stav", "Grandma Rina", "A studio with a rather long name in Ra'anana")],
        }, notes={4: "Sukkot, schools closed"})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=MEMBERS, owner_names=OWNER)
        pdf = render_week_pdf(summary, members=MEMBERS, owner_names=OWNER)
        self.assertTrue(pdf.startswith(b"%PDF"))
        png = pdf_to_png(pdf)
        self.assertTrue(png.startswith(b"\x89PNG"))
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        self.assertEqual(width, 2000)
        self.assertLess(height, width, "a landscape page, a column per day")
        self.assertLess(len(png), 2_000_000)

    def test_hebrew_draws_without_error(self) -> None:
        members = [{"name": "סתיו", "role": "partner"}, {"name": "להב", "role": "child"}]
        days = week({0: [plan("בית ספר", ["להב"], "08:00", "12:45", "אני", "")]})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=members, owner_names=["נמרוד"])
        png = pdf_to_png(render_week_pdf(summary, members=members, owner_names=["נמרוד"]))
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
