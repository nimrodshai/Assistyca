"""The week ahead as one picture.

On Saturday evening a family gets next week at a glance: a page with one
row per day, Sunday to Saturday, and on each day the plans as coloured
cards - one colour per person, with the key above the table, so a parent
can find their child's week by colour before reading a word. Each card
says the time, what it is, who it is for, and who takes and who collects;
a leg nobody is down for yet says so, because that is the thing to settle
before Sunday.

The page is drawn as a PDF with reportlab and rasterised to a PNG with
PyMuPDF, so the same drawing could be printed one day. The labels follow
the family's own script: a family whose names and activities are written
in Hebrew gets Hebrew weekdays and a right-to-left page; everyone else
gets English. Names are drawn through the bidi algorithm either way, so a
Hebrew child in an English household still reads the right way round.

Nothing here reaches the network or the database. The caller hands in
the days already held up against exceptions, the school calendar and the
day's own drives, and gets back the picture and the plain facts a caption
can be written from.
"""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import Iterable

from packages.infrastructure import household
from packages.infrastructure.portal_db import normalize_text

# -- the look -----------------------------------------------------------------

PAGE_WIDTH = 540.0
MARGIN = 26.0
DAY_COLUMN = 104.0
ROW_GAP = 6.0
CHIP_PAD = 7.0
CHIP_GAP = 5.0
CHIP_RADIUS = 6.0
CHIP_BAR = 4.0
MIN_ROW_HEIGHT = 42.0
# Rendered at this many device pixels per point: 540pt becomes 1080px,
# which WhatsApp shows sharp on any phone and keeps well under its limit.
RASTER_SCALE = 2.0

INK = "#1F2A37"
INK_SOFT = "#6B7280"
LINE = "#E5E7EB"
PAPER = "#FFFFFF"
ROW_ALT = "#F8FAFB"
OPEN_LEG = "#B42318"
NOTE = "#9A6700"

# One colour per person, in the order people are met: the account holder,
# the partner, then the children as the family listed them. Calm and
# distinct from one another on a phone screen in daylight.
PALETTE = ("#2A9D8F", "#E76F51", "#5A67D8", "#D69E2E", "#D53F8C", "#38A169", "#3182CE", "#805AD5", "#DD6B20", "#319795")
TINT_MIX = 0.86  # how far each colour is pulled towards white for a card's fill

FONT_DIR = Path(__file__).resolve().parents[2] / "assets"
FONT_FILES = {
    "WeekSans": "rubik-regular.ttf",
    "WeekSans-Medium": "rubik-medium.ttf",
    "WeekSans-SemiBold": "rubik-semibold.ttf",
}
_FONT_LOCK = threading.Lock()
_FONTS_READY = False

_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
# Explicit left-to-right embedding, so a time span keeps its order inside a
# Hebrew line; stripped before drawing, since no font has a glyph for them.
LTR_START = "\u202a"
LTR_END = "\u202c"
_BIDI_CONTROLS_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f]")
_LATIN_RE = re.compile(r"[A-Za-z]")

WORDS = {
    "en": {
        "title": "The week ahead",
        "weekdays": ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"),
        "months": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        "nothing": "Nothing planned",
        "takes": "takes",
        "collects": "collects",
        "nobody": "nobody yet",
        "parent": "Parent",
        "off": "Day off",
    },
    "he": {
        "title": "השבוע הקרוב",
        "weekdays": ("ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"),
        "months": (),
        "nothing": "אין תוכניות",
        "takes": "מביא/ה",
        "collects": "אוסף/ת",
        "nobody": "עדיין אין",
        "parent": "הורה",
        "off": "יום חופשי",
    },
}


@dataclass
class WeekDayPlan:
    """One day of the week as the picture shows it: the date, the plans
    really on that day (exceptions, the school calendar and the day's own
    drives already applied), and a note when the day is not an ordinary
    one - a holiday, a trip."""

    day: date
    plans: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


@dataclass
class WeekSummary:
    """What the picture is drawn from, and the plain facts beside it."""

    week_start: date
    days: list[WeekDayPlan]
    legend: list[tuple[str, str]]  # (name as shown, colour)
    language: str
    facts: list[str]  # one plain line per day, for the caption's writer
    open_legs: int  # drop-offs and pickups with nobody down for them


# -- words and colours --------------------------------------------------------


