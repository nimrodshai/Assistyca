"""The week ahead as one picture.

On Saturday evening a family gets next week at a glance: a calendar page
with a column per day, Sunday to Saturday, the hours down the side, and
every plan a block at its time - one colour per person, with the key under
the title, so a parent can find their child's week by colour before
reading a word. Each block says what it is, when, who it is for, and who
takes and who collects; a leg nobody is down for yet says so in red,
because that is the thing to settle before Sunday.

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

# A landscape page the shape of a screen: a column per day, the hours down
# the side. Rendered at two device pixels per point it is 2000 by 1200.
PAGE_WIDTH = 1000.0
PAGE_HEIGHT = 600.0
MARGIN = 22.0
TIME_GUTTER = 34.0
TITLE_BLOCK = 44.0
LEGEND_LINE = 18.0
DAY_HEADER = 42.0
UNTIMED_STRIP = 34.0
FOOTER = 8.0
# The hours a day shows when nothing falls outside them.
DEFAULT_FIRST_HOUR = 7
DEFAULT_LAST_HOUR = 19
MIN_HOUR_HEIGHT = 30.0
MIN_BLOCK_HEIGHT = 14.0
BLOCK_INSET = 2.0
BLOCK_PAD = 4.0
# The tag a taker's or collector's name is drawn in, in their colour.
TAG_HEIGHT = 10.0
TAG_PAD = 3.0
# Two tags on consecutive lines keep this much paper between them.
TAG_GAP = 1.0
# Device pixels per point: 1000pt becomes 2000px, sharp on a phone when
# zoomed and well under WhatsApp's size limit.
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
TINT_MIX = 0.86  # how far each colour is pulled towards white for a block's fill
BAND_TINT = 0.94  # fainter still, for a grown-up's own hours behind the day

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
        "nobody": "nobody",
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
        "nobody": "אין",
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
    # Whoever a plan is for, and whoever takes or collects - a grandparent,
    # a neighbour - so the tag with their name has a colour of its own.
    for activity in activities:
        for name in list(activity.get("who") or ()) + [activity.get("dropOffBy"), activity.get("pickUpBy")]:
            key = household.name_key(name)
            if not key or household.is_self(name, owner_names) or household.nobody_drives(name):
                continue
            if key not in {k for k, _ in order}:
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
            named = list(plan.get("who") or ())
            if not household.is_grown_up_activity(plan, members, owner_names):
                named += [plan.get("dropOffBy"), plan.get("pickUpBy")]
            for name in named:
                if not household.name_key(name) or household.nobody_drives(name):
                    continue
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


def _width(text: str, font: str, size: float) -> float:
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(_BIDI_CONTROLS_RE.sub("", text), font, size)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if current and _width(trial, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def _clip(text: str, font: str, size: float, width: float) -> str:
    """The text cut to the width with an ellipsis, for a block too short to
    wrap in."""

    if _width(text, font, size) <= width:
        return text
    cut = text
    while cut and _width(f"{cut}…", font, size) > width:
        cut = cut[:-1]
    return f"{cut.rstrip()}…" if cut else ""


def _minutes(value: Any) -> int | None:
    text = normalize_text(value)
    if not text or ":" not in text:
        return None
    try:
        hours, minutes = text.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return None


class _Page:
    """A canvas that knows which way the page reads: x is measured from the
    reading edge, which is the right edge on a Hebrew page, so the same
    drawing code lays the days out from right to left there."""

    def __init__(self, canvas: Any, *, rtl: bool, height: float) -> None:
        self.c = canvas
        self.rtl = rtl
        self.height = height

    def text(self, x: float, y: float, text: str, *, font: str, size: float, colour: str, align: str = "start") -> None:
        """Draw text at x from the reading edge and y from the top. start
        aligns to the reading edge: left for English, right for Hebrew."""

        self.c.setFont(font, size)
        self.c.setFillColorRGB(*_hex(colour))
        shown = _display(text)
        baseline = self.height - y
        real_x = PAGE_WIDTH - x if self.rtl else x
        if align == "center":
            self.c.drawCentredString(real_x, baseline, shown)
        elif (align == "start") != self.rtl:
            self.c.drawString(real_x, baseline, shown)
        else:
            self.c.drawRightString(real_x, baseline, shown)

    def box(self, x: float, y: float, width: float, height: float, fill: tuple[float, float, float], *, radius: float = 0.0) -> None:
        left = PAGE_WIDTH - x - width if self.rtl else x
        self.c.setFillColorRGB(*fill)
        self.c.setStrokeColorRGB(*fill)
        if radius:
            self.c.roundRect(left, self.height - y - height, width, height, radius, stroke=0, fill=1)
        else:
            self.c.rect(left, self.height - y - height, width, height, stroke=0, fill=1)

    def hline(self, x: float, y: float, width: float, colour: str = LINE, *, line_width: float = 0.6) -> None:
        left = PAGE_WIDTH - x - width if self.rtl else x
        self.c.setStrokeColorRGB(*_hex(colour))
        self.c.setLineWidth(line_width)
        self.c.line(left, self.height - y, left + width, self.height - y)

    def vline(self, x: float, y: float, height: float, colour: str = LINE, *, line_width: float = 0.6) -> None:
        real_x = PAGE_WIDTH - x if self.rtl else x
        self.c.setStrokeColorRGB(*_hex(colour))
        self.c.setLineWidth(line_width)
        self.c.line(real_x, self.height - y, real_x, self.height - y - height)


@dataclass
class _Leg:
    """One line of a block about a drive: the label ("takes:"), the word
    after it, and the colour of the person it names - empty for the bus
    or for nobody, which are words rather than people."""

    label: str
    text: str
    colour: str = ""
    is_open: bool = False


@dataclass
class _Block:
    start: int  # minutes from midnight
    end: int
    head: str
    who: str
    place: str
    legs: list[_Leg]
    is_open: bool
    colour: str
    # A grown-up's own hours - work, a shift - are drawn as a faint band
    # behind the day rather than a block beside the children's, so the
    # column stays theirs.
    band: bool = False
    lane: int = 0
    lanes: int = 1


def _lay_out_lanes(blocks: list[_Block]) -> None:
    """Blocks that overlap in time share the column side by side: each is
    given a lane, and every block in a run of overlaps knows how many lanes
    the run has, so their widths add up to the column."""

    blocks.sort(key=lambda block: (block.start, block.end))
    cluster: list[_Block] = []
    cluster_end = -1
    lane_ends: list[int] = []

    def close() -> None:
        for block in cluster:
            block.lanes = max(1, len(lane_ends))

    for block in blocks:
        if cluster and block.start >= cluster_end:
            close()
            cluster, lane_ends = [], []
        for index, end in enumerate(lane_ends):
            if block.start >= end:
                block.lane = index
                lane_ends[index] = block.end
                break
        else:
            block.lane = len(lane_ends)
            lane_ends.append(block.end)
        cluster.append(block)
        cluster_end = block.end if len(cluster) == 1 else max(cluster_end, block.end)
    close()


def _blocks_for_day(
    day: WeekDayPlan, *, members: list[dict[str, Any]], owner_names: list[str], colours: dict[str, tuple[str, str]], language: str,
) -> tuple[list[_Block], list[_Block]]:
    """The day's plans as timed blocks (bands first), and the ones with no
    time. A block's words are split into short lines - what, who, when,
    then each leg - because a column shared by two children is narrow."""

    timed: list[_Block] = []
    untimed: list[_Block] = []
    for plan in day.plans:
        _head, _legs, is_open, colour = _plan_lines(plan, members=members, owner_names=owner_names, colours=colours, language=language)
        title = normalize_text(plan.get("title"))
        who = ", ".join(
            _person(name, colours, owner_names, language)[0] for name in (plan.get("who") or ()) if household.name_key(name)
        )
        band = household.is_grown_up_activity(plan, members, owner_names)
        legs: list[_Leg] = []
        if not band:
            words = WORDS[language]
            for label, key in ((words["takes"], "dropOffBy"), (words["collects"], "pickUpBy")):
                text, leg_open = _leg_word(plan.get(key), colours, owner_names, language)
                is_person = not leg_open and not household.nobody_drives(text)
                legs.append(_Leg(
                    label=f"{label}:", text=text,
                    colour=_person(plan.get(key), colours, owner_names, language)[1] if is_person else "",
                    is_open=leg_open,
                ))
        start = _minutes(plan.get("startTime"))
        end = _minutes(plan.get("endTime"))
        block = _Block(
            start=0, end=0, head=title, who=who, place=normalize_text(plan.get("place")), legs=legs,
            is_open=is_open, colour=colour, band=band,
        )
        if start is None and end is None:
            untimed.append(block)
            continue
        if start is None:
            start = max(0, int(end) - 60)
        if end is None or end <= start:
            end = start + 60
        block.start, block.end = start, end
        timed.append(block)
    _lay_out_lanes([block for block in timed if not block.band])
    timed.sort(key=lambda block: (not block.band, block.start, block.end))
    return timed, untimed


def render_week_pdf(
    summary: WeekSummary, *, members: list[dict[str, Any]], owner_names: list[str],
) -> bytes:
    """The week as a calendar page: a column per day, the hours down the
    side, each plan a block at its time in its person's colour, the colour
    key under the title. One landscape page, sized like a screen."""

    from reportlab.pdfgen import canvas as pdf_canvas

    _ensure_fonts()
    words = WORDS[summary.language]
    rtl = summary.language == "he"
    all_plans = [plan for day in summary.days for plan in day.plans]
    colours = person_colours(members, owner_names, all_plans, language=summary.language)
    days = [
        _blocks_for_day(day, members=members, owner_names=owner_names, colours=colours, language=summary.language)
        for day in summary.days
    ]

    # The hours shown: the usual day, widened to whatever the week holds.
    first_minute, last_minute = DEFAULT_FIRST_HOUR * 60, DEFAULT_LAST_HOUR * 60
    for timed, _untimed in days:
        for block in timed:
            first_minute = min(first_minute, block.start)
            last_minute = max(last_minute, block.end)
    first_hour = first_minute // 60
    last_hour = -(-last_minute // 60)
    hours = max(1, last_hour - first_hour)
    has_untimed = any(untimed for _timed, untimed in days)
    untimed_height = UNTIMED_STRIP if has_untimed else 0.0

    grid_top = MARGIN + TITLE_BLOCK + (LEGEND_LINE if summary.legend else 0.0) + DAY_HEADER + untimed_height
    hour_height = max(MIN_HOUR_HEIGHT, (PAGE_HEIGHT - grid_top - MARGIN - FOOTER) / hours)
    height = grid_top + hour_height * hours + FOOTER + MARGIN
    column_width = (PAGE_WIDTH - 2 * MARGIN - TIME_GUTTER) / 7
    grid_x = MARGIN + TIME_GUTTER

    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, height))
    c.setTitle(words["title"])
    page = _Page(c, rtl=rtl, height=height)
    page.box(0, 0, PAGE_WIDTH, height, _hex(PAPER))

    # Title, dates, and the colour key.
    week_end = summary.week_start + timedelta(days=6)
    page.text(MARGIN, MARGIN + 15, words["title"], font="WeekSans-SemiBold", size=17, colour=INK)
    span = f"{_format_day(summary.week_start, summary.language)} – {_format_day(week_end, summary.language)}"
    page.text(PAGE_WIDTH - MARGIN, MARGIN + 14, span, font="WeekSans", size=10.5, colour=INK_SOFT, align="end")
    y = MARGIN + TITLE_BLOCK
    if summary.legend:
        x = MARGIN
        for label, colour in summary.legend:
            page.box(x, y - 14.5, 8, 8, _hex(colour), radius=4)
            page.text(x + 12, y - 7, label, font="WeekSans-Medium", size=9.5, colour=INK)
            x += 12 + _width(label, "WeekSans-Medium", 9.5) + 14
        y += LEGEND_LINE

    # Day headers.
    header_top = y
    for index, day in enumerate(summary.days):
        x = grid_x + index * column_width
        centre = x + column_width / 2
        weekday = words["weekdays"][(day.day.weekday() + 1) % 7]
        page.text(centre, header_top + 11, weekday, font="WeekSans-SemiBold", size=9, colour=INK, align="center")
        page.text(centre, header_top + 25, _format_day(day.day, summary.language), font="WeekSans", size=9, colour=INK_SOFT, align="center")
        if day.note:
            note = _clip(day.note, "WeekSans", 7, column_width - 6)
            page.text(centre, header_top + 36, note, font="WeekSans", size=7, colour=NOTE, align="center")
    y = header_top + DAY_HEADER

    # Plans with no time, in a strip under the day's name.
    if has_untimed:
        for index, (_timed, untimed) in enumerate(days):
            x = grid_x + index * column_width
            chip_y = y + 2
            for block in untimed[:2]:
                page.box(x + 2, chip_y, column_width - 4, 13, _tint(block.colour), radius=3)
                page.box(x + 2, chip_y, 2.5, 13, _hex(block.colour), radius=1)
                label = f"{block.head} · {block.who}" if block.who else block.head
                page.text(x + 7, chip_y + 9.5, _clip(label, "WeekSans-Medium", 7, column_width - 12), font="WeekSans-Medium", size=7, colour=INK)
                chip_y += 15
        y += untimed_height

    # The grid.
    grid_height = hour_height * hours
    for index in range(7):
        if index % 2 == 1:
            page.box(grid_x + index * column_width, y, column_width, grid_height, _hex(ROW_ALT))
    for hour_index in range(hours + 1):
        line_y = y + hour_index * hour_height
        page.hline(grid_x, line_y, column_width * 7)
        if hour_index < hours:
            page.text(grid_x - 5, line_y + 3.5 + (hour_height / 2 if hour_height < 18 else 9), f"{first_hour + hour_index:02d}:00",
                      font="WeekSans", size=7.5, colour=INK_SOFT, align="end")
    for index in range(8):
        page.vline(grid_x + index * column_width, y, grid_height)

    # The blocks.
    band_labels: list[tuple[float, float, float, _Block, list[_Block]]] = []
    for index, (timed, _untimed) in enumerate(days):
        column_x = grid_x + index * column_width
        for block in timed:
            top = y + (block.start - first_hour * 60) / 60 * hour_height
            bottom = y + (block.end - first_hour * 60) / 60 * hour_height
            if block.band:
                # The grown-up's own hours: a faint wash across the column,
                # under everything else; its one line is drawn last, at the
                # foot of the band, where the day is usually clear.
                page.box(column_x + 0.5, top, column_width - 1, bottom - top, _tint(block.colour, BAND_TINT))
                page.hline(column_x + 0.5, top, column_width - 1, block.colour, line_width=1.2)
                page.hline(column_x + 0.5, bottom, column_width - 1, block.colour, line_width=1.2)
                band_labels.append((column_x, top, bottom, block, [b for b in timed if not b.band]))
                continue
            lane_width = (column_width - 2 * BLOCK_INSET) / block.lanes
            x = column_x + BLOCK_INSET + block.lane * lane_width
            block_height = max(MIN_BLOCK_HEIGHT, bottom - top - 1.5)
            width = lane_width - 1.5
            page.box(x, top + 0.75, width, block_height, _tint(block.colour), radius=3.5)
            page.box(x, top + 0.75, 3, block_height, _hex(block.colour), radius=1.5)
            text_x = x + 3 + BLOCK_PAD
            text_width = width - 3 - 2 * BLOCK_PAD
            # What, who, when, then each leg: every line wrapped to the
            # block's width rather than cut, and drawn while there is room.
            lines: list[tuple[str, str, float, str] | _Leg] = []
            for line in _wrap(block.head, "WeekSans-Medium", 8, text_width)[:2]:
                lines.append((line, "WeekSans-Medium", 8, INK))
            if block.who:
                for line in _wrap(block.who, "WeekSans-Medium", 7.2, text_width):
                    lines.append((line, "WeekSans-Medium", 7.2, INK))
            lines.append((_time_label(block), "WeekSans", 7.2, INK_SOFT))
            if block.place:
                for line in _wrap(block.place, "WeekSans", 7.2, text_width):
                    lines.append((line, "WeekSans", 7.2, INK_SOFT))
            for leg in block.legs:
                if leg.colour:
                    lines.append(leg)
                else:
                    for line in _wrap(f"{leg.label} {leg.text}", "WeekSans", 7.2, text_width):
                        lines.append((line, "WeekSans", 7.2, OPEN_LEG if leg.is_open else INK_SOFT))
            room = block_height - 2 * BLOCK_PAD
            first_line_y = top + 0.75 + BLOCK_PAD + 7
            line_y = first_line_y
            drawn = 0
            for item in lines:
                if isinstance(item, _Leg):
                    # The label, then the person's name as a tag in their
                    # colour; on the next line when the two will not fit.
                    label_width = _width(item.label, "WeekSans", 7.2)
                    tag_width = _width(item.text, "WeekSans-Medium", 6.6) + 2 * TAG_PAD
                    beside = label_width + 3 + tag_width <= text_width
                    # A line that carries a tag is as tall as the tag and its gap.
                    step = TAG_HEIGHT + TAG_GAP
                    needed = step if beside else 2 * step
                    if drawn > 0 and (line_y - first_line_y) + needed > room:
                        break
                    page.text(text_x, line_y, item.label, font="WeekSans", size=7.2, colour=INK_SOFT)
                    tag_x = text_x + label_width + 3 if beside else text_x
                    tag_y = line_y if beside else line_y + step
                    page.box(tag_x, tag_y - 7.6, min(tag_width, text_width), TAG_HEIGHT, _hex(item.colour), radius=2.5)
                    page.text(tag_x + TAG_PAD, tag_y - 0.4, _clip(item.text, "WeekSans-Medium", 6.6, text_width - 2 * TAG_PAD),
                              font="WeekSans-Medium", size=6.6, colour=PAPER)
                    line_y += needed
                    drawn += 1 if beside else 2
                    continue
                text, font, size, colour = item
                step = size + 2.4
                if drawn > 0 and (line_y - first_line_y) + step > room:
                    break
                page.text(text_x, line_y, _clip(text, font, size, text_width), font=font, size=size, colour=colour)
                line_y += step
                drawn += 1

    for column_x, top, bottom, block, others in band_labels:
        # The line goes at the foot of the band, or its head, whichever
        # nothing else is drawn across; under a block it would not be read.
        label = _clip(f"{block.head} · {block.who}  {_time_label(block)}", "WeekSans-Medium", 6.8, column_width - 6)
        foot_clear = not any(other.start < block.end and other.end > block.end - 20 for other in others)
        head_clear = not any(other.start < block.start + 20 and other.end > block.start for other in others)
        if foot_clear:
            page.text(column_x + 3, bottom - 3, label, font="WeekSans-Medium", size=6.8, colour=block.colour)
        elif head_clear:
            page.text(column_x + 3, top + 8.5, label, font="WeekSans-Medium", size=6.8, colour=block.colour)

    page.text(PAGE_WIDTH - MARGIN, height - MARGIN + 3, "Assistyca", font="WeekSans-Medium", size=8, colour=INK_SOFT, align="end")
    c.showPage()
    c.save()
    return buffer.getvalue()


def _time_label(block: _Block) -> str:
    return f"{LTR_START}{block.start // 60:02d}:{block.start % 60:02d}–{block.end // 60:02d}:{block.end % 60:02d}{LTR_END}"


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
