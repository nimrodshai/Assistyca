"""Provider-neutral mail search intent shared by the Gmail and Outlook readers.

Gmail and Microsoft Graph do not speak the same search language, so a saved
action cannot carry a provider query string around any more. It carries the
intent - a date window, some words, whether an attachment is required - and
each reader renders that into its own dialect.

Actions saved before Outlook support stored a raw Gmail query in their fields.
``parse_gmail_query`` reads those back into the neutral shape so an action
written against Gmail keeps working when the mailbox behind it is Outlook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

MAIL_QUERY_MAX_LENGTH = 200
MAIL_QUERY_MAX_TERMS = 12

_GMAIL_DATE_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")
_GMAIL_NEWER_THAN_RE = re.compile(r"^(\d{1,4})d$", re.IGNORECASE)
# Keep letters from any alphabet (clients write Hebrew subjects), drop syntax.
_TERM_SAFE_RE = re.compile(r"[^\w .@-]+", re.UNICODE)


@dataclass(frozen=True)
class MailQuery:
    """What to look for in a mailbox, with no provider syntax attached."""

    terms: tuple[str, ...] = ()
    # Words every message must carry, rather than one of. A question about one
    # vendor searches for that vendor at the provider instead of reading the
    # newest messages of the month and dropping the ones that do not match.
    required_terms: tuple[str, ...] = ()
    after: date | None = None
    before: date | None = None
    newer_than_days: int | None = None
    in_inbox: bool = False
    has_attachment: bool = False

    def is_empty(self) -> bool:
        return not (
            self.terms
            or self.required_terms
            or self.after
            or self.before
            or self.newer_than_days
            or self.in_inbox
            or self.has_attachment
        )

    def describe(self) -> str:
        """A short human sentence, for messages that used to show the raw query."""

        parts: list[str] = []
        if self.terms:
            parts.append(" or ".join(self.terms))
        else:
            parts.append("messages")
        if self.required_terms:
            parts.append("mentioning " + " and ".join(self.required_terms))
        if self.after and self.before:
            parts.append(f"between {self.after.isoformat()} and {self.before.isoformat()}")
        elif self.after:
            parts.append(f"since {self.after.isoformat()}")
        elif self.before:
            parts.append(f"before {self.before.isoformat()}")
        elif self.newer_than_days:
            day_word = "day" if self.newer_than_days == 1 else "days"
            parts.append(f"from the last {self.newer_than_days} {day_word}")
        if self.has_attachment:
            parts.append("with an attachment")
        if self.in_inbox:
            parts.append("in the inbox")
        return " ".join(parts)


def _clean_term(value: Any) -> str:
    term = _TERM_SAFE_RE.sub(" ", str(value or "")).strip()
    return re.sub(r"\s+", " ", term)[:60]


def normalize_terms(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return ()
    seen: list[str] = []
    for value in values:
        term = _clean_term(value)
        if term and term.lower() not in {existing.lower() for existing in seen}:
            seen.append(term)
        if len(seen) >= MAIL_QUERY_MAX_TERMS:
            break
    return tuple(seen)


def _parse_gmail_date(value: str) -> date | None:
    match = _GMAIL_DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _format_gmail_date(value: date) -> str:
    return f"{value.year:04d}/{value.month:02d}/{value.day:02d}"


def parse_gmail_query(text: Any) -> MailQuery:
    """Read a Gmail search string back into the neutral shape.

    This understands the subset the portal itself writes - ``in:inbox``,
    ``newer_than:31d``, ``after:``/``before:``, ``has:attachment`` and a
    parenthesised OR list of words. Anything else in the string is kept as a
    plain search term rather than dropped, so a hand-written query still
    narrows the search instead of silently matching everything.
    """

    raw = str(text or "").strip()
    if not raw:
        return MailQuery()

    after: date | None = None
    before: date | None = None
    newer_than_days: int | None = None
    in_inbox = False
    has_attachment = False
    terms: list[str] = []

    # Words inside parentheses are the OR list the portal writes for receipts.
    for group in re.findall(r"\(([^)]*)\)", raw):
        for candidate in re.split(r"\bOR\b|\|", group, flags=re.IGNORECASE):
            term = _clean_term(candidate)
            if term:
                terms.append(term)
    remainder = re.sub(r"\([^)]*\)", " ", raw)

    for token in re.split(r"\s+", remainder):
        token = token.strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in {"or", "and"}:
            continue
        if lowered == "in:inbox":
            in_inbox = True
            continue
        if lowered in {"has:attachment", "has:attachments"}:
            has_attachment = True
            continue
        if lowered.startswith("after:"):
            after = _parse_gmail_date(token[6:]) or after
            continue
        if lowered.startswith("before:"):
            before = _parse_gmail_date(token[7:]) or before
            continue
        if lowered.startswith("newer_than:"):
            match = _GMAIL_NEWER_THAN_RE.match(token[11:])
            if match:
                newer_than_days = max(1, min(3650, int(match.group(1))))
            continue
        if ":" in lowered:
            # An operator this portal does not model (label:, from:, ...). Keep
            # its value as a search word so the search still narrows.
            token = token.split(":", 1)[1]
        term = _clean_term(token)
        if term:
            terms.append(term)

    return MailQuery(
        terms=normalize_terms(terms),
        after=after,
        before=before,
        newer_than_days=newer_than_days,
        in_inbox=in_inbox,
        has_attachment=has_attachment,
    )


def _fit_query(render: Any, terms: tuple[str, ...]) -> str:
    """Render a query, dropping OR-terms from the end until it fits.

    A query is a sentence the provider parses, so cutting it mid-word is worse
    than asking for less: "(receipt OR invo" is not a narrower search, it is a
    broken one, and an unclosed bracket can cost the whole month's results.
    Only the OR-terms are given up, and the widest ones last: the date window
    and anything the caller required stay, because dropping those would widen
    the search rather than narrow it.
    """

    kept = list(terms)
    while True:
        rendered = render(tuple(kept))
        if len(rendered) <= MAIL_QUERY_MAX_LENGTH or not kept:
            # A required term long enough to overflow on its own is still cut
            # here, which is the behaviour this has always had.
            return rendered[:MAIL_QUERY_MAX_LENGTH]
        kept.pop()


def to_gmail_query(query: MailQuery) -> str:
    """Render the intent as a Gmail search string.

    The clause order here is the order the portal has always written, so an
    action that ran against Gmail before keeps sending Gmail the same string.
    """

    def render(terms: tuple[str, ...]) -> str:
        parts: list[str] = []
        if query.in_inbox:
            parts.append("in:inbox")
        if query.after:
            parts.append(f"after:{_format_gmail_date(query.after)}")
        if query.before:
            parts.append(f"before:{_format_gmail_date(query.before)}")
        if query.newer_than_days and not (query.after or query.before):
            parts.append(f"newer_than:{query.newer_than_days}d")
        if query.has_attachment:
            parts.append("has:attachment")
        if terms:
            parts.append(f"({' OR '.join(terms)})")
        # Gmail ANDs bare words, which is exactly what a required term means.
        for term in query.required_terms:
            parts.append(f'"{term}"' if " " in term else term)
        return " ".join(parts)

    return _fit_query(render, query.terms)


def to_graph_search(query: MailQuery, *, today: date | None = None) -> str:
    """Render the intent as a Microsoft Graph KQL ``$search`` string.

    Graph refuses ``$search`` and ``$filter`` together on messages, so the date
    window has to travel inside the KQL. ``matches`` re-checks the window on
    what comes back, so a provider that reads the range loosely cannot widen
    the result.
    """

    def render(terms: tuple[str, ...]) -> str:
        clauses: list[str] = []
        if terms:
            quoted = " OR ".join(f'"{term}"' for term in terms)
            clauses.append(f"({quoted})" if len(terms) > 1 else quoted)
        for term in query.required_terms:
            clauses.append(f'"{term}"')

        after, before = resolve_window(query, today=today)
        if after:
            clauses.append(f"received>={after.isoformat()}")
        if before:
            clauses.append(f"received<{before.isoformat()}")
        if query.has_attachment:
            clauses.append("hasattachment:true")
        return " AND ".join(clauses)

    return _fit_query(render, query.terms)


def resolve_window(
    query: MailQuery,
    *,
    today: date | None = None,
) -> tuple[date | None, date | None]:
    """Turn the query's dates into a concrete ``[after, before)`` window."""

    reference = today or datetime.now(timezone.utc).date()
    after = query.after
    before = query.before
    if after is None and before is None and query.newer_than_days:
        after = reference - timedelta(days=query.newer_than_days)
    return after, before