def detect_language(members: Iterable[dict[str, Any]], activities: Iterable[dict[str, Any]]) -> str:
    """Hebrew when the family writes its names and plans in Hebrew letters
    more than in Latin ones; English otherwise. The family's own words
    decide, not the country, because a family in Israel may well keep its
    week in English."""

    text = " ".join(
        [normalize_text(member.get("name")) for member in members]
        + [f"{normalize_text(activity.get('title'))} {' '.join(activity.get('who') or [])}" for activity in activities]
    )
    hebrew = len(_HEBREW_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return "he" if hebrew > latin else "en"


def _owner_label(owner_names: Iterable[str], language: str) -> str:
    for name in owner_names:
        first = normalize_text(name).split(" ")[0]
        if first:
            return first
    return WORDS[language]["parent"]


def person_colours(
    members: Iterable[dict[str, Any]], owner_names: Iterable[str], activities: Iterable[dict[str, Any]], *, language: str = "en",
) -> dict[str, tuple[str, str]]:
    """Who gets which colour: name key to (name as shown, colour). The
    account holder first, then the partner, then everyone else in the
    order the family listed them; a name on an activity that is nobody in
    the family (a cousin, a friend's child) still gets a colour of its own
    so the card is never grey. People with no plans this week are left
    out, so the key only shows who appears in the table."""

    owner_label = _owner_label(owner_names, language)
    order: list[tuple[str, str]] = [(household.name_key(owner_label), owner_label)]
    members = list(members)
    for member in sorted(members, key=lambda m: 0 if household.normalize_role(m.get("role")) == "partner" else 1):
        name = normalize_text(member.get("name"))
        key = household.name_key(name)
        if key and key not in {k for k, _ in order}:
            order.append((key, name))
    for activity in activities:
        for name in activity.get("who") or ():
            key = household.name_key(name)
            if household.is_self(name, owner_names):
                continue
            if key and key not in {k for k, _ in order}:
                order.append((key, normalize_text(name)))
    # The self words all mean the account holder.
    aliases = {household.name_key(word): order[0][0] for word in household._SELF_WORDS}  # noqa: SLF001 - the one list of self words
    for name in owner_names:
        aliases[household.name_key(name)] = order[0][0]
    colours: dict[str, tuple[str, str]] = {}
    shown: dict[str, tuple[str, str]] = {}
    for index, (key, label) in enumerate(order):
        if key in shown:
            continue
        shown[key] = (label, PALETTE[index % len(PALETTE)])
    for key, (label, colour) in shown.items():
        colours[key] = (label, colour)
    for alias, target in aliases.items():
        if alias and target in shown:
            colours[alias] = shown[target]
    return colours


def _person(name: Any, colours: dict[str, tuple[str, str]], owner_names: Iterable[str], language: str) -> tuple[str, str]:
    """The name as shown and the colour for a who-word: the account holder
    by whatever word they used for themselves, anyone else by name."""

    if household.is_self(name, owner_names):
        key = household.name_key(_owner_label(owner_names, language))
        return colours.get(key, (_owner_label(owner_names, language), PALETTE[0]))
    key = household.name_key(name)
    if key in colours:
        return colours[key]
    return (normalize_text(name), INK_SOFT)


def _leg_word(value: Any, colours: dict[str, tuple[str, str]], owner_names: Iterable[str], language: str) -> tuple[str, bool]:
    """Who does a leg, as shown: a person's name, the bus by its word, or
    "nobody yet" (flagged) when the leg is open."""

    text = normalize_text(value)
    if not text:
        return WORDS[language]["nobody"], True
    if household.nobody_drives(text):
        return text, False
    return _person(text, colours, owner_names, language)[0], False


# -- the facts ----------------------------------------------------------------


def _format_day(day: date, language: str) -> str:
    if language == "he":
        return f"{day.day}.{day.month}"
    return f"{day.day} {WORDS['en']['months'][day.month - 1]}"


def _time_span(activity: dict[str, Any]) -> str:
    start = normalize_text(activity.get("startTime"))
    end = normalize_text(activity.get("endTime"))
    if start and end:
        # Held left to right inside a Hebrew line, or the bidi algorithm
        # swaps the two times around the dash.
        return f"{LTR_START}{start}–{end}{LTR_END}"
    return start or end


def _plan_lines(
    activity: dict[str, Any], *, members: list[dict[str, Any]], owner_names: list[str],
    colours: dict[str, tuple[str, str]], language: str,
) -> tuple[str, str, bool, str]:
    """The two lines of a card and the colour it takes: the first is time,
    title and who it is for; the second is who takes and who collects,
    empty for a grown-up's own hours. The flag says a leg is open."""

    words = WORDS[language]
    who = [name for name in (activity.get("who") or ()) if household.name_key(name)]
    shown = [_person(name, colours, owner_names, language)[0] for name in who]
    colour = _person(who[0], colours, owner_names, language)[1] if who else INK_SOFT
    head = " ".join(part for part in (_time_span(activity), normalize_text(activity.get("title"))) if part)
    if shown:
        head = f"{head} · {', '.join(shown)}"
    place = normalize_text(activity.get("place"))
    if household.is_grown_up_activity(activity, members, owner_names):
        return head, place, False, colour
    takes, takes_open = _leg_word(activity.get("dropOffBy"), colours, owner_names, language)
    collects, collects_open = _leg_word(activity.get("pickUpBy"), colours, owner_names, language)
    legs = f"{words['takes']}: {takes} · {words['collects']}: {collects}"
    if place:
        legs = f"{place} · {legs}"
    return head, legs, takes_open or collects_open, colour


def build_week_summary(
    *,
    week_start: date,
    days: list[WeekDayPlan],
    members: list[dict[str, Any]],
    owner_names: list[str],
    language: str = "",
) -> WeekSummary:
    """The facts the picture and its caption share, in one place."""

    all_plans = [plan for day in days for plan in day.plans]
    language = language or detect_language(members, all_plans)
    colours = person_colours(members, owner_names, all_plans, language=language)
    seen: list[tuple[str, str]] = []
    facts: list[str] = []
    open_legs = 0
    for day in days:
        label = f"{WORDS['en']['weekdays'][(day.day.weekday() + 1) % 7]} {day.day.isoformat()}"
        if not day.plans:
            facts.append(f"{label}: nothing planned" + (f" ({day.note})" if day.note else ""))
            continue
        lines = []
        for plan in day.plans:
            head, legs, is_open, colour = _plan_lines(plan, members=members, owner_names=owner_names, colours=colours, language=language)
            for name in plan.get("who") or ():
                shown, shade = _person(name, colours, owner_names, language)
                if shown and (shown, shade) not in seen and shade != INK_SOFT:
                    seen.append((shown, shade))
            open_legs += int(is_open)
            line = f"{head}" + (f" ({legs})" if legs else "") + (" - a leg still has nobody" if is_open else "")
            lines.append(_BIDI_CONTROLS_RE.sub("", line))
        facts.append(f"{label}" + (f" ({day.note})" if day.note else "") + ": " + "; ".join(lines))
    # The key keeps the family's own order, not the order of first appearance.
    legend = [(label, colour) for key, (label, colour) in colours.items() if (label, colour) in seen]
    ordered: list[tuple[str, str]] = []
    for entry in legend:
        if entry not in ordered:
            ordered.append(entry)
    return WeekSummary(week_start=week_start, days=days, legend=ordered, language=language, facts=facts, open_legs=open_legs)


# -- the drawing --------------------------------------------------------------


def _ensure_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    with _FONT_LOCK:
        if _FONTS_READY:
            return
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for name, file_name in FONT_FILES.items():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file_name)))
        _FONTS_READY = True


