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
    after: date | None = None
    before: date | None = None
    newer_than_days: int | None = None
    in_inbox: bool = False
    has_attachment: bool = False

    def is_empty(self) -> bool:
        return not (
            self.terms
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


def to_gmail_query(query: MailQuery) -> str:
    """Render the intent as a Gmail search string.

    The clause order here is the order the portal has always written, so an
    action that ran against Gmail before keeps sending Gmail the same string.
    """

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
    if query.terms:
        parts.append(f"({' OR '.join(query.terms)})")
    return " ".join(parts)[:MAIL_QUERY_MAX_LENGTH]


def to_graph_search(query: MailQuery, *, today: date | None = None) -> str:
    """Render the intent as a Microsoft Graph KQL ``$search`` string.

    Graph refuses ``$search`` and ``$filter`` together on messages, so the date
    window has to travel inside the KQL. ``matches`` re-checks the window on
    what comes back, so a provider that reads the range loosely cannot widen
    the result.
    """

    clauses: list[str] = []
    if query.terms:
        quoted = " OR ".join(f'"{term}"' for term in query.terms)
        clauses.append(f"({quoted})" if len(query.terms) > 1 else quoted)

    after, before = resolve_window(query, today=today)
    if after:
        clauses.append(f"received>={after.isoformat()}")
    if before:
        clauses.append(f"received<{before.isoformat()}")
    if query.has_attachment:
        clauses.append("hasattachment:true")
    return " AND ".join(clauses)[:MAIL_QUERY_MAX_LENGTH]


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


def build_query(
    *,
    terms: Any = (),
    after: date | None = None,
    before: date | None = None,
    newer_than_days: int | None = None,
    in_inbox: bool = False,
    has_attachment: bool = False,
) -> MailQuery:
    return MailQuery(
        terms=normalize_terms(terms),
        after=after,
        before=before,
        newer_than_days=newer_than_days,
        in_inbox=in_inbox,
        has_attachment=has_attachment,
    )


DEFAULT_DIGEST_QUERY = MailQuery(in_inbox=True, newer_than_days=1)