def matches(
    query: MailQuery,
    *,
    received: datetime | None = None,
    subject: str = "",
    sender: str = "",
    snippet: str = "",
    has_attachment: bool | None = None,
    today: date | None = None,
) -> bool:
    """Check one message against the intent.

    Gmail applies the whole query itself. Graph is asked for the same thing,
    but its KQL date handling is looser than Gmail's operators, so the reader
    runs every message back through this before it counts.
    """

    after, before = resolve_window(query, today=today)
    if received is not None and (after or before):
        received_date = received.astimezone(timezone.utc).date() if received.tzinfo else received.date()
        if after and received_date < after:
            return False
        if before and received_date >= before:
            return False
    if query.has_attachment and has_attachment is False:
        return False
    if query.terms:
        haystack = " ".join([str(subject or ""), str(sender or ""), str(snippet or "")]).lower()
        if not any(term.lower() in haystack for term in query.terms):
            return False
    return True


def month_window(year: int, month: int) -> MailQuery:
    """The receipts window: one whole calendar month."""

    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month >= 12 else date(year, month + 1, 1)
    return MailQuery(after=start, before=end)


def month_span_window(months: list[tuple[int, int]]) -> MailQuery:
    """One window covering every month in the list, oldest to newest.

    Asking a mailbox once for a run of months costs one search instead of one
    per month. The months are still counted apart afterwards; only the reading
    is shared.
    """

    ordered = sorted(months)
    if not ordered:
        return MailQuery()
    return MailQuery(
        after=month_window(*ordered[0]).after,
        before=month_window(*ordered[-1]).before,
    )


