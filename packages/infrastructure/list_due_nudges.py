"""The morning nudge about to-do items with a deadline.

A due date on an item is a promise the person made to themselves; this is
the part that keeps it. Once a day, after the nudge hour where the person
is, every account with an unticked dated item that is due today, due
tomorrow, or overdue gets one message saying so. It goes out as a scheduled
message, so it reaches WhatsApp when that is set up and the in-app feed
otherwise, with the same fallback the rest of the scheduled messages have.

One nudge per account per local day, claimed in the database before the
message is queued, so two polls or two workers cannot send it twice.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.whatsapp_agent_chat import infer_timezone_from_wa_id

DEFAULT_NUDGE_HOUR = 8
DEFAULT_NUDGE_POLL_SECONDS = 300
NUDGE_SOURCE = "list_due_nudge"
MAX_ITEMS_PER_BUCKET = 15


@dataclass(frozen=True)
class ListDueNudgeConfig:
    enabled: bool = True
    hour: int = DEFAULT_NUDGE_HOUR
    poll_seconds: int = DEFAULT_NUDGE_POLL_SECONDS


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(normalize_text(value) or default)
    except (TypeError, ValueError):
        return default


def load_list_due_nudge_config() -> ListDueNudgeConfig:
    enabled_text = normalize_text(os.getenv("PORTAL_LIST_NUDGES_ENABLED")).lower()
    return ListDueNudgeConfig(
        enabled=enabled_text not in {"0", "false", "no", "off", "disabled"},
        hour=min(23, max(0, _parse_int(os.getenv("PORTAL_LIST_NUDGE_HOUR"), DEFAULT_NUDGE_HOUR))),
        poll_seconds=max(30, _parse_int(os.getenv("PORTAL_LIST_NUDGE_POLL_SECONDS"), DEFAULT_NUDGE_POLL_SECONDS)),
    )


def parse_due_on(value: Any) -> date | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def describe_due(due_on: Any, today: date | None = None) -> str:
    """A deadline in words a person would use: today, tomorrow, Mon 15 Sep,
    or how late it is."""

    due = parse_due_on(due_on)
    if due is None:
        return ""
    reference = today or date.today()
    days = (due - reference).days
    if days == 0:
        return "due today"
    if days == 1:
        return "due tomorrow"
    if days < 0:
        late = -days
        return f"{late} day{'s' if late != 1 else ''} overdue"
    if days < 7:
        return f"due {due.strftime('%A')}"
    return f"due {due.strftime('%a %-d %b')}"


def bucket_due_items(items: list[dict[str, Any]], today: date) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {"overdue": [], "today": [], "tomorrow": []}
    for item in items:
        due = parse_due_on(item.get("dueOn"))
        if due is None:
            continue
        if due < today:
            buckets["overdue"].append(item)
        elif due == today:
            buckets["today"].append(item)
        elif due == today + timedelta(days=1):
            buckets["tomorrow"].append(item)
    return buckets


def build_due_nudge_text(buckets: dict[str, list[dict[str, Any]]], today: date) -> str:
    """The nudge as lines of text. Empty when there is nothing to say."""

    lines: list[str] = []
    headings = (("today", "Due today"), ("tomorrow", "Due tomorrow"), ("overdue", "Overdue"))
    for key, heading in headings:
        entries = buckets.get(key) or []
        if not entries:
            continue
        if lines:
            lines.append("")
        lines.append(f"{heading}:")
        for item in entries[:MAX_ITEMS_PER_BUCKET]:
            text = normalize_text(item.get("text"))
            list_name = normalize_text(item.get("listName"))
            suffix = f" ({list_name})" if list_name else ""
            if key == "overdue":
                suffix += f" - {describe_due(item.get('dueOn'), today)}"
            lines.append(f"• {text}{suffix}")
        if len(entries) > MAX_ITEMS_PER_BUCKET:
            lines.append(f"…and {len(entries) - MAX_ITEMS_PER_BUCKET} more")
    return "\n".join(lines)


class ListDueNudger:
    def __init__(self, database: PortalDatabase, *, config: ListDueNudgeConfig | None = None) -> None:
        self.database = database
        self.config = config or load_list_due_nudge_config()

    def _timezone_for_user(self, user_id: int) -> str:
        """Where the person is: from their WhatsApp number, else from the
        last message they scheduled, else UTC."""

        try:
            connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        except Exception:  # noqa: BLE001
            connection = {}
        wa_id = normalize_text(connection.get("ownerWaId"))
        if wa_id:
            inferred = infer_timezone_from_wa_id(wa_id)
            if inferred and inferred != "UTC":
                return inferred
        try:
            actions = self.database.list_scheduled_actions_for_user(user_id, limit=1)
        except Exception:  # noqa: BLE001
            actions = []
        for action in actions:
            name = normalize_text(action.get("timezone"))
            if name:
                return name
        return "UTC"

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        by_user: dict[int, list[dict[str, Any]]] = {}
        for item in self.database.list_open_due_items():
            by_user.setdefault(int(item.get("userId") or 0), []).append(item)

        queued = 0
        skipped = 0
        for user_id, items in by_user.items():
            if user_id <= 0:
                continue
            timezone_name = self._timezone_for_user(user_id)
            try:
                zone = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                zone = ZoneInfo("UTC")
                timezone_name = "UTC"
            local_now = reference.astimezone(zone)
            if local_now.hour < self.config.hour:
                continue
            today = local_now.date()
            buckets = bucket_due_items(items, today)
            text = build_due_nudge_text(buckets, today)
            if not text:
                continue
            if not self.database.record_list_nudge(user_id=user_id, local_date=today.isoformat()):
                skipped += 1
                continue
            connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
            channel = "whatsapp" if normalize_text(connection.get("ownerWaId")) else "portal"
            self.database.create_scheduled_action(
                user_id=user_id,
                action_type="send_message",
                channel=channel,
                recipient_ref="owner",
                run_at=reference,
                timezone_name=timezone_name,
                payload={
                    "messageText": text,
                    "title": "Your to-dos for today",
                    "source": NUDGE_SOURCE,
                    "localDate": today.isoformat(),
                },
            )
            queued += 1
        return {"ok": True, "accounts": len(by_user), "queued": queued, "skipped": skipped}

    def serve_forever(self, stop_event: threading.Event, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                summary = self.run_pending()
                if int(summary.get("queued") or 0) > 0:
                    logger(f"[list-nudges] queued={summary.get('queued')} accounts={summary.get('accounts')}")
            except Exception as exc:  # noqa: BLE001 - keep the nudger alive
                logger(f"[list-nudges] error: {exc}")
            stop_event.wait(max(30, int(self.config.poll_seconds)))


__all__ = [
    "DEFAULT_NUDGE_HOUR",
    "ListDueNudgeConfig",
    "ListDueNudger",
    "build_due_nudge_text",
    "bucket_due_items",
    "describe_due",
    "load_list_due_nudge_config",
    "parse_due_on",
]
