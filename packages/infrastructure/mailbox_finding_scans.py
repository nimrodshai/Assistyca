"""When the mailbox is looked at, and how what it says reaches the person.

Connecting a mailbox is the moment the person is paying attention, and a
day of silence afterwards is how they forget the assistant exists. So the
first scan runs a few minutes after the mailbox connects and says one
thing - the single best finding from the last twelve months, or that
there was nothing. The next morning brings the rest, and every morning
after that brings only what has changed.

A scan is a row in account_finding_scans, claimed here the way a
scheduled action is claimed, and run over loopback through the server's
own endpoint with a short-lived session for the account - the same way a
standing action runs - so credentials stay where they live. What the scan
finds is queued as a one-off run_task, so the model writes the message in
the person's language over the same loop a standing action uses, with
the plain sentence the figures make on their own as the fallback, and the
delivery, the WhatsApp window and the in-app feed all come from the
scheduled actions worker.

Each scan schedules the next: first, then the morning digest, then daily.
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

from packages.infrastructure.mailbox_findings import FINDINGS_TITLE
from packages.infrastructure.mailbox_findings import MAX_FINDINGS_PER_MESSAGE
from packages.infrastructure.mailbox_findings import NOTHING_FOUND_TEXT
from packages.infrastructure.mailbox_findings import build_findings_fallback_text
from packages.infrastructure.mailbox_findings import build_findings_instruction
from packages.infrastructure.mailbox_findings import build_nothing_found_instruction
from packages.infrastructure.mailbox_findings import rank_findings
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import normalize_text
from packages.infrastructure.scheduled_actions import parse_bool_env
from packages.infrastructure.scheduled_actions import parse_int_env
from packages.infrastructure.standing_tasks import STANDING_TASK_ACTION_TYPE
from packages.infrastructure.whatsapp_agent_chat import infer_timezone_from_wa_id

FINDINGS_SOURCE = "mailbox_findings"
SCAN_ENDPOINT = "/api/findings/scan"
DEFAULT_SCAN_HOUR = 8
DEFAULT_SCAN_POLL_SECONDS = 60
DEFAULT_FIRST_SCAN_DELAY_MINUTES = 2
DEFAULT_SCAN_BATCH_SIZE = 3
# A first scan reads a year of mail a hundred messages at a time and puts
# each batch to the model; it can take a few minutes.
SCAN_TIMEOUT_SECONDS = 900
# The morning after connecting comes at the scan hour, but never sooner
# than this after the first scan: someone who connects at 07:50 should not
# get "the rest" ten minutes after "the first".
DIGEST_MIN_GAP = timedelta(hours=8)


@dataclass(frozen=True)
class FindingScanConfig:
    enabled: bool = True
    hour: int = DEFAULT_SCAN_HOUR
    poll_seconds: int = DEFAULT_SCAN_POLL_SECONDS
    first_delay_minutes: int = DEFAULT_FIRST_SCAN_DELAY_MINUTES
    batch_size: int = DEFAULT_SCAN_BATCH_SIZE


def load_finding_scan_config() -> FindingScanConfig:
    return FindingScanConfig(
        enabled=parse_bool_env(os.getenv("PORTAL_MAILBOX_FINDINGS_ENABLED"), True),
        hour=min(23, max(0, parse_int_env(os.getenv("PORTAL_MAILBOX_FINDINGS_HOUR"), DEFAULT_SCAN_HOUR))),
        poll_seconds=max(15, parse_int_env(os.getenv("PORTAL_MAILBOX_FINDINGS_POLL_SECONDS"), DEFAULT_SCAN_POLL_SECONDS)),
        first_delay_minutes=max(
            0, parse_int_env(os.getenv("PORTAL_MAILBOX_FINDINGS_FIRST_DELAY_MINUTES"), DEFAULT_FIRST_SCAN_DELAY_MINUTES)
        ),
        batch_size=max(1, parse_int_env(os.getenv("PORTAL_MAILBOX_FINDINGS_BATCH_SIZE"), DEFAULT_SCAN_BATCH_SIZE)),
    )


def _zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(normalize_text(timezone_name) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def next_scan_run_at(
    *,
    hour: int,
    timezone_name: str,
    after: datetime,
    min_gap: timedelta = timedelta(0),
) -> datetime:
    """The next scan hour on the person's clock, at least ``min_gap`` away."""

    zone = _zone(timezone_name)
    earliest = after.astimezone(timezone.utc) + min_gap
    local = earliest.astimezone(zone)
    candidate = local.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    if candidate < local:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def account_timezone(database: Any, user_id: int, fallback: str = "") -> str:
    """Where the person is: from their WhatsApp number, else what the scan
    row says, else the last message they scheduled, else UTC."""

    try:
        connection = database.get_whatsapp_connection_by_user_id(user_id) or {}
    except Exception:  # noqa: BLE001
        connection = {}
    wa_id = normalize_text(connection.get("ownerWaId"))
    if wa_id:
        inferred = infer_timezone_from_wa_id(wa_id)
        if inferred and inferred != "UTC":
            return inferred
    if normalize_text(fallback):
        return normalize_text(fallback)
    try:
        actions = database.list_scheduled_actions_for_user(user_id, limit=1)
    except Exception:  # noqa: BLE001
        actions = []
    for action in actions:
        name = normalize_text(action.get("timezone"))
        if name:
            return name
    return "UTC"


