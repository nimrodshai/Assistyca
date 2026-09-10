"""When each inbox is looked at, and how a poll gets to the mailbox.

Every three minutes while the person is awake, every fifteen at night,
each account with a connected mailbox is polled once: the server's own
endpoint is called over loopback with a short-lived session for the
account, the same way a standing action or a mailbox scan runs, so the
credentials stay in the request handler where they live. The endpoint
does the reading and the telling; this thread only keeps time.

An account that fails backs off, doubling up to half an hour, and comes
back on its own. An account whose trial has run out is left alone for
half a day rather than knocked on every three minutes.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from packages.infrastructure.inbox_watch import poll_interval_seconds
from packages.infrastructure.mailbox_finding_scans import account_timezone
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.scheduled_actions import parse_bool_env
from packages.infrastructure.scheduled_actions import parse_int_env

POLL_ENDPOINT = "/api/inbox-watch/poll"
DEFAULT_DAY_POLL_SECONDS = 180
DEFAULT_NIGHT_POLL_SECONDS = 900
DEFAULT_QUIET_START_HOUR = 22
DEFAULT_QUIET_END_HOUR = 7
DEFAULT_HOLD_MINUTES = 10
DEFAULT_DAILY_CAP = 5
DEFAULT_TICK_SECONDS = 30
DEFAULT_BATCH_SIZE = 10
MAX_BACKOFF_SECONDS = 30 * 60
TRIAL_OVER_PAUSE = timedelta(hours=12)
POLL_TIMEOUT_SECONDS = 240


@dataclass(frozen=True)
class InboxWatchConfig:
    enabled: bool = True
    day_poll_seconds: int = DEFAULT_DAY_POLL_SECONDS
    night_poll_seconds: int = DEFAULT_NIGHT_POLL_SECONDS
    quiet_start_hour: int = DEFAULT_QUIET_START_HOUR
    quiet_end_hour: int = DEFAULT_QUIET_END_HOUR
    hold_minutes: int = DEFAULT_HOLD_MINUTES
    daily_cap: int = DEFAULT_DAILY_CAP
    tick_seconds: int = DEFAULT_TICK_SECONDS
    batch_size: int = DEFAULT_BATCH_SIZE


def load_inbox_watch_config() -> InboxWatchConfig:
    def hour(name: str, default: int) -> int:
        return min(23, max(0, parse_int_env(os.getenv(name), default)))

    return InboxWatchConfig(
        enabled=parse_bool_env(os.getenv("PORTAL_INBOX_WATCH_ENABLED"), True),
        day_poll_seconds=max(60, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_DAY_POLL_SECONDS"), DEFAULT_DAY_POLL_SECONDS)),
        night_poll_seconds=max(60, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_NIGHT_POLL_SECONDS"), DEFAULT_NIGHT_POLL_SECONDS)),
        quiet_start_hour=hour("PORTAL_INBOX_WATCH_QUIET_START_HOUR", DEFAULT_QUIET_START_HOUR),
        quiet_end_hour=hour("PORTAL_INBOX_WATCH_QUIET_END_HOUR", DEFAULT_QUIET_END_HOUR),
        hold_minutes=max(0, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_HOLD_MINUTES"), DEFAULT_HOLD_MINUTES)),
        daily_cap=max(1, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_DAILY_CAP"), DEFAULT_DAILY_CAP)),
        tick_seconds=max(10, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_TICK_SECONDS"), DEFAULT_TICK_SECONDS)),
        batch_size=max(1, parse_int_env(os.getenv("PORTAL_INBOX_WATCH_BATCH_SIZE"), DEFAULT_BATCH_SIZE)),
    )


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(normalize_text(timezone_name) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


class TrialOver(RuntimeError):
    """The account's trial has ended; polling it would only cost model calls."""