def widen_query(query: MailQuery) -> MailQuery | None:
    """The same search, asked less narrowly, or None when there is no wider one.

    A receipt does not have to say "receipt". Vendors send "Your Render
    statement", "Payment confirmation", "Thanks for your order", and a search
    built from the words a receipt usually carries comes back with nothing at
    all - which reads, to the person who asked, as "you were never charged".

    Widening drops those topic words and keeps everything that still narrows
    the search: the vendor, and the window it was asked about. That is only
    safe when something is left holding it down, so a search with no required
    term has no wider version - dropping the topic words there would mean
    reading a whole month of mail to answer a question about receipts.
    """

    if not query.required_terms or not query.terms:
        return None
    if not (query.after or query.before or query.newer_than_days):
        # A vendor with no window is every message they ever sent. That is not
        # a wider answer to the question, it is a different question.
        return None
    return MailQuery(
        terms=(),
        required_terms=query.required_terms,
        after=query.after,
        before=query.before,
        newer_than_days=query.newer_than_days,
        in_inbox=query.in_inbox,
        has_attachment=False,
    )


def describe_widening(query: MailQuery) -> str:
    """What was given up, in words the person who asked would use."""

    vendors = " and ".join(query.required_terms)
    if not vendors:
        return ""
    return f"everything from {vendors} in that period, not only the mail that calls itself a receipt"


def build_query(
    *,
    terms: Any = (),
    required_terms: Any = (),
    after: date | None = None,
    before: date | None = None,
    newer_than_days: int | None = None,
    in_inbox: bool = False,
    has_attachment: bool = False,
) -> MailQuery:
    return MailQuery(
        terms=normalize_terms(terms),
        required_terms=normalize_terms(required_terms),
        after=after,
        before=before,
        newer_than_days=newer_than_days,
        in_inbox=in_inbox,
        has_attachment=has_attachment,
    )


DEFAULT_DIGEST_QUERY = MailQuery(in_inbox=True, newer_than_days=1)


# A digest action saves a schedule, not a period, so its default window is the
# day it runs. A question asked in chat names its own period - "this week",
# "the last 3 days" - and reading a day of mail for it answers a question the
# user did not ask. These turn the period back into a number of days.
MAIL_TIME_WINDOW_MAX_DAYS = 366
_TIME_WINDOW_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_TIME_WINDOW_UNIT_DAYS = {
    "day": 1,
    "week": 7,
    "fortnight": 14,
    "month": 31,
    "quarter": 92,
    "year": 365,
}
_TIME_WINDOW_TODAY_RE = re.compile(r"\b(?:today|so far today|last 24 hours|past 24 hours)\b")
_TIME_WINDOW_YESTERDAY_RE = re.compile(r"\byesterday\b")
_TIME_WINDOW_COUNT_RE = re.compile(
    r"(?:(?P<count>\d{1,3}|" + "|".join(_TIME_WINDOW_NUMBER_WORDS) + r")\s+)?"
    r"(?P<unit>" + "|".join(_TIME_WINDOW_UNIT_DAYS) + r")s?\b"
)


def parse_time_window_days(value: Any) -> int | None:
    """Read a period written the way a person says it as a number of days.

    "this week" and "last week" both come back as seven days rather than a
    calendar week. A rolling window is what a mailbox can actually be asked
    for, and it is the reading that never leaves out yesterday's mail.
    Returns None when the text names no period, so the caller keeps its own
    default instead of inventing one.
    """

    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    if not text:
        return None
    if _TIME_WINDOW_TODAY_RE.search(text):
        return 1
    if _TIME_WINDOW_YESTERDAY_RE.search(text):
        return 2
    match = _TIME_WINDOW_COUNT_RE.search(text)
    if not match:
        return None
    raw_count = match.group("count") or ""
    count = int(raw_count) if raw_count.isdigit() else _TIME_WINDOW_NUMBER_WORDS.get(raw_count, 1)
    days = max(1, count) * _TIME_WINDOW_UNIT_DAYS[match.group("unit")]
    return min(days, MAIL_TIME_WINDOW_MAX_DAYS)