def choose_findings_to_tell(findings: list[dict[str, Any]], *, kind: str) -> tuple[list[dict[str, Any]], int]:
    """Which of the untold findings this message carries, and how many wait.

    The first message carries exactly one: the best. A morning carries up
    to a handful, best first, and says how many more there are.
    """

    untold = rank_findings(finding for finding in findings if normalize_text(finding.get("status")) == "new")
    limit = 1 if kind == "first" else MAX_FINDINGS_PER_MESSAGE
    chosen = untold[:limit]
    return chosen, max(0, len(untold) - len(chosen))


def build_findings_action_payload(
    findings: list[dict[str, Any]],
    *,
    kind: str,
    subscriptions: dict[str, dict[str, Any]] | None,
    more_count: int,
) -> dict[str, Any] | None:
    """The one-off action that tells the person, or None when there is
    nothing to say. A first scan with nothing found still says so."""

    if findings:
        return {
            "title": FINDINGS_TITLE,
            "instruction": build_findings_instruction(
                findings,
                kind=kind,
                subscriptions=subscriptions if kind in {"first", "digest"} else None,
                more_count=more_count,
            ),
            "fallbackText": build_findings_fallback_text(findings, kind=kind, more_count=more_count),
            "oneOff": True,
            "source": FINDINGS_SOURCE,
            "scanKind": kind,
            "findingKeys": [normalize_text(finding.get("key")) for finding in findings],
        }
    if kind == "first":
        return {
            "title": FINDINGS_TITLE,
            "instruction": build_nothing_found_instruction(),
            "fallbackText": NOTHING_FOUND_TEXT,
            "oneOff": True,
            "source": FINDINGS_SOURCE,
            "scanKind": kind,
            "findingKeys": [],
        }
    return None


