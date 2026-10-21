"""The week ahead as one picture: a colour per person, a row per day."""

from __future__ import annotations

import re
import unittest
from datetime import date
from datetime import timedelta

from packages.infrastructure.week_summary_image import WeekDayPlan
from packages.infrastructure.week_summary_image import build_day_summary
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
        self.assertIn("מי מביא: נמרוד · מי אוסף: הסעה", summary.facts[1])
        self.assertNotIn("‪", summary.facts[1], "no bidi controls reach the model")

    def test_the_week_starts_on_the_sunday_after_a_saturday(self) -> None:
        self.assertEqual(next_week_start(date(2026, 10, 17)), SUNDAY)  # Saturday
        self.assertEqual(next_week_start(SUNDAY), SUNDAY + timedelta(days=7))
        self.assertEqual(next_week_start(date(2026, 10, 21)), SUNDAY + timedelta(days=7))


class WeekSummaryDrawingTests(unittest.TestCase):
    def test_each_hour_is_written_centred_on_its_own_line_including_the_last(self) -> None:
        from unittest import mock

        from packages.infrastructure import week_summary_image

        lines: list[float] = []
        labels: dict[str, float] = {}
        real_hline, real_text = week_summary_image._Page.hline, week_summary_image._Page.text

        def hline(page, x, y, width, *args, **kwargs):
            lines.append(y)
            real_hline(page, x, y, width, *args, **kwargs)

        def text(page, x, y, value, **kwargs):
            if re.fullmatch(r"\d\d:00", value):
                labels[value] = y
            real_text(page, x, y, value, **kwargs)

        days = week({1: [plan("Capoeira", ["Lahav"], "17:15", "18:15", "me", "Stav")]})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=MEMBERS, owner_names=OWNER)
        with mock.patch.object(week_summary_image._Page, "hline", hline), mock.patch.object(week_summary_image._Page, "text", text):
            render_week_pdf(summary, members=MEMBERS, owner_names=OWNER)
        self.assertIn("18:00", labels)
        self.assertIn("19:00", labels)  # the bottom line is named too
        half_a_digit = 7.5 * 0.7 / 2
        for label, baseline in labels.items():
            self.assertTrue(any(abs(baseline - (line + half_a_digit)) < 0.01 for line in lines), f"{label} is not centred on a line")

    def test_a_short_block_keeps_whose_it_is_on_its_title_line(self) -> None:
        """An hour with two open legs has no room for the name's own line;
        the name joins the title rather than leaving it to the colour."""

        from unittest import mock

        from packages.infrastructure import week_summary_image

        drawn: list[str] = []
        real_text = week_summary_image._Page.text

        def text(page, x, y, value, **kwargs):
            drawn.append(value)
            real_text(page, x, y, value, **kwargs)

        [day] = week({0: [
            plan("Acrobatics", ["Lahav"], "16:15", "17:15", "", ""),
            plan("Acrobatics", ["Laor"], "18:15", "19:30", "the bus", "me"),
        ]})[:1]
        summary = build_day_summary(day=day, members=MEMBERS, owner_names=OWNER, title="today")
        with mock.patch.object(week_summary_image._Page, "text", text):
            render_week_pdf(summary, members=MEMBERS, owner_names=OWNER)
        self.assertIn("Acrobatics · Lahav", drawn)
        self.assertIn("takes: nobody", drawn)
        self.assertIn("\u202a16:15–17:15\u202c", drawn, "the time still fits beside it")

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
        self.assertGreaterEqual(width, 2000)
        self.assertLessEqual(width, 3200)
        self.assertLess(height, width, "a landscape page, a column per day")
        self.assertLess(len(png), 2_000_000)

    def test_one_day_is_a_narrower_page_with_one_wide_column(self) -> None:
        [day] = week({0: [plan("School", ["Lahav"], "08:00", "12:45", "me", ""), plan("Gan", ["Laor"], "08:00", "16:15", "me", "Stav")]})[:1]
        summary = build_day_summary(day=day, members=MEMBERS, owner_names=OWNER, title="today")
        self.assertEqual(summary.title, "Today")
        self.assertEqual(len(summary.days), 1)
        self.assertEqual(summary.open_legs, 1)
        png = pdf_to_png(render_week_pdf(summary, members=MEMBERS, owner_names=OWNER))
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        self.assertEqual(width, 1280)
        self.assertGreater(height, width, "one day stands tall on a phone")
        hebrew = build_day_summary(
            day=day, members=[{"name": "סתיו", "role": "partner"}, {"name": "להב", "role": "child"}],
            owner_names=["נמרוד"], title="tomorrow", language="he",
        )
        self.assertEqual(hebrew.title, "מחר")

    def test_hebrew_draws_without_error(self) -> None:
        members = [{"name": "סתיו", "role": "partner"}, {"name": "להב", "role": "child"}]
        days = week({0: [plan("בית ספר", ["להב"], "08:00", "12:45", "אני", "")]})
        summary = build_week_summary(week_start=SUNDAY, days=days, members=members, owner_names=["נמרוד"])
        png = pdf_to_png(render_week_pdf(summary, members=members, owner_names=["נמרוד"]))
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
