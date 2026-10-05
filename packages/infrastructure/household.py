"""The family an account keeps, and the week it runs.

A family account is about the people in it and the afternoons they share:
who the partner is and how to reach them, the children and where they are
each day, which activity is on which day and who drives to it - and the
grown-ups' own weeks, their work above all, which say when they cannot be
the one driving. None of that
is a passing fact. It is kept in its own tables, apart from the short
remembered facts that give way to newer ones, and it goes only when the
person says so.

This module holds the plain rules the store, the chat tools and the page
share: what a role is, how a day and a time are written, who "me" is, and
the compact shape the assistant reads the family in. Nothing here touches
the database or the network.
"""

from __future__ import annotations

import re
from datetime import date
from datetime import timedelta
from typing import Any
from typing import Iterable

ACCOUNT_KINDS = ("business", "family")
MEMBER_ROLES = ("partner", "child", "other")
# Who may change the week: the two parents, which is the account holder and
# the partner. A grandparent who joined gets the pickups that are theirs and
# can read the week, and that is all - the week is the parents' to set.
WEEK_EDITOR_ROLES = ("owner", "partner")
# An invitation to join the family's account stands this long. It is a link
# the parent forwards and the other person opens when they get to it, so it
# is given days, not the minutes a sign-in code gets.
INVITE_TTL_DAYS = 14
# The conversation a joined phone has with the assistant is its own thread,
# kept apart from the account holder's under this key.
MEMBER_THREAD_PREFIX = "phone:"
# The week as it is lived where most of these families are: it starts on
# Sunday. Stored as these codes, shown in the person's own words.
WEEKDAY_CODES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
# Python counts Monday as 0; this maps a date's weekday() to a code.
PYTHON_WEEKDAY_TO_CODE = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
GETTING_TO_KNOW_STATUSES = ("not_started", "in_progress", "postponed", "done")

MAX_MEMBERS = 20
MAX_ACTIVITIES = 80
MAX_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_TEXT_LENGTH = 240

# Words a person uses for themselves when saying who drives. The assistant
# is asked to write "me"; the others are here because people type.
_SELF_WORDS = {"me", "myself", "i", "owner", "אני", "אני עצמי"}
# Ways a child gets there without anyone driving them: the school bus, the
# shuttle, their own two feet. Written in "who drives" so the morning can say
# it and nobody is asked to cover it - but it is not a drive, so nobody is
# told it is time to leave.
_NOBODY_DRIVES_WORDS = {
    "bus", "the bus", "school bus", "the school bus", "shuttle", "the shuttle", "hasaa", "train", "the train",
    "walks", "walk", "walking", "on foot", "by foot", "bike", "bicycle", "by bike", "scooter",
    "alone", "on their own", "by themselves", "themselves", "on his own", "by himself", "himself",
    "on her own", "by herself", "herself", "independently",
    "אוטובוס", "באוטובוס", "הסעה", "בהסעה", "רכבת", "ברכבת", "ברגל", "הולך", "הולכת", "הולך ברגל", "הולכת ברגל",
    "לבד", "בעצמו", "בעצמה", "אופניים", "באופניים", "קורקינט", "בקורקינט",
}
_NOBODY_DRIVES_RE = re.compile(
    r"\b(?:bus|shuttle|train|walks?|walking|foot|bike|bicycle|scooter|alone|themselves|himself|herself"
    r"|independently)\b|(?:^|\s)(?:אוטובוס|באוטובוס|הסעה|בהסעה|רכבת|ברכבת|ברגל|לבד|בעצמו|בעצמה|אופניים|באופניים"
    r"|קורקינט|בקורקינט)(?:\s|$)"
)
# A phrase may start with one of these capitalised ("Takes the bus home") and
# still be nobody driving; any other capitalised word is somebody's name.
_NOBODY_DRIVES_LEADING = {
    "the", "a", "on", "by", "takes", "goes", "comes", "gets", "rides", "walks", "school", "home",
    "bus", "shuttle", "train", "bike", "alone",
}
_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def name_key(value: Any) -> str:
    """How two spellings of one name are told to be the same person."""

    return clean(value, MAX_NAME_LENGTH).casefold()


def normalize_account_kind(value: Any) -> str:
    return "family" if clean(value).lower() == "family" else "business"