class FindingScanScheduler:
    """Runs due scans, tells the person, and lines up the next scan."""

    def __init__(
        self,
        database: PortalDatabase,
        *,
        config: FindingScanConfig | None = None,
        base_url: str = "",
        session_token_factory: Callable[[str], str] | None = None,
        scan: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.database = database
        self.config = config or load_finding_scan_config()
        self.base_url = str(base_url or "").rstrip("/")
        self.session_token_factory = session_token_factory
        # How a scan is run: over loopback by default, or whatever a test
        # hands in. Takes the scan row and the account, returns the
        # endpoint's answer.
        self._scan = scan or self._scan_over_loopback

    # -- the account behind a scan -------------------------------------------

    def _account_for(self, scan: dict[str, Any]) -> dict[str, Any]:
        user_id = int(scan.get("userId") or 0)
        if user_id <= 0:
            raise RuntimeError("Mailbox scan is missing a user id.")
        user = self.database.get_user_by_id(user_id) or {}
        email = normalize_text(user.get("email"))
        if not email or not bool(user.get("isActive", True)):
            raise RuntimeError("Mailbox scan does not resolve to an active account.")
        connection = self.database.get_whatsapp_connection_by_user_id(user_id) or {}
        owner_wa_id = normalize_text(connection.get("ownerWaId"))
        if not owner_wa_id:
            linked = self.database.list_user_whatsapp_numbers(user_id=user_id)
            owner_wa_id = normalize_text(linked[0].get("waId")) if linked else ""
        return {
            "userId": user_id,
            "email": email,
            "ownerWaId": owner_wa_id,
            "timezone": account_timezone(self.database, user_id, normalize_text(scan.get("timezone"))),
        }

    # -- running one scan ----------------------------------------------------

    def _scan_over_loopback(self, scan: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url or self.session_token_factory is None:
            raise RuntimeError("Mailbox scans are not wired to the server.")
        body = json.dumps({
            "kind": normalize_text(scan.get("kind")) or "daily",
            "timezone": account["timezone"],
        }, ensure_ascii=False).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}{SCAN_ENDPOINT}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token_factory(account['email'])}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=SCAN_TIMEOUT_SECONDS) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                status = int(response.status)
        except urllib_error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                parsed = {}
            status = int(exc.code)
        except (urllib_error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"The mailbox scan could not reach the server: {exc}") from exc
        result = parsed if isinstance(parsed, dict) else {}
        if status != 200 or not result.get("ok"):
            code = normalize_text(result.get("error")) or f"HTTP {status}"
            detail = normalize_text(result.get("message"))
            raise RuntimeError(f"The mailbox scan failed ({code}{': ' + detail if detail else ''}).")
        return result

    def _tell(self, scan: dict[str, Any], account: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Queue the message about what was found and mark those findings told."""

        kind = normalize_text(scan.get("kind")) or "daily"
        findings = [finding for finding in (result.get("findings") or []) if isinstance(finding, dict)]
        chosen, more_count = choose_findings_to_tell(findings, kind=kind)
        subscriptions = result.get("subscriptions") if isinstance(result.get("subscriptions"), dict) else None
        payload = build_findings_action_payload(chosen, kind=kind, subscriptions=subscriptions, more_count=more_count)
        if payload is None:
            return {"told": 0, "waiting": more_count}
        channel = "whatsapp" if account.get("ownerWaId") else "portal"
        action = self.database.create_scheduled_action(
            user_id=int(account["userId"]),
            action_type=STANDING_TASK_ACTION_TYPE,
            channel=channel,
            recipient_ref="owner",
            run_at=datetime.now(timezone.utc),
            timezone_name=account["timezone"],
            payload={**payload, "scanId": int(scan.get("id") or 0)},
        )
        told = self.database.mark_account_findings_told(
            user_id=int(account["userId"]),
            keys=[normalize_text(finding.get("key")) for finding in chosen],
        )
        return {"told": told, "waiting": more_count, "actionId": int(action.get("id") or 0), "channel": channel}

    def _schedule_next(self, scan: dict[str, Any], account: dict[str, Any], *, now: datetime) -> dict[str, Any] | None:
        kind = normalize_text(scan.get("kind")) or "daily"
        next_kind = "digest" if kind == "first" else "daily"
        run_at = next_scan_run_at(
            hour=self.config.hour,
            timezone_name=account["timezone"],
            after=now,
            min_gap=DIGEST_MIN_GAP if kind == "first" else timedelta(0),
        )
        return self.database.schedule_finding_scan(
            user_id=int(account["userId"]),
            kind=next_kind,
            run_at=run_at,
            timezone_name=account["timezone"],
            after_scan_id=int(scan.get("id") or 0),
        )

    def run_scan(self, scan: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        account = self._account_for(scan)
        result = self._scan(scan, account)
        outcome = self._tell(scan, account, result)
        following = self._schedule_next(scan, account, now=reference)
        summary = {
            "mailboxes": int(result.get("mailboxes") or 0),
            "read": result.get("read") if isinstance(result.get("read"), dict) else {},
            "findings": len(result.get("findings") or []),
            "newKeys": len(result.get("newKeys") or []),
            "failures": result.get("failures") if isinstance(result.get("failures"), list) else [],
            **outcome,
            "nextScanId": int((following or {}).get("id") or 0),
            "nextRunAt": normalize_text((following or {}).get("runAt")),
        }
        return summary

    # -- the loop ------------------------------------------------------------

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            recovered = self.database.requeue_stale_finding_scans(now=reference)
        except Exception:  # noqa: BLE001 - recovery must never block the scans
            recovered = 0
        due = self.database.list_due_finding_scans(now=reference, limit=self.config.batch_size)
        processed = done = failed = 0
        for waiting in due:
            claimed = self.database.claim_finding_scan(int(waiting.get("id") or 0))
            if not claimed:
                continue
            processed += 1
            try:
                summary = self.run_scan(claimed, now=reference)
            except Exception as exc:  # noqa: BLE001 - one account's trouble must not stop the rest
                failed += 1
                print(f"[mailbox-findings] scan={claimed.get('id')} kind={claimed.get('kind')} failed: {exc}", flush=True)
                self._fail(claimed, error=str(exc), now=reference)
                continue
            done += 1
            self.database.finish_finding_scan(scan_id=int(claimed["id"]), status="done", summary=summary)
            print(
                f"[mailbox-findings] scan={claimed.get('id')} kind={claimed.get('kind')} "
                f"findings={summary.get('findings')} told={summary.get('told')} next={summary.get('nextRunAt')}",
                flush=True,
            )
        return {"ok": True, "due": len(due), "processed": processed, "done": done, "failed": failed, "recovered": recovered}

    def _fail(self, scan: dict[str, Any], *, error: str, now: datetime) -> None:
        """A failed scan is not the end of the account's mornings. It is
        marked failed with why, and the next morning's scan is still lined
        up, so a mailbox that refused today is read tomorrow."""

        self.database.finish_finding_scan(scan_id=int(scan.get("id") or 0), status="failed", last_error=error)
        try:
            user_id = int(scan.get("userId") or 0)
            timezone_name = account_timezone(self.database, user_id, normalize_text(scan.get("timezone")))
            self.database.schedule_finding_scan(
                user_id=user_id,
                kind="daily",
                run_at=next_scan_run_at(hour=self.config.hour, timezone_name=timezone_name, after=now, min_gap=timedelta(hours=1)),
                timezone_name=timezone_name,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[mailbox-findings] scan={scan.get('id')} could not line up the next scan: {exc}", flush=True)

    def serve_forever(self, stop_event: threading.Event, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                summary = self.run_pending()
                if int(summary.get("processed") or 0) > 0:
                    logger(
                        f"[mailbox-findings] processed={summary.get('processed')} done={summary.get('done')} "
                        f"failed={summary.get('failed')}"
                    )
            except Exception as exc:  # noqa: BLE001 - keep the scanner alive
                logger(f"[mailbox-findings] error: {exc}")
            stop_event.wait(max(15, int(self.config.poll_seconds)))


__all__ = [
    "DEFAULT_SCAN_HOUR",
    "FINDINGS_SOURCE",
    "FindingScanConfig",
    "FindingScanScheduler",
    "SCAN_ENDPOINT",
    "account_timezone",
    "build_findings_action_payload",
    "choose_findings_to_tell",
    "load_finding_scan_config",
    "next_scan_run_at",
]
