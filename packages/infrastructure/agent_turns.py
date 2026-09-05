"""Seeing every turn: one record per turn, three numbers, and one alert.

The failure that started the conversation runtime work was invisible until
a customer saw it: a reply cut off by a token budget, logged as a parse
error with no text. This module is the answer to "how would we have known".
Every request that is part of a turn - the turn itself, a lookup it ran, the
answer it composed, the recovery reply it fell back to - lands on one row
keyed by the turn id, written whether the turn succeeded or not, with the
model, the tokens, the latency, each tool call and its outcome, whether the
fallback was used and why, and the raw model text when it failed.

From the rows come three numbers over the last day and week: the fallback
rate, the incomplete-response rate, and the tool error rate by code. When
the fallback rate over the last day crosses the line, every admin gets one
notification for that day. Once a week, a sample of real turns is scored by
the same judge the scripted conversations use, and the result lands in the
same feed, for a person to read.

Nothing here knows about HTTP handlers or WhatsApp. The recorder is handed
what was asked and what was answered; the server decides when a request is
part of a turn.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.infrastructure.openai_api import OpenAIError
from packages.infrastructure.openai_api import normalize_text
from packages.infrastructure.openai_api import observe_responses
from packages.infrastructure.openai_api import usage_context
from packages.infrastructure.openai_api import parse_bool
from packages.infrastructure.openai_api import safe_int

# The requests that make up a turn. The first two start one; the rest attach
# to the turn whose id they carry, and stand alone when they carry none.
TURN_STARTING_PATHS = frozenset({"/api/agent/turn", "/api/agent/loop"})
RECOVER_PATH = "/api/agent/recover"
RUN_PATH = "/api/agent/proposals/run"
COMPOSE_PATH = "/api/agent/answer/compose"
REVISE_PATH = "/api/agent/proposals/revise"
TURN_FOLLOW_UP_PATHS = frozenset({RECOVER_PATH, RUN_PATH, COMPOSE_PATH, REVISE_PATH})
TURN_PATHS = TURN_STARTING_PATHS | TURN_FOLLOW_UP_PATHS

# Outcomes of rows that are not a customer turn on their own: a lookup the
# browser ran from a card, a composer call with no turn in front of it. They
# carry tool calls and tokens but do not count in the fallback denominator.
NON_TURN_OUTCOMES = frozenset({"tool_only", "compose_only", "revise_only"})

MAX_STORED_TEXT = 1000
MAX_RAW_OUTPUT = 2000
MAX_TOOL_CALLS_STORED = 40
DAY = timedelta(days=1)
WEEK = timedelta(days=7)

# The alert line: a fallback rate over the last day above this, on at least
# this many turns, is the signal. The floor keeps one bad turn in a quiet
# hour from paging anyone, while at any real volume two percent is reached
# by a handful of failures.
DEFAULT_ALERT_RATE = 0.02
DEFAULT_ALERT_MIN_TURNS = 10
ALERT_SOURCE = "agent_turns"

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_SAMPLE_SIZE = 20
DEFAULT_SAMPLE_DAYS = 7
DEFAULT_SAMPLE_WEEKDAY = 0  # Monday
DEFAULT_SAMPLE_HOUR = 9
DEFAULT_SAMPLE_MINUTE = 30
DEFAULT_SAMPLE_POLL_SECONDS = 600


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _clip(value: Any, limit: int) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _parse_iso(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def describe_account_state(tool_context: Any) -> str:
    """The connected sources at the time, in words a judge can check a reply against."""

    context = tool_context if isinstance(tool_context, dict) else {}
    connected: list[str] = []
    for key, label in (("gmail", "Gmail"), ("outlook", "Outlook"), ("calendar", "Google Calendar"), ("drive", "Google Drive")):
        entry = context.get(key)
        if isinstance(entry, dict) and entry.get("platformConnected") is True:
            status = normalize_text(entry.get("connectionStatus")).lower()
            connected.append(f"{label} (needs attention)" if status == "needs_attention" else label)
    whatsapp = context.get("whatsapp") if isinstance(context.get("whatsapp"), dict) else {}
    parts = []
    if whatsapp.get("ready") or whatsapp.get("platformConnected"):
        parts.append("The WhatsApp number is connected.")
    parts.append(f"Connected sources: {', '.join(connected)}." if connected else "No mailbox, calendar or drive is connected.")
    return " ".join(parts)


def new_turn_record(
    *,
    turn_id: str,
    path: str,
    user_id: int = 0,
    channel: str = "",
    user_message: str = "",
    account_state: str = "",
    created_at: str = "",
) -> dict[str, Any]:
    now = created_at or _iso(_utc_now())
    return {
        "turn_id": normalize_text(turn_id) or uuid.uuid4().hex,
        "user_id": int(user_id or 0),
        "channel": normalize_text(channel).lower() or "portal",
        "path": normalize_text(path),
        "model": "",
        "reasoning_effort": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "model_calls": 0,
        "latency_ms": 0,
        "tool_calls": [],
        "outcome": "",
        "status_code": 0,
        "fallback_used": False,
        "fallback_reason": "",
        "incomplete_responses": 0,
        "raw_output_on_failure": "",
        "user_message": _clip(user_message, MAX_STORED_TEXT),
        "reply": "",
        "account_state": _clip(account_state, MAX_STORED_TEXT),
        "created_at": now,
        "updated_at": now,
    }


def describe_response(path: str, request: dict[str, Any], status: int, payload: dict[str, Any], *, latency_ms: int = 0) -> dict[str, Any]:
    """What one response means for the turn it belongs to.

    Pure, so the classification can be tested without a server: which
    outcome the turn had, whether the reply came from the fallback and why,
    and the tool call this request amounted to, if it was one.
    """

    request = request if isinstance(request, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    ok = status == 200 and bool(payload.get("ok"))
    error_code = normalize_text(payload.get("error"))
    http_reason = f"http_{status}" + (f":{error_code}" if error_code else "")
    described: dict[str, Any] = {
        "outcome": "",
        "fallback_used": False,
        "fallback_reason": "",
        "tool_call": None,
        "tool_calls": [],
        "reply": _clip(normalize_text(payload.get("reply")), MAX_STORED_TEXT),
    }

    if path in TURN_STARTING_PATHS:
        if not ok:
            # A refusal is the server saying no on purpose - bad input, no
            # session, a trial that ended. Everything else is a turn that
            # broke, and the person got a fallback reply or nothing.
            if status in (400, 401, 402, 403):
                described["outcome"] = "refused"
            else:
                described.update(outcome="error", fallback_used=True, fallback_reason=http_reason)
            return described
        outcome = normalize_text(payload.get("outcome")).lower() or "message"
        if isinstance(payload.get("pendingConfirmation"), dict) and payload.get("pendingConfirmation"):
            outcome = "confirmation_asked"
        elif isinstance(payload.get("calendarChoice"), list) and payload.get("calendarChoice"):
            outcome = "calendar_choice"
        described["outcome"] = outcome
        if payload.get("recovered"):
            reason = normalize_text(payload.get("recoveryCode")) or "recovered"
            if payload.get("composed") is False:
                reason += "/computed"
            described.update(fallback_used=True, fallback_reason=reason)
        elif payload.get("fallbackUsed"):
            described.update(fallback_used=True, fallback_reason=normalize_text(payload.get("fallbackReason")) or "fallback")
        raw_calls = payload.get("toolCalls") if isinstance(payload.get("toolCalls"), list) else []
        described["tool_calls"] = [normalize_tool_call(call) for call in raw_calls if isinstance(call, dict)]
        return described

    if path == RECOVER_PATH:
        situation = request.get("situation") if isinstance(request.get("situation"), dict) else {}
        code = normalize_text(payload.get("code")) or normalize_text(situation.get("code")) or "recovered"
        if not ok or payload.get("composed") is False:
            code += "/computed"
        described.update(outcome="recovered", fallback_used=True, fallback_reason=code)
        return described

    if path == RUN_PATH:
        name = normalize_text(request.get("proposalType") or request.get("proposal_type")).lower() or "run"
        if normalize_text(request.get("mode")).lower() == "answer":
            name = f"{name}:answer"
        described["outcome"] = "tool"
        described["tool_call"] = {"name": name, "ok": ok, "code": "" if ok else (error_code or f"http_{status}"), "ms": int(latency_ms)}
        return described

    if path == COMPOSE_PATH:
        described["outcome"] = "compose"
        if not ok:
            described.update(fallback_used=True, fallback_reason="answer_compose_failed" + (f":{error_code}" if error_code else ""))
        return described

    described["outcome"] = "revise"
    return described


def normalize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": normalize_text(call.get("name") or call.get("tool"))[:80],
        "ok": bool(call.get("ok")),
        "code": normalize_text(call.get("code"))[:80],
        "ms": safe_int(call.get("ms") or call.get("durationMs")),
    }


class TurnRecorder:
    """Collects what one request did and writes it onto its turn's row.

    Created before the handler runs, so the turn id exists for the reply to
    carry; observes every model call the handler makes on this thread; and
    on finish reads the response the handler wrote and files the row. A
    request that carries a turn id attaches to that row; one that starts a
    turn, or carries none, gets its own.
    """

    def __init__(
        self,
        *,
        database: Any,
        path: str,
        request: dict[str, Any] | None = None,
        user_id: int = 0,
        channel: str = "",
        turn_id: str = "",
    ) -> None:
        self.database = database
        self.path = normalize_text(path)
        self.request = request if isinstance(request, dict) else {}
        self.user_id = int(user_id or 0)
        self.channel = normalize_text(channel or self.request.get("channel")).lower() or "portal"
        requested_id = normalize_text(turn_id or self.request.get("turnId"))
        self.attaches = bool(requested_id) and self.path in TURN_FOLLOW_UP_PATHS
        self.turn_id = requested_id if self.attaches else uuid.uuid4().hex
        self.started = time.monotonic()
        self.model = ""
        self.reasoning_effort = ""
        self.input_tokens = 0
        self.output_tokens = 0
        self.model_calls = 0
        self.incomplete_responses = 0
        self.last_output = ""
        self.discarded = False
        self.record: dict[str, Any] | None = None
        self.finished = False

    def observe(self, result: Any) -> None:
        self.model_calls += 1
        self.model = normalize_text(getattr(result, "model", "")) or self.model
        self.input_tokens += safe_int(getattr(result, "input_tokens", 0))
        self.output_tokens += safe_int(getattr(result, "output_tokens", 0))
        self.incomplete_responses += safe_int(getattr(result, "incomplete_attempts", 0))
        request_payload = getattr(result, "request_payload", None)
        reasoning = request_payload.get("reasoning") if isinstance(request_payload, dict) else None
        if isinstance(reasoning, dict):
            self.reasoning_effort = normalize_text(reasoning.get("effort")) or self.reasoning_effort
        text = getattr(result, "output_text", "")
        if text:
            self.last_output = _clip(text, MAX_RAW_OUTPUT)

    @contextmanager
    def observing(self) -> Iterator[None]:
        # The usage rows this turn's model calls write carry the channel and
        # the turn id, so cost can be split by channel later without a join.
        with usage_context(channel=self.channel, turn_id=self.turn_id), observe_responses(self.observe):
            yield

    def discard(self) -> None:
        """Leave this turn out of the log.

        The one turn that deletes the account would otherwise be filed under
        it after everything else was erased: the yes, the goodbye, the
        account's state. An erasure that leaves a row saying "yes, delete me"
        is not an erasure.
        """

        self.discarded = True
        self.finished = True

    def finish(self, status: int, payload: dict[str, Any] | None, *, crashed: bool = False) -> dict[str, Any]:
        """File the row. Called once, before the reply leaves, so a call that
        follows with this turn's id finds the row it attaches to."""

        if self.discarded:
            return {}
        if self.finished and self.record is not None:
            return self.record
        self.finished = True
        payload = payload if isinstance(payload, dict) else {}
        latency_ms = int((time.monotonic() - self.started) * 1000)
        if crashed and not status:
            status = 500
        described = describe_response(self.path, self.request, int(status or 0), payload, latency_ms=latency_ms)
        if crashed:
            described.update(outcome="error", fallback_used=True, fallback_reason=described.get("fallback_reason") or "crashed")

        turn_id = normalize_text(payload.get("turnId")) or self.turn_id
        record = self.database.get_agent_turn(turn_id) if self.attaches else None
        if record is None:
            record = new_turn_record(
                turn_id=turn_id,
                path=self.path,
                user_id=self.user_id,
                channel=self.channel,
                user_message=normalize_text(self.request.get("userMessage")),
                account_state=describe_account_state(self.request.get("toolContext")),
            )
            outcome = described["outcome"]
            if self.path == RUN_PATH:
                outcome = "tool_only"
            elif self.path == COMPOSE_PATH:
                outcome = "compose_only"
            elif self.path == REVISE_PATH:
                outcome = "revise_only"
            record["outcome"] = outcome
            record["status_code"] = int(status or 0)
        else:
            if self.path == RECOVER_PATH:
                record["outcome"] = "recovered"
            if int(status or 0) and int(status or 0) != 200:
                record["status_code"] = int(status)
        if not record.get("user_id") and self.user_id:
            record["user_id"] = self.user_id

        record["model"] = self.model or record.get("model", "")
        record["reasoning_effort"] = self.reasoning_effort or record.get("reasoning_effort", "")
        record["input_tokens"] = safe_int(record.get("input_tokens")) + self.input_tokens
        record["output_tokens"] = safe_int(record.get("output_tokens")) + self.output_tokens
        record["model_calls"] = safe_int(record.get("model_calls")) + self.model_calls
        record["latency_ms"] = safe_int(record.get("latency_ms")) + latency_ms
        record["incomplete_responses"] = safe_int(record.get("incomplete_responses")) + self.incomplete_responses
        tool_calls = list(record.get("tool_calls") or [])
        tool_calls.extend(described["tool_calls"])
        if described["tool_call"]:
            tool_calls.append(described["tool_call"])
        record["tool_calls"] = tool_calls[:MAX_TOOL_CALLS_STORED]
        if described["fallback_used"]:
            record["fallback_used"] = True
            record["fallback_reason"] = described["fallback_reason"]
            if not record.get("raw_output_on_failure") and self.last_output:
                record["raw_output_on_failure"] = self.last_output
        if described["reply"]:
            record["reply"] = described["reply"]
        record["updated_at"] = _iso(_utc_now())

        self.database.save_agent_turn(record)
        self.record = record
        print(json.dumps({"event": "agent.turn.recorded", **public_turn(record)}, ensure_ascii=False), flush=True)
        try:
            check_fallback_alert(self.database)
        except Exception as exc:  # noqa: BLE001 - the alert must never break the reply
            print(f"Agent fallback alert check failed: {exc}", flush=True)
        return record


