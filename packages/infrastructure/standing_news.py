"""What counts as new for a recurring news task.

A news task that runs every morning should bring what happened since the
last message, once. Two things decide it, both in code:

- the window: the search asks only for items published or updated since the
  run that last delivered (or, on the first run, one schedule period back),
  and an item whose date is readable and earlier than that is dropped;
- the ledger: every item a delivered run sent is written down against the
  task, and an item already there is never sent again, however the article
  was reworded or updated.

When a run finds nothing new it sends nothing. The ledger is written only
after the message is delivered, so a run that fails to send does not use up
the items it found.
"""

from __future__ import annotations

import re
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

# How far back the first run of a task looks, by how often it runs.
FIRST_RUN_LOOKBACK = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=31)}

_DATE_FORMATS = (
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
)


def _as_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def news_window_start(action: dict[str, Any], *, now: datetime) -> datetime:
    """Where this run's news starts: the last delivered run, else one period back."""

    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    covered = _as_utc(payload.get("newsCoveredUntil"))
    if covered is not None:
        return covered
    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    lookback = FIRST_RUN_LOOKBACK.get(str(schedule.get("frequency") or "").lower(), timedelta(days=1))
    return now.astimezone(timezone.utc) - lookback


def describe_window(since: datetime, timezone_name: str) -> str:
    """The window in words a search understands, in the person's own clock."""

    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = since.astimezone(zone)
    return f"published or updated after {local.strftime('%Y-%m-%d %H:%M')} ({zone.key}), up to now"


def parse_item_date(value: Any) -> date | None:
    """The day an item is dated, when the text says it plainly enough; None otherwise."""

    text = " ".join(str(value or "").split())
    if not text:
        return None
    iso = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def item_fingerprints(item: dict[str, Any]) -> list[str]:
    """The keys an item is remembered by: its page, and its title.

    Either one already sent is enough to hold it back, so the same article
    retitled, or the same headline at a moved address, does not come twice.
    """

    keys: list[str] = []
    url = str(item.get("sourceUrl") or "").strip()
    if url:
        parts = urlsplit(url)
        host = parts.netloc.lower().removeprefix("www.")
        path = parts.path.rstrip("/")
        if host:
            keys.append(f"url:{host}{path}")
    title = " ".join(re.sub(r"[^\w\s]", " ", str(item.get("title") or "").casefold()).split())
    if title:
        keys.append(f"title:{title}")
    return keys


def select_new_items(
    items: list[dict[str, Any]],
    *,
    since: datetime,
    seen: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The items that are new: dated no earlier than the window's first day, and never sent.

    An item whose date cannot be read is kept on the date and judged by the
    ledger alone; the search was already asked for the window. Returns the
    new items and how many were held back for each reason.
    """

    first_day = since.astimezone(timezone.utc).date()
    kept: list[dict[str, Any]] = []
    held = {"older": 0, "alreadySent": 0}
    taken: set[str] = set()
    for item in items:
        day = parse_item_date(item.get("date"))
        if day is not None and day < first_day:
            held["older"] += 1
            continue
        keys = item_fingerprints(item)
        if any(key in seen or key in taken for key in keys):
            held["alreadySent"] += 1
            continue
        taken.update(keys)
        kept.append(item)
    return kept, held


__all__ = [
    "FIRST_RUN_LOOKBACK",
    "describe_window",
    "item_fingerprints",
    "news_window_start",
    "parse_item_date",
    "select_new_items",
]