class InboxWatchScheduler:
    def __init__(
        self,
        database: PortalDatabase,
        *,
        config: InboxWatchConfig | None = None,
        base_url: str = "",
        session_token_factory: Callable[[str], str] | None = None,
        poll: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    ) -> None:
        self.database = database
        self.config = config or load_inbox_watch_config()
        self.base_url = str(base_url or "").rstrip("/")
        self.session_token_factory = session_token_factory
        # How one account is polled: over loopback, or whatever a test
        # hands in. Takes the account and its timezone, returns the
        # endpoint's answer.
        self._poll = poll or self._poll_over_loopback

    def _poll_over_loopback(self, account: dict[str, Any], timezone_name: str) -> dict[str, Any]:
        if not self.base_url or self.session_token_factory is None:
            raise RuntimeError("The inbox watch is not wired to the server.")
        body = json.dumps({"timezone": timezone_name}, ensure_ascii=False).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}{POLL_ENDPOINT}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token_factory(account['email'])}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=POLL_TIMEOUT_SECONDS) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                status = int(response.status)
        except urllib_error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                parsed = {}
            status = int(exc.code)
        except (urllib_error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"The inbox poll could not reach the server: {exc}") from exc
        result = parsed if isinstance(parsed, dict) else {}
        code = normalize_text(result.get("error"))
        if code == "trial_expired":
            raise TrialOver(code)
        if status != 200 or not result.get("ok"):
            detail = normalize_text(result.get("message"))
            raise RuntimeError(f"The inbox poll failed ({code or f'HTTP {status}'}{': ' + detail if detail else ''}).")
        return result

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        accounts = self.database.list_inbox_watch_due_accounts(now=reference, limit=self.config.batch_size)
        polled = failed = paused = 0
        notified = 0
        for account in accounts:
            user_id = int(account.get("userId") or 0)
            if user_id <= 0:
                continue
            timezone_name = account_timezone(self.database, user_id)
            local = reference.astimezone(_zone(timezone_name))
            interval = poll_interval_seconds(
                local,
                day_seconds=self.config.day_poll_seconds,
                night_seconds=self.config.night_poll_seconds,
                quiet_start=self.config.quiet_start_hour,
                quiet_end=self.config.quiet_end_hour,
            )
            try:
                result = self._poll(account, timezone_name)
            except TrialOver:
                paused += 1
                self.database.set_inbox_watch_next_poll(user_id=user_id, next_poll_at=reference + TRIAL_OVER_PAUSE)
                continue
            except Exception as exc:  # noqa: BLE001 - one account's trouble must not stop the rest
                failed += 1
                failures = int(account.get("failures") or 0) + 1
                backoff = min(MAX_BACKOFF_SECONDS, interval * (2 ** min(failures, 4)))
                print(f"[inbox-watch] user={user_id} poll failed (attempt {failures}): {exc}", flush=True)
                self.database.set_inbox_watch_next_poll(user_id=user_id, next_poll_at=reference + timedelta(seconds=backoff), error=str(exc))
                continue
            polled += 1
            notified += int(result.get("notified") or 0)
            self.database.set_inbox_watch_next_poll(user_id=user_id, next_poll_at=reference + timedelta(seconds=interval))
            if int(result.get("new") or 0) or int(result.get("notified") or 0):
                print(
                    f"[inbox-watch] user={user_id} new={result.get('new')} read={result.get('read')} held={result.get('held')} "
                    f"notified={result.get('notified')} next_in={interval}s",
                    flush=True,
                )
        return {"ok": True, "due": len(accounts), "polled": polled, "failed": failed, "paused": paused, "notified": notified}

    def serve_forever(self, stop_event: threading.Event, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                summary = self.run_pending()
                if int(summary.get("failed") or 0) > 0:
                    logger(f"[inbox-watch] polled={summary.get('polled')} failed={summary.get('failed')}")
            except Exception as exc:  # noqa: BLE001 - keep the watch alive
                logger(f"[inbox-watch] error: {exc}")
            stop_event.wait(max(10, int(self.config.tick_seconds)))


__all__ = [
    "InboxWatchConfig",
    "InboxWatchScheduler",
    "POLL_ENDPOINT",
    "TrialOver",
    "load_inbox_watch_config",
]