def normalize_role(value: Any) -> str:
    role = clean(value).lower()
    return role if role in MEMBER_ROLES else "other"


def normalize_email_address(value: Any) -> str:
    text = clean(value, 200)
    return text if _EMAIL_RE.match(text) else ""


def normalize_time(value: Any) -> str:
    """"7:30", "07.30", "17" -> "07:30", "07:30", "17:00"; anything else -> ""."""

    match = _TIME_RE.match(str(value or ""))
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def normalize_days(values: Iterable[Any]) -> list[str]:
    """Weekday codes, each once, in week order."""

    wanted = {clean(value).lower()[:3] for value in values or ()}
    return [code for code in WEEKDAY_CODES if code in wanted]


def weekday_code(day: date) -> str:
    return PYTHON_WEEKDAY_TO_CODE[day.weekday()]


def is_self(who: Any, owner_names: Iterable[str] = ()) -> bool:
    """Whether "who drives" names the account holder."""

    text = name_key(who)
    if not text or nobody_drives(text):
        return False
    if text in _SELF_WORDS:
        return True
    names = {name_key(name) for name in owner_names if name_key(name)}
    firsts = {name.split(" ")[0] for name in names}
    return text in names or text in firsts


def is_named(who: Any, names: Iterable[str]) -> bool:
    """Whether "who drives" is one of these people by name - the name as
    given or its first word - and never by "me", which is the account
    holder's word for themselves."""

    text = name_key(who)
    if not text or text in _SELF_WORDS or nobody_drives(text):
        return False
    known = {name_key(name) for name in names if name_key(name)}
    firsts = {name.split(" ")[0] for name in known}
    return text in known or text in firsts


def can_change_week(role: Any) -> bool:
    """Whether someone with this role may change the week. "owner" is the
    account holder; anyone else is a member row's role."""

    return clean(role).lower() in WEEK_EDITOR_ROLES


def member_thread_id(wa_id: Any) -> str:
    """The conversation key for a phone that joined the family."""

    number = re.sub(r"\D+", "", str(wa_id or ""))
    return f"{MEMBER_THREAD_PREFIX}{number}" if number else ""


def describe_speaker(member: dict[str, Any] | None, *, owner_name: str = "") -> dict[str, Any]:
    """Who is writing, as the assistant reads it when it is not the account
    holder: their name and role, whether the week is theirs to change, and
    what name the week knows them by - the drives written under that name
    are theirs, while "me" in the week is always the account holder."""

    if not member:
        return {}
    role = normalize_role(member.get("role"))
    name = clean(member.get("name"), MAX_NAME_LENGTH)
    speaker: dict[str, Any] = {
        "name": name,
        "role": role,
        "isOwner": False,
        "canChangeWeek": can_change_week(role),
        "drivesAs": name,
    }
    if clean(owner_name):
        speaker["accountHolder"] = clean(owner_name, MAX_NAME_LENGTH)
    return speaker