def public_turn(record: dict[str, Any]) -> dict[str, Any]:
    """The row as the page and the log see it."""

    return {
        "turnId": record.get("turn_id", ""),
        "userId": int(record.get("user_id") or 0),
        "channel": record.get("channel", ""),
        "model": record.get("model", ""),
        "reasoningEffort": record.get("reasoning_effort", ""),
        "inputTokens": safe_int(record.get("input_tokens")),
        "outputTokens": safe_int(record.get("output_tokens")),
        "modelCalls": safe_int(record.get("model_calls")),
        "latencyMs": safe_int(record.get("latency_ms")),
        "toolCalls": list(record.get("tool_calls") or []),
        "outcome": record.get("outcome", ""),
        "statusCode": safe_int(record.get("status_code")),
        "fallbackUsed": bool(record.get("fallback_used")),
        "fallbackReason": record.get("fallback_reason", ""),
        "incompleteResponses": safe_int(record.get("incomplete_responses")),
        "rawOutputOnFailure": record.get("raw_output_on_failure", ""),
        "userMessage": record.get("user_message", ""),
        "reply": record.get("reply", ""),
        "createdAt": record.get("created_at", ""),
    }


# -- the three numbers --------------------------------------------------------


def summarize_window(turns: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Fallback rate, incomplete-response rate, and tool error rate by code."""

    turn_count = 0
    fallbacks = 0
    incomplete = 0
    tool_calls = 0
    tool_errors = 0
    errors_by_code: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for record in turns:
        for call in record.get("tool_calls") or []:
            tool_calls += 1
            if not call.get("ok"):
                tool_errors += 1
                code = normalize_text(call.get("code")) or "unknown"
                errors_by_code[code] = errors_by_code.get(code, 0) + 1
        if normalize_text(record.get("outcome")) in NON_TURN_OUTCOMES:
            continue
        turn_count += 1
        if record.get("fallback_used"):
            fallbacks += 1
            reason = normalize_text(record.get("fallback_reason")) or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1
        if safe_int(record.get("incomplete_responses")) > 0:
            incomplete += 1
    return {
        "turns": turn_count,
        "fallbacks": fallbacks,
        "fallbackRate": (fallbacks / turn_count) if turn_count else 0.0,
        "fallbackReasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        "incompleteTurns": incomplete,
        "incompleteRate": (incomplete / turn_count) if turn_count else 0.0,
        "toolCalls": tool_calls,
        "toolErrors": tool_errors,
        "toolErrorRate": (tool_errors / tool_calls) if tool_calls else 0.0,
        "toolErrorsByCode": dict(sorted(errors_by_code.items(), key=lambda item: (-item[1], item[0]))),
    }


def turn_metrics(database: Any, *, now: datetime | None = None) -> dict[str, Any]:
    moment = now or _utc_now()
    week = database.list_agent_turns(since=_iso(moment - WEEK), limit=20000)
    day_start = moment - DAY
    day = [record for record in week if (_parse_iso(record.get("created_at")) or moment) >= day_start]
    return {"asOf": _iso(moment), "day": summarize_window(day), "week": summarize_window(week)}


# -- the alert ------------------------------------------------------------------


def alert_settings() -> dict[str, Any]:
    try:
        rate = float(os.getenv("PORTAL_AGENT_FALLBACK_ALERT_RATE") or DEFAULT_ALERT_RATE)
    except ValueError:
        rate = DEFAULT_ALERT_RATE
    return {
        "rate": max(0.0, min(1.0, rate)),
        "minTurns": max(1, safe_int(os.getenv("PORTAL_AGENT_FALLBACK_ALERT_MIN_TURNS")) or DEFAULT_ALERT_MIN_TURNS),
    }


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%" if value * 100 >= 10 else f"{value * 100:.1f}%"


def check_fallback_alert(database: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """One notification per admin per day when the last day's fallback rate crosses the line.

    Returns the day window when an alert is warranted, whether or not a new
    notification was written, so a caller can tell "quiet" from "already
    told them".
    """

    moment = now or _utc_now()
    settings = alert_settings()
    window = summarize_window(database.list_agent_turns(since=_iso(moment - DAY), limit=20000))
    if window["turns"] < settings["minTurns"] or window["fallbackRate"] <= settings["rate"]:
        return None
    dedupe_key = f"agent-fallback-alert:{moment.date().isoformat()}"
    reasons = ", ".join(f"{code} ({count})" for code, count in list(window["fallbackReasons"].items())[:6]) or "none recorded"
    title = f"Assistant fallback rate is {_percent(window['fallbackRate'])} today"
    body = (
        f"{window['fallbacks']} of {window['turns']} turns in the last 24 hours ended in a fallback reply, "
        f"above the {_percent(settings['rate'])} line. Reasons: {reasons}. "
        "Open Admin > Turns to read them."
    )
    for user_id in database.list_admin_user_ids():
        if database.has_notification(user_id=user_id, dedupe_key=dedupe_key):
            continue
        database.save_notification(
            user_id=user_id,
            title=title,
            body=body,
            kind="alert",
            tone="warning",
            source=ALERT_SOURCE,
            dedupe_key=dedupe_key,
            metadata={"window": "day", **window},
        )
        print(json.dumps({"event": "agent.fallback_alert", "userId": user_id, **window}, ensure_ascii=False), flush=True)
    return window


# -- the weekly sample ----------------------------------------------------------


def parse_weekday(value: Any, default: int = DEFAULT_SAMPLE_WEEKDAY) -> int:
    text = normalize_text(value).lower()
    if not text:
        return default
    if text.isdigit():
        return max(0, min(6, int(text)))
    for index, name in enumerate(WEEKDAY_NAMES):
        if name.startswith(text[:3]):
            return index
    return default


def resolve_timezone(name: str) -> Any:
    text = normalize_text(name)
    if text:
        try:
            return ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


@dataclass(frozen=True)
class AgentTurnSamplingConfig:
    enabled: bool = True
    timezone_name: str = ""
    schedule_weekday: int = DEFAULT_SAMPLE_WEEKDAY
    schedule_hour: int = DEFAULT_SAMPLE_HOUR
    schedule_minute: int = DEFAULT_SAMPLE_MINUTE
    sample_size: int = DEFAULT_SAMPLE_SIZE
    days: int = DEFAULT_SAMPLE_DAYS
    threshold: int = 3
    poll_seconds: int = DEFAULT_SAMPLE_POLL_SECONDS


def load_agent_turn_sampling_config() -> AgentTurnSamplingConfig:
    return AgentTurnSamplingConfig(
        enabled=parse_bool(os.getenv("PORTAL_AGENT_TURN_SAMPLING_ENABLED"), default=True),
        timezone_name=normalize_text(os.getenv("PORTAL_AGENT_TURN_SAMPLING_TIMEZONE") or os.getenv("PORTAL_WHATSAPP_REENGAGEMENT_TIMEZONE")),
        schedule_weekday=parse_weekday(os.getenv("PORTAL_AGENT_TURN_SAMPLING_WEEKDAY")),
        schedule_hour=max(0, min(23, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_HOUR")) if os.getenv("PORTAL_AGENT_TURN_SAMPLING_HOUR") else DEFAULT_SAMPLE_HOUR)),
        schedule_minute=max(0, min(59, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_MINUTE")) if os.getenv("PORTAL_AGENT_TURN_SAMPLING_MINUTE") else DEFAULT_SAMPLE_MINUTE)),
        sample_size=max(1, min(100, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_SIZE")) or DEFAULT_SAMPLE_SIZE)),
        days=max(1, min(31, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_DAYS")) or DEFAULT_SAMPLE_DAYS)),
        threshold=max(0, min(5, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_THRESHOLD")) or 3)),
        poll_seconds=max(60, safe_int(os.getenv("PORTAL_AGENT_TURN_SAMPLING_POLL_SECONDS")) or DEFAULT_SAMPLE_POLL_SECONDS),
    )


Judge = Callable[[str, list[dict[str, Any]], str], dict[str, Any]]


def score_sample(
    database: Any,
    *,
    judge: Judge,
    now: datetime | None = None,
    config: AgentTurnSamplingConfig | None = None,
) -> dict[str, Any]:
    """Pick random turns from the window and have the judge read each reply.

    A turn with no stored reply (the person got nothing back) is a failure
    without a judge; a turn the judge cannot score is reported as unscored
    rather than dropped, so a judge outage is visible in the report.
    """

    from packages.infrastructure.reply_judge import RUBRIC, low_points

    settings = config or AgentTurnSamplingConfig()
    moment = now or _utc_now()
    since = _iso(moment - timedelta(days=settings.days))
    turns = [
        record for record in database.sample_agent_turns(since=since, limit=settings.sample_size)
        if normalize_text(record.get("outcome")) not in NON_TURN_OUTCOMES
    ]
    scored: list[dict[str, Any]] = []
    passed = 0
    unscored = 0
    for record in turns:
        entry = {
            "turnId": record.get("turn_id", ""),
            "channel": record.get("channel", ""),
            "userMessage": record.get("user_message", ""),
            "reply": record.get("reply", ""),
            "fallbackUsed": bool(record.get("fallback_used")),
            "fallbackReason": record.get("fallback_reason", ""),
            "scores": None,
            "low": [],
            "note": "",
        }
        if not entry["reply"]:
            entry["low"] = list(RUBRIC)
            entry["note"] = "nothing was sent back"
        else:
            state = record.get("account_state") or "Only the WhatsApp number is known to be connected."
            conversation = [{"role": "user", "text": entry["userMessage"]}]
            try:
                scores = judge(state, conversation, entry["reply"])
            except OpenAIError as exc:
                unscored += 1
                entry["note"] = f"judge unavailable: {exc.message}"[:160]
                scored.append(entry)
                continue
            entry["scores"] = {key: int(scores.get(key, 0) or 0) for key in RUBRIC}
            entry["low"] = low_points(scores, settings.threshold)
            entry["note"] = str(scores.get("note") or "")[:160]
            if not entry["low"]:
                passed += 1
        scored.append(entry)
    return {
        "sampled": len(turns),
        "passed": passed,
        "unscored": unscored,
        "threshold": settings.threshold,
        "days": settings.days,
        "since": since,
        "fallbacks": sum(1 for entry in scored if entry["fallbackUsed"]),
        "entries": scored,
    }


def format_sample_report(report: dict[str, Any]) -> tuple[str, str]:
    """The notification's title and body: the headline, then every reply that fell short."""

    sampled = int(report.get("sampled") or 0)
    if sampled == 0:
        return (
            "Weekly turn sample: no turns to read",
            f"No customer turns were recorded in the last {report.get('days', DEFAULT_SAMPLE_DAYS)} days, so there was nothing to score.",
        )
    passed = int(report.get("passed") or 0)
    unscored = int(report.get("unscored") or 0)
    judged = sampled - unscored
    if judged <= 0:
        title = f"Weekly turn sample: none of {sampled} replies could be scored"
    else:
        title = f"Weekly turn sample: {passed} of {judged} replies scored {report.get('threshold', 3)} or better"
    lines = [
        f"{sampled} random turns from the last {report.get('days', DEFAULT_SAMPLE_DAYS)} days, "
        f"{report.get('fallbacks', 0)} of them fallback replies."
    ]
    if report.get("unscored"):
        lines.append(f"{report['unscored']} could not be scored because the judge was unavailable.")
    short = [entry for entry in report.get("entries", []) if entry.get("low")]
    if short:
        lines.append("")
        lines.append("Replies that fell short:")
        for entry in short:
            scores = entry.get("scores") or {}
            score_text = " ".join(f"{key[:3]}={scores[key]}" for key in scores) if scores else "unscored"
            lines.append(
                f"- [{entry.get('channel') or 'portal'}] {_clip(entry.get('userMessage'), 120)!r} -> "
                f"{_clip(entry.get('reply') or '(nothing)', 200)!r}  {score_text}"
                + (f"  {entry['note']}" if entry.get("note") else "")
            )
    elif judged > 0:
        lines.append("Every scored reply passed on every point.")
    lines.append("")
    lines.append("A reply that surprises you belongs in scripts/agent_conversation_eval.py as a scripted conversation.")
    return title, "\n".join(lines)


class AgentTurnSamplingScheduler:
    """Once a week, score a sample of real turns and put the report in the feed."""

    def __init__(self, database: Any, *, config: AgentTurnSamplingConfig | None = None, judge: Judge | None = None) -> None:
        self.database = database
        self.config = config or load_agent_turn_sampling_config()
        self._judge = judge

    def judge(self, state: str, conversation: list[dict[str, Any]], reply: str) -> dict[str, Any]:
        if self._judge is None:
            from packages.infrastructure.reply_judge import judge as default_judge

            self._judge = default_judge
        return self._judge(state, conversation, reply)

    def due_slot(self, now: datetime | None = None) -> datetime:
        """The most recent scheduled moment at or before now, in the configured zone."""

        zone = resolve_timezone(self.config.timezone_name)
        local_now = (now or _utc_now()).astimezone(zone)
        candidate = local_now.replace(hour=self.config.schedule_hour, minute=self.config.schedule_minute, second=0, microsecond=0)
        days_back = (local_now.weekday() - self.config.schedule_weekday) % 7
        candidate -= timedelta(days=days_back)
        if candidate > local_now:
            candidate -= timedelta(days=7)
        return candidate

    def run_pending(self, now: datetime | None = None) -> dict[str, Any]:
        moment = now or _utc_now()
        slot = self.due_slot(moment)
        dedupe_key = f"agent-turn-sample:{slot.date().isoformat()}"
        admins = [user_id for user_id in self.database.list_admin_user_ids() if not self.database.has_notification(user_id=user_id, dedupe_key=dedupe_key)]
        if not admins:
            return {"ran": False, "slot": slot.isoformat()}
        report = score_sample(self.database, judge=self.judge, now=moment, config=self.config)
        title, body = format_sample_report(report)
        for user_id in admins:
            self.database.save_notification(
                user_id=user_id,
                title=title,
                body=body,
                kind="report",
                tone="warning" if report["passed"] < report["sampled"] - report["unscored"] else "info",
                source=ALERT_SOURCE,
                dedupe_key=dedupe_key,
                metadata={"sampled": report["sampled"], "passed": report["passed"], "unscored": report["unscored"], "since": report["since"]},
            )
        return {"ran": True, "slot": slot.isoformat(), "report": report, "notified": admins}

    def serve_forever(self, stop_event: Any, *, log: Callable[[str], None] | None = None) -> None:
        logger = log or (lambda message: None)
        while not getattr(stop_event, "is_set", lambda: False)():
            try:
                summary = self.run_pending()
                if summary.get("ran"):
                    report = summary["report"]
                    logger(f"[agent-turn-sample] slot={summary['slot']} sampled={report['sampled']} passed={report['passed']} unscored={report['unscored']}")
            except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
                logger(f"[agent-turn-sample] error: {exc}")
            if getattr(stop_event, "wait", None) is None:
                break
            stop_event.wait(self.config.poll_seconds)


__all__ = [
    "AgentTurnSamplingConfig",
    "AgentTurnSamplingScheduler",
    "DEFAULT_ALERT_MIN_TURNS",
    "DEFAULT_ALERT_RATE",
    "TURN_FOLLOW_UP_PATHS",
    "TURN_PATHS",
    "TURN_STARTING_PATHS",
    "TurnRecorder",
    "alert_settings",
    "check_fallback_alert",
    "describe_account_state",
    "describe_response",
    "format_sample_report",
    "load_agent_turn_sampling_config",
    "new_turn_record",
    "public_turn",
    "score_sample",
    "summarize_window",
    "turn_metrics",
]
