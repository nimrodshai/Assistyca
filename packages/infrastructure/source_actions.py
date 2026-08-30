"""Safe recurring snapshots for user-provided URLs and files.

This phase deliberately stores only the latest fetch metadata. It does not send
source contents to the language model or attempt to interpret them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import os
import socket
import threading
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.portal_db import normalize_text


DEFAULT_SOURCE_ACTION_POLL_SECONDS = 15
DEFAULT_SOURCE_ACTION_BATCH_SIZE = 10
SOURCE_ACTION_MAX_BYTES = 5 * 1024 * 1024
# Hourly is the shortest cadence a source check is offered on. Re-reading a
# page every few minutes cost far more than it was worth and surfaced nothing
# a person could act on any sooner.
SOURCE_ACTION_MIN_INTERVAL_MINUTES = 60
SOURCE_ACTION_MAX_INTERVAL_MINUTES = 30 * 24 * 60
SOURCE_ACTION_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class SourceActionConfig:
    enabled: bool = True
    poll_seconds: int = DEFAULT_SOURCE_ACTION_POLL_SECONDS
    batch_size: int = DEFAULT_SOURCE_ACTION_BATCH_SIZE
    max_bytes: int = SOURCE_ACTION_MAX_BYTES
    timeout_seconds: int = SOURCE_ACTION_TIMEOUT_SECONDS


def _parse_bool(value: str | None, default: bool) -> bool:
    text = normalize_text(value).lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(normalize_text(value) or default)
    except (TypeError, ValueError):
        return default


def load_source_action_config() -> SourceActionConfig:
    return SourceActionConfig(
        enabled=_parse_bool(os.getenv("PORTAL_SOURCE_ACTIONS_ENABLED"), True),
        poll_seconds=max(1, _parse_int(os.getenv("PORTAL_SOURCE_ACTIONS_POLL_SECONDS"), DEFAULT_SOURCE_ACTION_POLL_SECONDS)),
        batch_size=max(1, min(100, _parse_int(os.getenv("PORTAL_SOURCE_ACTIONS_BATCH_SIZE"), DEFAULT_SOURCE_ACTION_BATCH_SIZE))),
        max_bytes=max(1024, min(SOURCE_ACTION_MAX_BYTES, _parse_int(os.getenv("PORTAL_SOURCE_ACTIONS_MAX_BYTES"), SOURCE_ACTION_MAX_BYTES))),
        timeout_seconds=max(3, min(60, _parse_int(os.getenv("PORTAL_SOURCE_ACTIONS_TIMEOUT_SECONDS"), SOURCE_ACTION_TIMEOUT_SECONDS))),
    )


def _host_is_private(hostname: str) -> bool:
    lowered = normalize_text(hostname).lower().rstrip(".")
    if not lowered or lowered in {"localhost", "localhost.localdomain", "metadata.google.internal"} or lowered.endswith(".local"):
        return True
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(lowered, None, type=socket.SOCK_STREAM)}
    except OSError:
        # Let the actual fetch report DNS failures, but do not accept a host
        # whose address cannot be inspected as an internal/private exception.
        return False
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not parsed.is_global:
            return True
    return False


def validate_source_url(value: str) -> str:
    parsed = urllib_parse.urlparse(normalize_text(value))
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Source URL must use http or https.")
    if parsed.username or parsed.password:
        raise ValueError("Source URLs cannot include embedded credentials.")
    if not parsed.hostname:
        raise ValueError("Source URL must include a hostname.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Source URL must use the standard web port.")
    if _host_is_private(parsed.hostname):
        raise ValueError("Private or local network URLs are not allowed.")
    return urllib_parse.urlunparse(parsed._replace(fragment=""))


class _SafeRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        safe_url = validate_source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def fetch_source_url(url: str, *, max_bytes: int = SOURCE_ACTION_MAX_BYTES, timeout_seconds: int = SOURCE_ACTION_TIMEOUT_SECONDS) -> dict[str, Any]:
    safe_url = validate_source_url(url)
    request = urllib_request.Request(
        safe_url,
        headers={"User-Agent": "Assistyca-SourceAction/1.0", "Accept": "text/*,application/json,application/xml"},
        method="GET",
    )
    opener = urllib_request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = validate_source_url(response.geturl())
            content_length = normalize_text(response.headers.get("Content-Length"))
            if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                raise ValueError(f"Source is larger than the {max_bytes // (1024 * 1024)} MB limit.")
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError(f"Source is larger than the {max_bytes // (1024 * 1024)} MB limit.")
            return {
                "url": final_url,
                "httpStatus": int(getattr(response, "status", 200) or 200),
                "contentType": normalize_text(response.headers.get_content_type()),
                "contentHash": hashlib.sha256(content).hexdigest(),
                "contentSize": len(content),
            }
    except urllib_error.HTTPError as exc:
        raise RuntimeError(f"Source returned HTTP {exc.code}.") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Source could not be reached: {normalize_text(exc.reason) or 'network error'}.") from exc


def run_source_action(database: PortalDatabase, action: dict[str, Any], *, config: SourceActionConfig) -> dict[str, Any]:
    source_type = normalize_text(action.get("sourceType")).lower()
    if source_type == "url":
        result = fetch_source_url(
            str(action.get("sourceUrl") or ""),
            max_bytes=config.max_bytes,
            timeout_seconds=config.timeout_seconds,
        )
        database.finish_source_action(
            action_id=int(action.get("id") or 0), status="active", last_run_status="success",
            last_http_status=int(result["httpStatus"]), last_content_type=str(result["contentType"]),
            last_content_hash=str(result["contentHash"]), last_content_size=int(result["contentSize"]),
            next_run_at=datetime.now(timezone.utc) + timedelta(minutes=int(action.get("intervalMinutes") or 1440)),
        )
        return {"status": "success", **result}

    raw = database.get_source_action(int(action.get("id") or 0), include_bytes=True) or {}
    content = raw.get("fileBytes") if isinstance(raw.get("fileBytes"), (bytes, bytearray)) else b""
    if not content:
        raise RuntimeError("Stored source file is empty.")
    digest = hashlib.sha256(content).hexdigest()
    database.finish_source_action(
        action_id=int(action.get("id") or 0), status="active", last_run_status="success",
        last_content_type=str(raw.get("mimeType") or "application/octet-stream"),
        last_content_hash=digest, last_content_size=len(content),
        next_run_at=datetime.now(timezone.utc) + timedelta(minutes=int(action.get("intervalMinutes") or 1440)),
    )
    return {"status": "success", "contentHash": digest, "contentSize": len(content)}


class SourceActionScheduler:
    def __init__(self, database: PortalDatabase, *, config: SourceActionConfig | None = None) -> None:
        self.database = database
        self.config = config or load_source_action_config()

    def run_pending(self, *, now: datetime | None = None) -> dict[str, Any]:
        reference = now or datetime.now(timezone.utc)

        # Recover sources stranded in 'running' by a crashed or redeployed worker;
        # without this they are never polled again.
        try:
            recovered = self.database.requeue_stale_source_actions(now=reference)
        except Exception:  # noqa: BLE001 - recovery must never block the batch
            recovered = 0

        due = self.database.list_due_source_actions(now=reference, limit=self.config.batch_size)
        processed = success = failed = 0
        for candidate in due:
            action = self.database.claim_source_action(int(candidate.get("id") or 0))
            if not action:
                continue
            processed += 1
            try:
                run_source_action(self.database, action, config=self.config)
                success += 1
            except Exception as exc:  # noqa: BLE001 - isolate one source from the batch
                failed += 1
                self.database.finish_source_action(
                    action_id=int(action.get("id") or 0), status="active", last_run_status="failed",
                    last_error=str(exc),
                    next_run_at=datetime.now(timezone.utc) + timedelta(minutes=int(action.get("intervalMinutes") or 1440)),
                )
        return {
            "ok": True,
            "due": len(due),
            "processed": processed,
            "success": success,
            "failed": failed,
            "recovered": recovered,
        }

    def run_one(self, action_id: int) -> dict[str, Any]:
        action = self.database.claim_source_action(int(action_id), force=True)
        if not action:
            raise RuntimeError("Source action is not active or was already claimed.")
        try:
            return run_source_action(self.database, action, config=self.config)
        except Exception as exc:  # noqa: BLE001
            self.database.finish_source_action(
                action_id=int(action.get("id") or 0), status="active", last_run_status="failed",
                last_error=str(exc),
                next_run_at=datetime.now(timezone.utc) + timedelta(minutes=int(action.get("intervalMinutes") or 1440)),
            )
            raise

    def serve_forever(self, stop_event: threading.Event, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda _message: None)
        while not stop_event.is_set():
            try:
                result = self.run_pending()
                if result["processed"]:
                    logger(f"Source actions processed: {result}")
            except Exception as exc:  # noqa: BLE001
                logger(f"Source action scheduler error: {exc}")
            stop_event.wait(self.config.poll_seconds)