def invite_candidates(members: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The grown-ups in the family who could be brought onto the account and
    are not on it yet: the partner first, then anyone else who is not a
    child. Each with what joining would give them, so the offer is exact."""

    found = []
    for member in members or ():
        role = normalize_role(member.get("role"))
        name = clean(member.get("name"), MAX_NAME_LENGTH)
        if role == "child" or not name or member.get("waId") or member.get("onWhatsApp"):
            continue
        found.append({"name": name, "role": role, "theyGet": member_nudges(role)})
    found.sort(key=lambda entry: 0 if entry["role"] == "partner" else 1)
    return found


def member_nudges(role: Any) -> tuple[str, ...]:
    """What a joined phone is told about the week on its own: a parent gets
    the whole of it - the morning plan, the evening before when tomorrow
    still has nobody down for a pickup, and a word before each drive of
    theirs; anyone else gets only the word before the drives that are
    theirs."""

    if normalize_role(role) == "partner":
        return ("morning", "evening", "rides")
    return ("rides",)


def nobody_drives(who: Any) -> bool:
    """Whether "who drives" says the child gets there with nobody driving:
    the bus, the shuttle, on foot, on their own.

    Written down it is not a gap - the morning says "collects: the bus" and
    nobody is asked to cover it - and it is not anyone's drive either, so no
    one is told it is time to leave. An empty value is a gap, not this.
    """

    text = name_key(who)
    if not text:
        return False
    if text in _NOBODY_DRIVES_WORDS:
        return True
    # A phrase around one of the words - "takes the bus home", "walks back",
    # "הולכת לבד הביתה" - is still nobody driving. A name next to one of them
    # ("Dana, by bus") is still a person.
    if not _NOBODY_DRIVES_RE.search(text):
        return False
    words = clean(who, MAX_NAME_LENGTH).replace(",", " ").split()
    if any(word[:1].isupper() for word in words[1:]):
        return False
    return not words[0][:1].isupper() or words[0].casefold() in _NOBODY_DRIVES_LEADING


_BIRTHDAY_RE = re.compile(r"^\s*(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\s*$")
BIRTHDAY_REMINDER_DAYS = 30

# The ready-made birthday list: each step with how many days before the
# birthday it is due. A child's birthday is a party; anyone else's is a
# celebration and a present. The assistant words each step in the person's
# language and leaves out what does not fit; the days come from here.
BIRTHDAY_LIST_TEMPLATES: dict[str, tuple[tuple[str, int], ...]] = {
    "child": (
        ("Decide what kind of party, where, and roughly how many children", 28),
        ("Book the place or the activity", 24),
        ("Put together the guest list", 24),
        ("Send the invitations", 21),
        ("Plan the celebration at kindergarten or school", 10),
        ("Confirm who is coming", 7),
        ("Order or bake the cake", 7),
        ("Buy the present", 7),
        ("Party bags for the guests", 5),
        ("Decorations, candles, plates and drinks", 3),
        ("Charge the phone or camera for photos", 1),
    ),
    "adult": (
        ("Decide how to celebrate: dinner, a trip, a party or a quiet day", 28),
        ("Book the restaurant, place or tickets", 21),
        ("Arrange a babysitter if needed", 14),
        ("Choose and order the present", 14),
        ("Invite whoever should be there", 14),
        ("Order the cake or flowers", 5),
        ("Write the card", 2),
    ),
}


def birthday_template_kind(role: Any) -> str:
    return "child" if normalize_role(role) == "child" else "adult"


def normalize_birthday(value: Any) -> str:
    """"2021-10-12" stays; "10-12" (no year given) becomes "--10-12";
    anything that is not a real day becomes ""."""

    text = str(value or "").strip()
    if text.startswith("--"):
        text = text[2:]
    match = _BIRTHDAY_RE.match(text)
    if not match:
        return ""
    year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
    try:
        date(int(year) if year else 2000, month, day)
    except ValueError:
        return ""
    return f"{year}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"


def _birthday_parts(birthday: Any) -> tuple[int | None, int, int] | None:
    text = normalize_birthday(birthday)
    if not text:
        return None
    if text.startswith("--"):
        return None, int(text[2:4]), int(text[5:7])
    return int(text[:4]), int(text[5:7]), int(text[8:10])


def _on_year(year: int, month: int, day: int) -> date:
    # 29 February is kept on 28 February in a year without it.
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def next_birthday(birthday: Any, today: date) -> date | None:
    """The next time the birthday comes round, today included."""

    parts = _birthday_parts(birthday)
    if parts is None:
        return None
    _year, month, day = parts
    upcoming = _on_year(today.year, month, day)
    return upcoming if upcoming >= today else _on_year(today.year + 1, month, day)


def age_from_birthday(birthday: Any, today: date) -> int | None:
    parts = _birthday_parts(birthday)
    if parts is None or parts[0] is None:
        return None
    year, month, day = parts
    return today.year - year - ((today.month, today.day) < (month, day))


def birthday_list_items(role: Any, birthday_on: date, today: date) -> list[dict[str, Any]]:
    """The template for this person, each step with its due date. A step
    whose day has already gone is due today rather than overdue."""

    return [
        {"step": index, "text": text, "dueOn": max(today, birthday_on - timedelta(days=days)).isoformat()}
        for index, (text, days) in enumerate(BIRTHDAY_LIST_TEMPLATES[birthday_template_kind(role)], start=1)
    ]


def current_age(age: Any, noted_on: Any, today: date, birthday: Any = "") -> int | None:
    """An age said once keeps counting: said as 4 two years ago is 6 now.
    A birthday with its year, when there is one, is the better source."""

    from_birthday = age_from_birthday(birthday, today)
    if from_birthday is not None:
        return from_birthday
    try:
        years = int(age)
    except (TypeError, ValueError):
        return None
    try:
        noted = date.fromisoformat(str(noted_on or "")[:10])
    except ValueError:
        return years
    passed = today.year - noted.year - ((today.month, today.day) < (noted.month, noted.day))
    return years + max(0, passed)


def grown_up_names(members: Iterable[dict[str, Any]] | None) -> set[str]:
    """The name keys of everyone in the family who is not a child."""

    return {
        name_key(member.get("name"))
        for member in members or ()
        if name_key(member.get("name")) and normalize_role(member.get("role")) != "child"
    }


def is_grown_up_activity(
    activity: dict[str, Any],
    members: Iterable[dict[str, Any]] | None,
    owner_names: Iterable[str] = (),
) -> bool:
    """Whether this is a grown-up's own week rather than a child's.

    The person's work hours, the partner's shift, the evening class one of
    them goes to: these are kept in the same week because they say when that
    grown-up cannot do a pickup, but nobody takes a grown-up anywhere and
    nobody collects them. An activity is theirs when everyone it is for is
    the account holder ("me") or someone in the family who is not a child; a
    name nobody knows is taken to be a child's, so the asking carries on.
    """

    who = [name for name in (activity.get("who") or ()) if name_key(name)]
    if not who:
        return False
    adults = grown_up_names(members)
    return all(is_self(name, owner_names) or name_key(name) in adults for name in who)


def own_week_gaps(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
    *,
    calendar_connected: bool = False,
    owner_names: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Whether the person has been asked about their own week yet.

    Once the children are placed, the question that tells the pickups apart
    is the parent's own: when they work, and the regular things of their
    week, which is when they cannot be the one collecting. Nothing of it is
    in the week until they put it there - or until their calendar is
    connected, which holds the same answer and is offered as the other way
    to give it. Like the afternoons, this is a question and never a hole: a
    "no thanks" is a whole answer, so it never makes the week unready.
    """

    if calendar_connected:
        return []
    owners = list(owner_names)
    for activity in activities or ():
        if any(is_self(name, owners) for name in (activity.get("who") or ())):
            return []
    if not any(name_key(member.get("name")) for member in members or ()):
        return []
    return [{"missing": "own_week", "who": "me"}]


def activity_gaps(
    activity: dict[str, Any],
    members: Iterable[dict[str, Any]] | None = None,
    owner_names: Iterable[str] = (),
) -> list[str]:
    """What an activity still has nobody down for.

    With the family given, a grown-up's own week has no gaps: nobody is
    down to collect them, and nobody should be."""

    if members is not None and is_grown_up_activity(activity, members, owner_names):
        return []
    gaps = []
    if not clean(activity.get("dropOffBy")):
        gaps.append("drop_off")
    if not clean(activity.get("pickUpBy")):
        gaps.append("pick_up")
    return gaps


DRIVE_LEGS = ("drop_off", "pick_up")
_LEG_KEYS = {"drop_off": ("dropOffBy", "startTime"), "pick_up": ("pickUpBy", "endTime")}
_LEG_WORDS = {"dropoff": "drop_off", "drop_off": "drop_off", "pickup": "pick_up", "pick_up": "pick_up", "collect": "pick_up", "take": "drop_off"}


def normalize_legs(values: Iterable[Any] | None) -> list[str]:
    """The legs of a drive, as code names: drop_off and pick_up, in that
    order, however they were spelt."""

    found = []
    for value in values or ():
        key = _LEG_WORDS.get(clean(value).lower().replace("-", "_").replace(" ", "_"))
        if key and key not in found:
            found.append(key)
    return [leg for leg in DRIVE_LEGS if leg in found]


def own_work_hours(
    activities: Iterable[dict[str, Any]] | None,
    members: Iterable[dict[str, Any]] | None,
    owner_names: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """The account holder's own week - the grown-up activities that are
    theirs, with a start and an end - which is when they are not free to
    drive. The partner's hours are not here: they say when the partner is
    busy, not the person."""

    owners = list(owner_names)
    hours = []
    for activity in activities or ():
        if not is_grown_up_activity(activity, members, owners):
            continue
        if not any(is_self(name, owners) for name in (activity.get("who") or ())):
            continue
        if normalize_time(activity.get("startTime")) and normalize_time(activity.get("endTime")):
            hours.append(activity)
    return hours


def drives_during_work(
    activities: Iterable[dict[str, Any]] | None,
    members: Iterable[dict[str, Any]] | None,
    owner_names: Iterable[str] = (),
    *,
    day: date | None = None,
    include_accepted: bool = False,
) -> list[dict[str, Any]]:
    """The drives the account holder is down for that fall inside their own
    work hours - a pickup at 13:30 on a day they work 09:00-17:00.

    Both come from the same week, so this is a question the week can ask
    itself, and it is asked the evening before and again in the morning
    until it is settled. Settled is one of two things: somebody else is put
    down for the drive, or the person says it is fine as it is - they work
    round the corner, or leave early that day - which is kept on the
    activity (fineDuringWork) so it is never raised again. The hours' ends
    are not inside: a pickup when work finishes is their drive home.

    day narrows it to one weekday; otherwise every day the two share.
    Each record is one drive: the activity, its leg, the clock, the work it
    falls inside, and the days it does.
    """

    owners = list(owner_names)
    work = own_work_hours(activities, members, owners)
    if not work:
        return []
    wanted = weekday_code(day) if day is not None else None
    found = []
    for activity in activities or ():
        if is_grown_up_activity(activity, members, owners):
            continue
        accepted = set(normalize_legs(activity.get("fineDuringWork")))
        for leg in DRIVE_LEGS:
            who_key, time_key = _LEG_KEYS[leg]
            if not is_self(activity.get(who_key), owners):
                continue
            if leg in accepted and not include_accepted:
                continue
            clock = normalize_time(activity.get(time_key))
            if not clock:
                continue
            days = [code for code in (activity.get("days") or ()) if wanted is None or code == wanted]
            for hours in work:
                shared = [code for code in days if code in (hours.get("days") or ())]
                if not shared:
                    continue
                if normalize_time(hours["startTime"]) < clock < normalize_time(hours["endTime"]):
                    found.append({
                        "activity": activity, "leg": leg, "at": clock, "work": hours,
                        "days": [code for code in WEEKDAY_CODES if code in shared],
                        "accepted": leg in accepted,
                    })
    return found


def describe_work_hours(hours: dict[str, Any]) -> str:
    """A grown-up's hours as a few words: "Work at the office 09:00-17:00"."""

    place = clean(hours.get("place"))
    return f"{clean(hours.get('title'), MAX_TITLE_LENGTH)}{' at ' + place if place else ''} {hours.get('startTime')}-{hours.get('endTime')}"


# What a week has to hold before it can be run for a family. The point of
# the week is the afternoons: a child ends somewhere at a time, and somebody
# has to be there. So a child nobody has told us anything about, an activity
# with no day or no finishing time, and above all a pickup with nobody down
# for it are each something still to ask about - in that order, because a
# person answers the big thing before the small one. "afternoons" and
# "own_week" sit among them without being one of them: see afternoon_gaps
# and own_week_gaps. The parent's own week comes last, once the children's
# are in, because that is when the pickups it bears on are known.
WEEK_GAP_KINDS = ("people", "week", "days", "times", "afternoons", "drop_off", "pick_up", "own_week")


def _activity_time(activity: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = clean(activity.get(key))
        if value:
            return value
    return ""


def week_setup_gaps(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """What the week still needs before it can be looked after, in ask order.

    Each gap says what is missing and who or what it is about, so the
    assistant asks the next real question instead of deciding for itself that
    it knows enough. An empty list is a week that is ready: every child has
    their days, and every one of those days has someone down for the pickup.
    """

    people = [member for member in (members or ()) if clean(member.get("name"), MAX_NAME_LENGTH)]
    week = list(activities or ())
    gaps: list[dict[str, Any]] = []
    if not people:
        return [{"missing": "people"}]

    spoken_for = {name_key(name) for activity in week for name in (activity.get("who") or ())}
    for member in people:
        if normalize_role(member.get("role")) != "child":
            continue
        name = clean(member.get("name"), MAX_NAME_LENGTH)
        if name_key(name) not in spoken_for:
            gaps.append({"missing": "week", "who": name})

    for activity in week:
        title = clean(activity.get("title"), MAX_TITLE_LENGTH)
        where = {"activity": title}
        if activity.get("id"):
            where["id"] = activity["id"]
        if not list(activity.get("days") or ()):
            gaps.append({"missing": "days", **where})
        if not _activity_time(activity, "end", "endTime"):
            gaps.append({"missing": "times", **where})
        for missing in activity_gaps({
            "who": activity.get("who") or (),
            "dropOffBy": _activity_time(activity, "dropOffBy"),
            "pickUpBy": _activity_time(activity, "pickUpBy"),
        }, people):
            gaps.append({"missing": missing, **where})

    return in_ask_order(gaps)


def in_ask_order(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The gaps sorted the way a person answers them: the big thing first."""

    order = {kind: index for index, kind in enumerate(WEEK_GAP_KINDS)}
    return sorted(gaps, key=lambda gap: order.get(str(gap.get("missing")), len(WEEK_GAP_KINDS)))


def afternoon_gaps(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """The children whose week holds one thing and nothing after it.

    School is the first answer a family gives and the easy half of the week:
    it is the same every day and it ends early. The hard half is what comes
    after it - the club on Tuesdays, the swimming on Thursdays, each in a
    different place with a different person driving - and a family who has
    just answered the school question has not been asked that one yet. So a
    child with a single thing in their week is a question still to put,
    rather than a week that is finished.

    This is the one gap that can be answered with "nothing", which is why it
    never makes a week unready: it is asked while the family is being got to
    know, and it is closed by the asking rather than by what comes back.
    """

    week = list(activities or ())
    gaps: list[dict[str, Any]] = []
    for member in members or ():
        if normalize_role(member.get("role")) != "child":
            continue
        name = clean(member.get("name"), MAX_NAME_LENGTH)
        if not name:
            continue
        theirs = [
            activity
            for activity in week
            if name_key(name) in {name_key(who) for who in (activity.get("who") or ())}
        ]
        if len(theirs) != 1:
            continue
        gap = {"missing": "afternoons", "who": name}
        after = clean(theirs[0].get("title"), MAX_TITLE_LENGTH)
        if after:
            gap["after"] = after
        gaps.append(gap)
    return gaps


def week_is_ready(
    members: Iterable[dict[str, Any]] | None,
    activities: Iterable[dict[str, Any]] | None,
) -> bool:
    """Whether the week can be run: everyone placed, and every pickup taken."""

    return not week_setup_gaps(members, activities)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def describe_household(
    *,
    profile: dict[str, Any] | None,
    members: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    today: date,
    group_name: str = "",
    calendar: list[dict[str, Any]] | None = None,
    calendar_connected: bool = False,
    owner_names: Iterable[str] = (),
) -> dict[str, Any]:
    """The family as the assistant reads it on every turn.

    group_name makes it a group's week rather than an account's: the same
    people and the same days, with nothing of the account on it - no kind of
    account and no getting to know, because a group is not an account and
    what it keeps belongs to everyone in the room.

    calendar is what the school calendar says about today or tomorrow where
    they live, for a day that is not an ordinary one: the week is the usual
    week, and this is what says a holiday has closed the school.

    calendar_connected says their own calendar is in, which answers the
    question of their own week without them typing it out. owner_names is
    what the account holder is called, so a week saved under their name
    rather than as "me" is still read as theirs.
    """

    profile = profile or {}
    owners = [name for name in owner_names if clean(name)]
    # A drive of theirs inside their own work hours, still to settle: said
    # on the activity so a "that's fine" in the conversation can be kept.
    during_work: dict[int, dict[str, Any]] = {}
    if not group_name:
        for found in drives_during_work(activities, members, owners):
            during_work.setdefault(int(found["activity"].get("id") or 0), {})[found["leg"]] = {
                "at": found["at"], "inside": describe_work_hours(found["work"]), "days": found["days"],
            }
    described: dict[str, Any] = {} if group_name else {
        "accountKind": normalize_account_kind(profile.get("accountKind")),
        "gettingToKnow": {
            "status": clean(profile.get("gettingToKnow")) or "not_started",
            "askAgainOn": clean(profile.get("askAgainOn")) or None,
        },
    }
    if group_name:
        described["forGroup"] = clean(group_name, MAX_NAME_LENGTH)
    described.update({
        "members": [
            {
                key: value
                for key, value in {
                    "name": member.get("name"),
                    "role": member.get("role"),
                    "age": current_age(member.get("age"), member.get("ageNotedOn"), today, member.get("birthday")),
                    "birthday": member.get("birthday") or None,
                    "nextBirthday": _iso(next_birthday(member.get("birthday"), today)),
                    "school": member.get("school") or None,
                    "email": member.get("email") or None,
                    "phone": member.get("phone") or None,
                    "notes": member.get("notes") or None,
                    "onWhatsApp": True if member.get("waId") else None,
                }.items()
                if value not in (None, "")
            }
            for member in members
        ],
        "week": [
            {
                key: value
                for key, value in {
                    "id": activity.get("id"),
                    "title": activity.get("title"),
                    "who": activity.get("who") or None,
                    "days": activity.get("days"),
                    "start": activity.get("startTime") or None,
                    "end": activity.get("endTime") or None,
                    "place": activity.get("place") or None,
                    "dropOffBy": activity.get("dropOffBy") or None,
                    "pickUpBy": activity.get("pickUpBy") or None,
                    "notes": activity.get("notes") or None,
                    "grownUp": is_grown_up_activity(activity, members, owners) or None,
                    "nobodyDownFor": activity_gaps(activity, members, owners) or None,
                    "fineDuringWork": normalize_legs(activity.get("fineDuringWork")) or None,
                    "driveDuringWork": during_work.get(int(activity.get("id") or 0)) or None,
                }.items()
                if value not in (None, "", [], {})
            }
            for activity in activities
        ],
    })
    gaps = week_setup_gaps(members, activities)
    # weekReady is whether the week can be run, and neither the afternoons
    # question nor the one about the parent's own week bears on that: a
    # family who says there is nothing after school, or who would rather not
    # put their work hours in, has a whole week. They travel with the gaps
    # only while the family is still being got to know, so each is asked
    # once and never becomes a nag - and never in a group, whose week is
    # kept between adults who already know their own afternoons.
    described["weekReady"] = not gaps
    still_asking = not group_name and clean(profile.get("gettingToKnow")).lower() != "done"
    if still_asking:
        gaps = in_ask_order(
            gaps
            + afternoon_gaps(members, activities)
            + own_week_gaps(members, activities, calendar_connected=calendar_connected, owner_names=owners)
        )
    if gaps:
        described["weekGaps"] = gaps
    if calendar:
        described["calendar"] = list(calendar)
    return described


def should_describe_household(profile: dict[str, Any] | None, members: list[Any], activities: list[Any]) -> bool:
    """A family account always has the block; any other account once it
    keeps someone or something, so a business owner's partner is known too."""

    return normalize_account_kind((profile or {}).get("accountKind")) == "family" or bool(members) or bool(activities)


__all__ = [
    "ACCOUNT_KINDS",
    "GETTING_TO_KNOW_STATUSES",
    "INVITE_TTL_DAYS",
    "MEMBER_THREAD_PREFIX",
    "WEEK_EDITOR_ROLES",
    "can_change_week",
    "describe_speaker",
    "invite_candidates",
    "is_named",
    "member_nudges",
    "member_thread_id",
    "MAX_ACTIVITIES",
    "MAX_MEMBERS",
    "MEMBER_ROLES",
    "WEEKDAY_CODES",
    "BIRTHDAY_LIST_TEMPLATES",
    "BIRTHDAY_REMINDER_DAYS",
    "activity_gaps",
    "afternoon_gaps",
    "age_from_birthday",
    "birthday_list_items",
    "birthday_template_kind",
    "clean",
    "current_age",
    "describe_household",
    "grown_up_names",
    "in_ask_order",
    "is_grown_up_activity",
    "is_self",
    "nobody_drives",
    "name_key",
    "next_birthday",
    "normalize_birthday",
    "normalize_account_kind",
    "normalize_days",
    "normalize_email_address",
    "normalize_role",
    "normalize_time",
    "own_week_gaps",
    "should_describe_household",
    "weekday_code",
    "week_is_ready",
    "week_setup_gaps",
    "WEEK_GAP_KINDS",
]
