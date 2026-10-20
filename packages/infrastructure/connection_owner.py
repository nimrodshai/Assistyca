"""Whose mail and calendar a request may read.

A family account is several people: the account holder, and a partner or a
grandparent writing from their own phones. The week and the lists are the
family's. Mail and calendars are not: each belongs to whoever connected it,
and nobody else on the account sees what is in it - not the partner the
account holder's, and not the account holder the partner's.

So every connection has an owner - empty for the account holder, a phone for
a family member - and every request that reads one says whose it may read.
The session says which account; it cannot say which person, because the
account holder's own session would then be enough to read the partner's
mail. The person is named in a header signed with the server's secret, and
only the server, acting for a phone that wrote in, signs it. A request
without it reads the account holder's connections; one with a header that
does not verify reads nobody's.

The one thing that crosses from one person to another is when they are busy:
planning who takes a pickup needs it, and nothing else of the calendar does.
busy_blocks is that crossing - start and end, merged, and nothing more.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Iterable
from zoneinfo import ZoneInfo

CONNECTION_VIEWER_HEADER = "X-Assistyca-Viewer"
# Where the other grown-ups' busy times are read, for planning who drives.
FAMILY_BUSY_ENDPOINT = "/api/family-week/busy"
# The longest stretch of someone else's busy times one request reads.
FAMILY_BUSY_MAX_DAYS = 14
# A header value that names nobody: a request carrying it reads no one's
# connections. Sent on when a turn is a family member's but arrived without
# their signed phone, so it never falls back to the account holder's mail.
NOBODY_VIEWER = "nobody"
# The scheduled messages built out of someone's mail: the inbox watch's
# alerts, an answer in a thread they follow, and what a look through their
# mailbox found. Each holds what the mail said, so it is as private as the
# mailbox - listed to, and stopped by, the person whose mailbox it is.
CONNECTION_ACTION_SOURCES = frozenset({"inbox_watch", "thread_follow", "mailbox_findings"})


def _digits(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _mac(secret: str, email: str, number: str) -> str:
    message = f"viewer:{str(email or '').strip().lower()}:{number}".encode("utf-8")
    return hmac.new(str(secret or "").encode("utf-8"), message, hashlib.sha256).hexdigest()[:40]


def sign_connection_viewer(secret: str, email: str, wa_id: Any) -> str:
    """The header value naming this phone as the one asking, on this account."""

    number = _digits(wa_id)
    if not number or not str(secret or ""):
        return ""
    return f"{number}.{_mac(secret, email, number)}"


def read_connection_viewer(secret: str, email: str, value: Any) -> str | None:
    """The phone a header names, or None when it does not verify."""

    text = str(value or "").strip()
    number, _, signature = text.partition(".")
    if not number.isdigit() or not signature or not str(secret or ""):
        return None
    return number if hmac.compare_digest(signature, _mac(secret, email, number)) else None


def action_connection_owner(action: dict[str, Any] | None) -> str | None:
    """Whose connection a scheduled action was built from, as
    connection_owner says it ("" the account holder, else a member's phone),
    or None when it was not built from anyone's mail."""

    payload = (action or {}).get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if str(payload.get("source") or "").strip() not in CONNECTION_ACTION_SOURCES:
        return None
    # Such a message goes to its owner: a member's phone is named on it, and
    # the account holder's carries none.
    return _digits(payload.get("recipientWaId"))


def action_visible_to(action: dict[str, Any] | None, viewer: str) -> bool:
    """Whether the person a request is for (connection_owner) may see and
    stop this scheduled action. The family's own tasks are everyone's; one
    built from mail is only its owner's, and a viewer that did not verify
    owns none."""

    owner = action_connection_owner(action)
    return owner is None or owner == str(viewer or "")


def _moment(value: Any, zone: ZoneInfo, *, all_day: bool) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, datetime.min.time())
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    moment = moment.astimezone(zone)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0) if all_day else moment


def busy_blocks(events: Iterable[dict[str, Any]], zone: ZoneInfo) -> list[dict[str, str]]:
    """When someone is busy, and nothing else: each event reduced to its
    start and end in their own clock, overlapping and touching times merged
    into one block so not even the number of meetings shows. A whole-day
    event is the whole day. Titles, places, attendees and descriptions never
    leave here."""

    spans: list[tuple[datetime, datetime]] = []
    for event in events or ():
        if not isinstance(event, dict):
            continue
        all_day = bool(event.get("allDay"))
        start = _moment(event.get("start"), zone, all_day=all_day)
        end = _moment(event.get("end"), zone, all_day=all_day)
        if start is None:
            continue
        if end is None or end <= start:
            end = start + (timedelta(days=1) if all_day else timedelta(minutes=30))
        spans.append((start, end))
    spans.sort()
    merged: list[list[datetime]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [
        {"start": start.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M")}
        for start, end in merged
    ]


__all__ = ["CONNECTION_ACTION_SOURCES", "CONNECTION_VIEWER_HEADER", "action_connection_owner", "action_visible_to", "FAMILY_BUSY_ENDPOINT", "FAMILY_BUSY_MAX_DAYS", "NOBODY_VIEWER", "busy_blocks", "read_connection_viewer", "sign_connection_viewer"]