def _display(text: str) -> str:
    """The visual order of a line: Hebrew runs reversed for a drawer that
    only goes left to right. Without the bidi package the text is drawn as
    stored, which is wrong for Hebrew but never a crash."""

    if not _HEBREW_RE.search(text):
        return _BIDI_CONTROLS_RE.sub("", text)
    try:
        from bidi.algorithm import get_display
    except ImportError:  # pragma: no cover - the package is in requirements
        return _BIDI_CONTROLS_RE.sub("", text)
    return _BIDI_CONTROLS_RE.sub("", get_display(text))


def _hex(colour: str) -> tuple[float, float, float]:
    value = colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _tint(colour: str, mix: float = TINT_MIX) -> tuple[float, float, float]:
    r, g, b = _hex(colour)
    return (r + (1 - r) * mix, g + (1 - g) * mix, b + (1 - b) * mix)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    from reportlab.pdfbase import pdfmetrics

    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and pdfmetrics.stringWidth(trial, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


class _Page:
    """A canvas that knows which way the page reads."""

    def __init__(self, canvas: Any, *, rtl: bool, height: float) -> None:
        self.c = canvas
        self.rtl = rtl
        self.height = height

    def text(self, x: float, y: float, text: str, *, font: str, size: float, colour: str, align: str = "start") -> None:
        """Draw text at x (from the reading edge) and y from the top. start
        aligns to the reading edge: left for English, right for Hebrew."""

        self.c.setFont(font, size)
        self.c.setFillColorRGB(*_hex(colour))
        shown = _display(text)
        baseline = self.height - y
        if align == "center":
            self.c.drawCentredString(x, baseline, shown)
        elif (align == "start") != self.rtl:
            self.c.drawString(x, baseline, shown)
        else:
            self.c.drawRightString(x, baseline, shown)

    def edge(self, offset: float) -> float:
        """An x at `offset` from the reading edge."""

        return PAGE_WIDTH - offset if self.rtl else offset

    def box(self, x_from_edge: float, y: float, width: float, height: float, fill: tuple[float, float, float], *, radius: float = 0.0) -> None:
        left = PAGE_WIDTH - x_from_edge - width if self.rtl else x_from_edge
        self.c.setFillColorRGB(*fill)
        self.c.setStrokeColorRGB(*fill)
        if radius:
            self.c.roundRect(left, self.height - y - height, width, height, radius, stroke=0, fill=1)
        else:
            self.c.rect(left, self.height - y - height, width, height, stroke=0, fill=1)

    def rule(self, y: float, colour: str = LINE) -> None:
        self.c.setStrokeColorRGB(*_hex(colour))
        self.c.setLineWidth(0.6)
        self.c.line(MARGIN, self.height - y, PAGE_WIDTH - MARGIN, self.height - y)


def _measure_rows(
    summary: WeekSummary, *, members: list[dict[str, Any]], owner_names: list[str], colours: dict[str, tuple[str, str]], chip_width: float,
) -> list[list[tuple[list[str], list[str], bool, str]]]:
    """The cards of each day, with their lines already wrapped."""

    rows = []
    for day in summary.days:
        cards = []
        for plan in day.plans:
            head, legs, is_open, colour = _plan_lines(
                plan, members=members, owner_names=owner_names, colours=colours, language=summary.language,
            )
            cards.append((
                _wrap(head, "WeekSans-Medium", 10.5, chip_width - 2 * CHIP_PAD - CHIP_BAR - 3),
                _wrap(legs, "WeekSans", 9.2, chip_width - 2 * CHIP_PAD - CHIP_BAR - 3) if legs else [],
                is_open,
                colour,
            ))
        rows.append(cards)
    return rows


def _card_height(card: tuple[list[str], list[str], bool, str]) -> float:
    head_lines, leg_lines, _open, _colour = card
    return CHIP_PAD * 2 + 12.5 * len(head_lines) + 11.0 * len(leg_lines)


def render_week_pdf(
    summary: WeekSummary, *, members: list[dict[str, Any]], owner_names: list[str],
) -> bytes:
    """The page as a PDF: title and dates, the colour key, then a row per
    day with its cards. The page is as tall as the week needs."""

    from reportlab.pdfgen import canvas as pdf_canvas

    _ensure_fonts()
    words = WORDS[summary.language]
    rtl = summary.language == "he"
    all_plans = [plan for day in summary.days for plan in day.plans]
    colours = person_colours(members, owner_names, all_plans, language=summary.language)
    chip_width = PAGE_WIDTH - 2 * MARGIN - DAY_COLUMN
    rows = _measure_rows(summary, members=members, owner_names=owner_names, colours=colours, chip_width=chip_width)

    # Legend lines: as many as the names need.
    from reportlab.pdfbase import pdfmetrics

    legend_entries = summary.legend
    legend_rows: list[list[tuple[str, str]]] = [[]]
    used = 0.0
    for label, colour in legend_entries:
        width = 10 + pdfmetrics.stringWidth(label, "WeekSans-Medium", 10) + 16
        if legend_rows[-1] and used + width > PAGE_WIDTH - 2 * MARGIN:
            legend_rows.append([])
            used = 0.0
        legend_rows[-1].append((label, colour))
        used += width

    row_heights = []
    for day, cards in zip(summary.days, rows):
        if cards:
            inner = sum(_card_height(card) for card in cards) + CHIP_GAP * (len(cards) - 1)
        else:
            inner = 16.0
        label_height = 30.0 + (11.0 if day.note else 0.0)
        row_heights.append(max(MIN_ROW_HEIGHT, inner + 2 * ROW_GAP, label_height + 2 * ROW_GAP))

    top = MARGIN + 30.0  # title block
    legend_top = top + 26.0
    legend_height = 16.0 * len(legend_rows) if legend_entries else 0.0
    table_top = legend_top + legend_height + 14.0
    height = table_top + sum(row_heights) + MARGIN + 14.0

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, height))
    c.setTitle(words["title"])
    page = _Page(c, rtl=rtl, height=height)
    page.box(0, 0, PAGE_WIDTH, height, _hex(PAPER))

    # Title and the week's dates.
    week_end = summary.week_start + timedelta(days=6)
    page.text(page.edge(MARGIN), MARGIN + 16, words["title"], font="WeekSans-SemiBold", size=19, colour=INK)
    span = f"{_format_day(summary.week_start, summary.language)} – {_format_day(week_end, summary.language)}"
    page.text(page.edge(PAGE_WIDTH - MARGIN), MARGIN + 15, span, font="WeekSans", size=11, colour=INK_SOFT, align="end")

    # The colour key.
    y = legend_top
    for entries in legend_rows:
        x = MARGIN
        for label, colour in entries:
            page.box(x, y - 8, 9, 9, _hex(colour), radius=4.5)
            page.text(page.edge(x + 14), y, label, font="WeekSans-Medium", size=10, colour=INK)
            x += 14 + pdfmetrics.stringWidth(label, "WeekSans-Medium", 10) + 16
        y += 16.0

    # The table.
    y = table_top
    page.rule(y - 4)
    for index, (day, cards, row_height) in enumerate(zip(summary.days, rows, row_heights)):
        if index % 2 == 1:
            page.box(MARGIN, y, PAGE_WIDTH - 2 * MARGIN, row_height, _hex(ROW_ALT))
        weekday = words["weekdays"][(day.day.weekday() + 1) % 7]
        page.text(page.edge(MARGIN + 8), y + ROW_GAP + 12, weekday, font="WeekSans-SemiBold", size=11.5, colour=INK)
        page.text(page.edge(MARGIN + 8), y + ROW_GAP + 25, _format_day(day.day, summary.language), font="WeekSans", size=9.5, colour=INK_SOFT)
        if day.note:
            for line_index, line in enumerate(_wrap(day.note, "WeekSans", 8.2, DAY_COLUMN - 14)[:2]):
                page.text(page.edge(MARGIN + 8), y + ROW_GAP + 37 + 10 * line_index, line, font="WeekSans", size=8.2, colour=NOTE)
        chip_y = y + ROW_GAP
        if not cards:
            page.text(page.edge(MARGIN + DAY_COLUMN + CHIP_PAD), chip_y + 12, words["nothing"], font="WeekSans", size=9.5, colour=INK_SOFT)
        for card in cards:
            head_lines, leg_lines, is_open, colour = card
            card_height = _card_height(card)
            page.box(MARGIN + DAY_COLUMN, chip_y, chip_width, card_height, _tint(colour), radius=CHIP_RADIUS)
            page.box(MARGIN + DAY_COLUMN, chip_y, CHIP_BAR, card_height, _hex(colour), radius=2.0)
            text_x = MARGIN + DAY_COLUMN + CHIP_BAR + CHIP_PAD
            line_y = chip_y + CHIP_PAD + 9.5
            for line in head_lines:
                page.text(page.edge(text_x), line_y, line, font="WeekSans-Medium", size=10.5, colour=INK)
                line_y += 12.5
            for line in leg_lines:
                page.text(page.edge(text_x), line_y, line, font="WeekSans", size=9.2, colour=OPEN_LEG if is_open else INK_SOFT)
                line_y += 11.0
            chip_y += card_height + CHIP_GAP
        y += row_height
        page.rule(y)

    page.text(page.edge(MARGIN), height - MARGIN + 2, "Assistyca", font="WeekSans-Medium", size=8.5, colour=INK_SOFT)
    c.showPage()
    c.save()
    return buffer.getvalue()


def pdf_to_png(pdf_bytes: bytes, *, scale: float = RASTER_SCALE) -> bytes:
    """The first page of a PDF as a PNG. PyMuPDF is imported here so that a
    server without it still imports this module and fails only when it
    tries to draw."""

    import fitz  # PyMuPDF

    document = fitz.open("pdf", pdf_bytes)
    try:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def render_week_image(
    summary: WeekSummary, *, members: list[dict[str, Any]], owner_names: list[str],
) -> tuple[bytes, bytes]:
    """The picture and the PDF it was drawn from."""

    pdf_bytes = render_week_pdf(summary, members=members, owner_names=owner_names)
    return pdf_to_png(pdf_bytes), pdf_bytes


def next_week_start(today: date) -> date:
    """The Sunday that starts the coming week: tomorrow when today is
    Saturday, which is when the picture goes out."""

    days_ahead = (6 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


__all__ = [
    "WeekDayPlan",
    "WeekSummary",
    "build_week_summary",
    "detect_language",
    "next_week_start",
    "pdf_to_png",
    "person_colours",
    "render_week_image",
    "render_week_pdf",
]
