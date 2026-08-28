"""Centralized OpenAI Responses API gateway with usage tracking.

This module keeps the OpenAI integration in one place so callers do not need
to hand-roll request construction, token accounting, or billing persistence.
It is intentionally dependency-light and uses the standard library only.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Callable
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.infrastructure.task_complexity import TaskComplexity, model_for_complexity


_logger = logging.getLogger("assistyca.openai_api")

DEFAULT_OPENAI_API_BASE = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = model_for_complexity(TaskComplexity.IMPORTANT)
DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_CURRENCY = "USD"

# Bounded retry for transient upstream failures. Only idempotent-safe conditions
# are retried: connection errors, 408/409/429 and 5xx. Everything else fails fast.
DEFAULT_OPENAI_MAX_ATTEMPTS = 3
DEFAULT_OPENAI_RETRY_BASE_DELAY_SECONDS = 0.5
DEFAULT_OPENAI_RETRY_MAX_DELAY_SECONDS = 8.0
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

OpenAIEventSink = Callable[[dict[str, Any]], None]
OpenAIPriceResolver = Callable[
    [str],
    Optional[Union[dict[str, Any], Tuple[Optional[float], Optional[float]]]],
]


def _sleep_before_retry(attempt: int, *, retry_after: str | None = None) -> None:
    """Back off between attempts, honouring Retry-After when the server sends it."""

    delay = min(
        DEFAULT_OPENAI_RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)),
        DEFAULT_OPENAI_RETRY_MAX_DELAY_SECONDS,
    )
    if retry_after:
        try:
            delay = max(delay, min(float(str(retry_after).strip()), DEFAULT_OPENAI_RETRY_MAX_DELAY_SECONDS))
        except (TypeError, ValueError):
            pass
    time.sleep(delay)


class OpenAIError(RuntimeError):
    """Base error for OpenAI gateway failures."""

    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class OpenAIConfigurationError(OpenAIError):
    """Raised when the gateway cannot be configured safely."""


class OpenAIRequestError(OpenAIError):
    """Raised when the OpenAI API request fails."""

    def __init__(self, message: str, *, details: str = "", status_code: int | None = None) -> None:
        super().__init__(message, details=details)
        self.status_code = status_code


class OpenAITrackingError(OpenAIError):
    """Raised when usage or event tracking cannot be completed."""

    def __init__(self, message: str, *, details: str = "", data: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.data = data if isinstance(data, dict) else {}


@dataclass
class OpenAIConfig:
    api_key: str = ""
    base_url: str = DEFAULT_OPENAI_API_BASE
    default_model: str = DEFAULT_OPENAI_MODEL
    timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    default_currency: str = DEFAULT_OPENAI_CURRENCY
    count_input_tokens_before_request: bool = False
    strict_tracking: bool = True
    include_prompt_in_metadata: bool = True


@dataclass
class OpenAIRequest:
    tool_name: str
    prompt: str
    billing_email: str = ""
    tool_id: str = ""
    model: str = ""
    instructions: str = ""
    skills: Sequence[Any] = field(default_factory=tuple)
    input: Any = None
    tools: Sequence[Any] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    input_price_cents_per_1k_tokens: float | None = None
    output_price_cents_per_1k_tokens: float | None = None
    input_token_price_multiplier: float | None = None
    output_token_price_multiplier: float | None = None
    currency: str | None = None
    timeout_seconds: float | None = None
    extra_payload: dict[str, Any] = field(default_factory=dict)
    count_input_tokens: bool | None = None


@dataclass
class OpenAIResult:
    request_id: str
    billing_email: str
    tool_name: str
    tool_id: str
    model: str
    response_id: str
    output_text: str
    usage: dict[str, Any]
    input_tokens: int
    output_tokens: int
    counted_input_tokens: int | None
    raw_response: dict[str, Any]
    request_payload: dict[str, Any]
    started_at: str
    completed_at: str
    duration_ms: int
    billing_snapshot: dict[str, Any] | None = None
    usage_record: dict[str, Any] | None = None


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = normalize_text(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.isoformat()

    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]

    return normalize_text(value)


def load_openai_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
    timeout_seconds: float | None = None,
    default_currency: str | None = None,
    count_input_tokens_before_request: bool | None = None,
    strict_tracking: bool | None = None,
    include_prompt_in_metadata: bool | None = None,
) -> OpenAIConfig:
    return OpenAIConfig(
        api_key=normalize_text(api_key if api_key is not None else os.getenv("OPENAI_API_KEY")),
        base_url=normalize_text(base_url if base_url is not None else os.getenv("OPENAI_BASE_URL"))
        or DEFAULT_OPENAI_API_BASE,
        default_model=normalize_text(default_model if default_model is not None else os.getenv("OPENAI_MODEL"))
        or DEFAULT_OPENAI_MODEL,
        timeout_seconds=safe_float(
            timeout_seconds if timeout_seconds is not None else os.getenv("OPENAI_TIMEOUT_SECONDS")
        )
        or DEFAULT_OPENAI_TIMEOUT_SECONDS,
        default_currency=normalize_text(
            default_currency if default_currency is not None else os.getenv("OPENAI_BILLING_CURRENCY")
        )
        or DEFAULT_OPENAI_CURRENCY,
        count_input_tokens_before_request=parse_bool(
            count_input_tokens_before_request
            if count_input_tokens_before_request is not None
            else os.getenv("OPENAI_COUNT_INPUT_TOKENS"),
            default=False,
        ),
        strict_tracking=parse_bool(
            strict_tracking if strict_tracking is not None else os.getenv("OPENAI_STRICT_TRACKING"),
            default=True,
        ),
        include_prompt_in_metadata=parse_bool(
            include_prompt_in_metadata
            if include_prompt_in_metadata is not None
            else os.getenv("OPENAI_INCLUDE_PROMPT_IN_METADATA"),
            default=True,
        ),
    )


def extract_openai_error_message(payload: dict[str, Any], *, status_code: int | None = None) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""

    message = normalize_text(error.get("message"))
    if message:
        return message

    error_type = normalize_text(error.get("type"))
    if error_type:
        return error_type

    if status_code in {401, 403}:
        return "OpenAI rejected the API key."

    if status_code == 404:
        return "OpenAI could not find the requested resource."

    return ""


def extract_openai_usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    usage_payload = usage if isinstance(usage, dict) else {}
    input_tokens = safe_int(usage_payload.get("input_tokens") or usage_payload.get("prompt_tokens"))
    output_tokens = safe_int(usage_payload.get("output_tokens") or usage_payload.get("completion_tokens"))
    total_tokens = safe_int(usage_payload.get("total_tokens")) or (input_tokens + output_tokens)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "raw": make_json_safe(usage_payload),
        "input_tokens_details": make_json_safe(
            usage_payload.get("input_tokens_details") or usage_payload.get("prompt_tokens_details") or {}
        ),
        "output_tokens_details": make_json_safe(
            usage_payload.get("output_tokens_details") or usage_payload.get("completion_tokens_details") or {}
        ),
    }


def extract_openai_output_text(payload: dict[str, Any]) -> str:
    direct_output = normalize_text(payload.get("output_text"))
    if direct_output:
        return direct_output

    output = payload.get("output")
    pieces: list[str] = []
    seen: set[str] = set()

    def add_piece(candidate: Any) -> None:
        text = normalize_text(candidate)
        if text and text not in seen:
            seen.add(text)
            pieces.append(text)

    def walk(value: Any) -> None:
        if isinstance(value, str):
            add_piece(value)
            return

        if isinstance(value, list):
            for item in value:
                walk(item)
            return

        if isinstance(value, dict):
            for key in ("output_text", "text", "value"):
                add_piece(value.get(key))

            content = value.get("content")
            if isinstance(content, (list, dict, str)):
                walk(content)

    walk(output)
    return "\n".join(pieces).strip()


def _request_url(base_url: str, path: str) -> str:
    return f"{normalize_text(base_url).rstrip('/')}/{path.lstrip('/')}"


def _json_request(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], int]:
    body = json.dumps(make_json_safe(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    # Bounded retry with exponential backoff. A single transient blip used to be
    # terminal, and for scheduled actions that meant a message was silently never
    # delivered because the row was marked failed with no path back to pending.
    max_attempts = max(1, DEFAULT_OPENAI_MAX_ATTEMPTS)
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
                status_code = int(getattr(response, "status", 200) or 200)
            break
        except urllib_error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code in RETRYABLE_HTTP_STATUS_CODES
            if retryable and attempt < max_attempts:
                _sleep_before_retry(attempt, retry_after=exc.headers.get("Retry-After") if exc.headers else None)
                continue
            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                parsed = {}
            message = extract_openai_error_message(parsed, status_code=exc.code) if isinstance(parsed, dict) else ""
            if not message:
                message = f"OpenAI returned HTTP {exc.code}."
            raise OpenAIRequestError(message, details=raw_body, status_code=exc.code) from exc
        except urllib_error.URLError as exc:
            if attempt < max_attempts:
                _sleep_before_retry(attempt)
                continue
            reason = normalize_text(getattr(exc, "reason", "")) or "The network request failed."
            raise OpenAIRequestError("OpenAI did not respond. Check the network and try again.", details=reason) from exc

    try:
        parsed_body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise OpenAIRequestError("OpenAI returned an unexpected response.", details=raw_body) from exc

    if not isinstance(parsed_body, dict):
        raise OpenAIRequestError("OpenAI returned an unexpected response.", details=raw_body)

    return parsed_body, status_code


class OpenAIGateway:
    """Single entry point for OpenAI API calls and billing instrumentation."""

    def __init__(
        self,
        *,
        config: OpenAIConfig | None = None,
        usage_recorder: Any | None = None,
        billing_email: str = "",
        event_sink: OpenAIEventSink | None = None,
        price_resolver: OpenAIPriceResolver | None = None,
    ) -> None:
        self.config = config or load_openai_config()
        self.usage_recorder = usage_recorder
        self.billing_email = normalize_text(billing_email)
        self.event_sink = event_sink
        self.price_resolver = price_resolver

    @classmethod
    def from_env(
        cls,
        *,
        usage_recorder: Any | None = None,
        billing_email: str = "",
        event_sink: OpenAIEventSink | None = None,
        price_resolver: OpenAIPriceResolver | None = None,
    ) -> "OpenAIGateway":
        return cls(
            config=load_openai_config(),
            usage_recorder=usage_recorder,
            billing_email=billing_email,
            event_sink=event_sink,
            price_resolver=price_resolver,
        )

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self.event_sink is None:
            # No caller currently supplies an event sink, which meant that skipped
            # billing -- the one event that costs real money -- produced no log, no
            # metric, and no row. Fall back to the module logger so the gap is at
            # least observable in the deployment logs.
            _logger.warning(
                "%s %s",
                event_name,
                json.dumps(make_json_safe(payload), ensure_ascii=True, sort_keys=True),
            )
            return

        envelope = make_json_safe(
            {
                "event": event_name,
                "timestamp": now_iso(),
                "component": "openai_api",
                **payload,
            }
        )
        try:
            self.event_sink(envelope)
        except Exception as exc:  # noqa: BLE001 - tracking failures should be explicit
            raise OpenAITrackingError(
                f"OpenAI event sink failed for {event_name}.",
                details=str(exc),
                data=envelope if isinstance(envelope, dict) else {},
            ) from exc

    def _resolve_model(self, request: OpenAIRequest) -> str:
        return normalize_text(request.model) or self.config.default_model

    def _resolve_billing_email(self, request: OpenAIRequest) -> str:
        return normalize_text(request.billing_email) or self.billing_email

    def _resolve_input(self, request: OpenAIRequest) -> Any:
        if request.input is not None:
            return request.input
        return request.prompt

    def _resolve_instructions(self, request: OpenAIRequest) -> str:
        sections: list[str] = []
        instructions = normalize_text(request.instructions)
        if instructions:
            sections.append(instructions)

        skills = [normalize_text(skill) for skill in request.skills if normalize_text(skill)]
        if skills:
            sections.append("Relevant skills:\n" + "\n".join(f"- {skill}" for skill in skills))

        return "\n\n".join(sections).strip()

    def _build_request_payload(self, request: OpenAIRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        model = self._resolve_model(request)
        tool_name = normalize_text(request.tool_name)
        if not tool_name:
            raise OpenAIConfigurationError("OpenAI tool_name is required.")

        prompt = normalize_text(request.prompt)
        if request.input is None and not prompt:
            raise OpenAIConfigurationError("OpenAI prompt is required when no structured input is provided.")

        resolved_input = self._resolve_input(request)
        payload: dict[str, Any] = {
            "model": model,
            "input": resolved_input,
        }

        instructions = self._resolve_instructions(request)
        if instructions:
            payload["instructions"] = instructions

        if request.tools:
            payload["tools"] = list(request.tools)

        if request.reasoning is not None:
            payload["reasoning"] = request.reasoning

        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = int(request.max_output_tokens)

        if request.temperature is not None:
            payload["temperature"] = float(request.temperature)

        if request.top_p is not None:
            payload["top_p"] = float(request.top_p)

        if request.extra_payload:
            payload.update(request.extra_payload)

        tracking_metadata = make_json_safe(dict(request.metadata or {}))
        tracking_metadata.setdefault("tool_name", tool_name)
        tracking_metadata.setdefault("tool_id", normalize_text(request.tool_id) or tool_name)
        tracking_metadata.setdefault("model", model)
        if self.config.include_prompt_in_metadata:
            tracking_metadata["prompt"] = prompt
            tracking_metadata["input"] = make_json_safe(resolved_input)
            if instructions:
                tracking_metadata["instructions"] = instructions
        tracking_metadata["skills"] = [normalize_text(skill) for skill in request.skills if normalize_text(skill)]
        return make_json_safe(payload), make_json_safe(tracking_metadata)

    def _resolve_price_snapshot(self, request: OpenAIRequest, *, model: str) -> dict[str, Any] | None:
        if self.usage_recorder is None:
            return None

        input_price = request.input_price_cents_per_1k_tokens
        output_price = request.output_price_cents_per_1k_tokens
        currency = normalize_text(request.currency)
        source = ""
        price_row: Any = None

        if input_price is None or output_price is None:
            synced_price_row = self._sync_usage_recorder_price(model)
            if isinstance(synced_price_row, dict):
                price_row = synced_price_row
                source = "pricing_sync"

            if self.price_resolver is not None:
                resolved_row = self.price_resolver(model)
                if resolved_row is not None:
                    price_row = resolved_row
                    source = "resolver"
            elif hasattr(self.usage_recorder, "get_model_price"):
                resolved_row = self.usage_recorder.get_model_price(model)
                if resolved_row is not None:
                    price_row = resolved_row
                    source = "usage_recorder"

        if isinstance(price_row, dict):
            input_price = (
                input_price
                if input_price is not None
                else (
                    price_row.get("input_price_cents_per_1k_tokens")
                    if price_row.get("input_price_cents_per_1k_tokens") is not None
                    else price_row.get("inputPriceCentsPer1kTokens")
                )
            )
            output_price = (
                output_price
                if output_price is not None
                else (
                    price_row.get("output_price_cents_per_1k_tokens")
                    if price_row.get("output_price_cents_per_1k_tokens") is not None
                    else price_row.get("outputPriceCentsPer1kTokens")
                )
            )
            currency = currency or normalize_text(price_row.get("currency"))
            source = source or "usage_recorder"
        elif isinstance(price_row, tuple):
            if len(price_row) >= 1 and input_price is None:
                input_price = price_row[0]
            if len(price_row) >= 2 and output_price is None:
                output_price = price_row[1]
            source = source or "resolver"

        if input_price is None or output_price is None:
            return {
                "input_price_cents_per_1k_tokens": None,
                "output_price_cents_per_1k_tokens": None,
                "currency": currency or self.config.default_currency,
                "source": source or "missing",
            }

        return {
            "input_price_cents_per_1k_tokens": float(input_price),
            "output_price_cents_per_1k_tokens": float(output_price),
            "currency": currency or self.config.default_currency,
            "source": source or "explicit",
        }

    def _sync_usage_recorder_price(self, model: str) -> dict[str, Any] | None:
        if self.usage_recorder is None:
            return None
        if (
            not hasattr(self.usage_recorder, "get_model_price")
            or not hasattr(self.usage_recorder, "upsert_model_price")
        ):
            return None

        try:
            from packages.infrastructure.openai_pricing import resolve_current_openai_model_price

            return resolve_current_openai_model_price(self.usage_recorder, model)
        except Exception:
            return None

    def _should_count_input_tokens(self, request: OpenAIRequest) -> bool:
        if request.count_input_tokens is not None:
            return bool(request.count_input_tokens)
        return bool(self.config.count_input_tokens_before_request)

    def count_input_tokens(self, request: OpenAIRequest) -> int:
        model = self._resolve_model(request)
        request_payload, _ = self._build_request_payload(request)
        request_payload["model"] = model

        parsed_body, _ = _json_request(
            _request_url(self.config.base_url, "/responses/input_tokens"),
            request_payload,
            api_key=self.config.api_key,
            timeout_seconds=request.timeout_seconds or self.config.timeout_seconds,
        )
        input_tokens = safe_int(parsed_body.get("input_tokens"))
        if input_tokens <= 0:
            raise OpenAIRequestError("OpenAI did not return an input token count.", details=json.dumps(parsed_body))
        return input_tokens

    def create_response(self, request: OpenAIRequest) -> OpenAIResult:
        api_key = normalize_text(self.config.api_key)
        if not api_key:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required.")

        request_id = uuid.uuid4().hex
        billing_email = self._resolve_billing_email(request)
        model = self._resolve_model(request)
        started_at = now_utc()
        timeout_seconds = request.timeout_seconds or self.config.timeout_seconds

        request_payload, tracking_metadata = self._build_request_payload(request)
        request_payload["model"] = model
        if request.input is None:
            request_payload["input"] = request.prompt

        if self.usage_recorder is not None and self.config.strict_tracking:
            if not billing_email:
                raise OpenAITrackingError(
                    "OpenAI usage tracking is enabled, but no billing email was provided.",
                    data={"request_id": request_id, "tool_name": request.tool_name, "model": model},
                )

            price_snapshot = self._resolve_price_snapshot(request, model=model)
            if not isinstance(price_snapshot, dict) or price_snapshot.get("input_price_cents_per_1k_tokens") is None:
                raise OpenAITrackingError(
                    f"OpenAI usage tracking is enabled, but pricing for {model} could not be resolved.",
                    data={"request_id": request_id, "tool_name": request.tool_name, "model": model},
                )
        else:
            price_snapshot = self._resolve_price_snapshot(request, model=model)

        counted_input_tokens: int | None = None
        if self._should_count_input_tokens(request):
            counted_input_tokens = self.count_input_tokens(request)
            self._emit(
                "openai.tokens.counted",
                {
                    "request_id": request_id,
                    "billing_email": billing_email,
                    "tool_name": normalize_text(request.tool_name),
                    "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                    "model": model,
                    "input_tokens": counted_input_tokens,
                },
            )

        self._emit(
            "openai.request.started",
            {
                "request_id": request_id,
                "billing_email": billing_email,
                "tool_name": normalize_text(request.tool_name),
                "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                "model": model,
                "prompt": normalize_text(request.prompt),
                "skills": [normalize_text(skill) for skill in request.skills if normalize_text(skill)],
                "has_structured_input": request.input is not None,
            },
        )

        try:
            response_body, status_code = _json_request(
                _request_url(self.config.base_url, "/responses"),
                request_payload,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
        except OpenAIRequestError as exc:
            self._emit(
                "openai.request.failed",
                {
                    "request_id": request_id,
                    "billing_email": billing_email,
                    "tool_name": normalize_text(request.tool_name),
                    "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                    "model": model,
                    "error": exc.message,
                    "details": exc.details,
                    "status_code": exc.status_code,
                },
            )
            raise

        completed_at = now_utc()
        duration_ms = int(round((completed_at - started_at).total_seconds() * 1000))
        response_model = normalize_text(response_body.get("model")) or model
        response_id = normalize_text(response_body.get("id"))
        output_text = extract_openai_output_text(response_body)
        usage = extract_openai_usage(response_body)

        self._emit(
            "openai.request.completed",
            {
                "request_id": request_id,
                "billing_email": billing_email,
                "tool_name": normalize_text(request.tool_name),
                "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                "model": response_model,
                "response_id": response_id,
                "status_code": status_code,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "output_text_length": len(output_text),
                "duration_ms": duration_ms,
            },
        )

        usage_record: dict[str, Any] | None = None
        if self.usage_recorder is not None:
            tracking_issue = ""
            if not billing_email:
                tracking_issue = "billing email was not provided"
            elif usage["input_tokens"] <= 0 and usage["output_tokens"] <= 0:
                tracking_issue = "the OpenAI response did not include usage data"
            elif not isinstance(price_snapshot, dict) or price_snapshot.get("input_price_cents_per_1k_tokens") is None:
                tracking_issue = f"pricing for {response_model} could not be resolved"

            if tracking_issue:
                if self.config.strict_tracking:
                    raise OpenAITrackingError(
                        f"OpenAI usage tracking is enabled, but {tracking_issue}.",
                        data={
                            "request_id": request_id,
                            "response_id": response_id,
                            "tool_name": request.tool_name,
                            "model": response_model,
                            "response": make_json_safe(response_body),
                        },
                    )

                self._emit(
                    "openai.usage.skipped",
                    {
                        "request_id": request_id,
                        "billing_email": billing_email,
                        "tool_name": normalize_text(request.tool_name),
                        "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                        "model": response_model,
                        "response_id": response_id,
                        "reason": tracking_issue,
                    },
                )
            else:
                record_metadata = make_json_safe(tracking_metadata)
                openai_metadata = record_metadata.get("openai")
                openai_metadata = openai_metadata if isinstance(openai_metadata, dict) else {}
                record_metadata["openai"] = make_json_safe(
                    {
                        **openai_metadata,
                        "request_id": request_id,
                        "response_id": response_id,
                        "status_code": status_code,
                        "response_model": response_model,
                        "output_text": output_text if self.config.include_prompt_in_metadata else "",
                        "usage": usage,
                        "counted_input_tokens": counted_input_tokens,
                        "billing_snapshot": price_snapshot,
                    }
                )

                try:
                    usage_record = self.usage_recorder.record_usage(
                        billing_email,
                        response_model,
                        tool_id=normalize_text(request.tool_id) or normalize_text(request.tool_name),
                        used_at=completed_at,
                        input_tokens=usage["input_tokens"],
                        output_tokens=usage["output_tokens"],
                        input_price_cents_per_1k_tokens=price_snapshot["input_price_cents_per_1k_tokens"],
                        output_price_cents_per_1k_tokens=price_snapshot["output_price_cents_per_1k_tokens"],
                        input_token_price_multiplier=request.input_token_price_multiplier,
                        output_token_price_multiplier=request.output_token_price_multiplier,
                        currency=price_snapshot["currency"],
                        metadata=record_metadata,
                    )
                except Exception as exc:  # noqa: BLE001 - tracking failures should stay visible
                    self._emit(
                        "openai.usage.failed",
                        {
                            "request_id": request_id,
                            "billing_email": billing_email,
                            "tool_name": normalize_text(request.tool_name),
                            "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                            "model": response_model,
                            "response_id": response_id,
                            "error": str(exc),
                        },
                    )
                    raise OpenAITrackingError(
                        "OpenAI usage could not be recorded.",
                        details=str(exc),
                        data={
                            "request_id": request_id,
                            "response_id": response_id,
                            "tool_name": request.tool_name,
                            "model": response_model,
                            "response": make_json_safe(response_body),
                        },
                    ) from exc

                self._emit(
                    "openai.usage.recorded",
                    {
                        "request_id": request_id,
                        "billing_email": billing_email,
                        "tool_name": normalize_text(request.tool_name),
                        "tool_id": normalize_text(request.tool_id) or normalize_text(request.tool_name),
                        "model": response_model,
                        "response_id": response_id,
                        "input_tokens": usage["input_tokens"],
                        "output_tokens": usage["output_tokens"],
                        "billing_snapshot": price_snapshot,
                        "usage_record": make_json_safe(usage_record),
                    },
                )

        completed_at_iso = completed_at.isoformat()
        return OpenAIResult(
            request_id=request_id,
            billing_email=billing_email,
            tool_name=normalize_text(request.tool_name),
            tool_id=normalize_text(request.tool_id) or normalize_text(request.tool_name),
            model=response_model,
            response_id=response_id,
            output_text=output_text,
            usage=usage,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            counted_input_tokens=counted_input_tokens,
            raw_response=make_json_safe(response_body),
            request_payload=make_json_safe(request_payload),
            started_at=started_at.isoformat(),
            completed_at=completed_at_iso,
            duration_ms=duration_ms,
            billing_snapshot=price_snapshot,
            usage_record=make_json_safe(usage_record) if usage_record is not None else None,
        )


def create_openai_gateway(
    *,
    usage_recorder: Any | None = None,
    billing_email: str = "",
    event_sink: OpenAIEventSink | None = None,
    price_resolver: OpenAIPriceResolver | None = None,
    config: OpenAIConfig | None = None,
) -> OpenAIGateway:
    """Convenience factory for callers that want a one-line gateway setup."""

    return OpenAIGateway(
        config=config or load_openai_config(),
        usage_recorder=usage_recorder,
        billing_email=billing_email,
        event_sink=event_sink,
        price_resolver=price_resolver,
    )


def call_openai_response(
    *,
    tool_name: str,
    prompt: str,
    billing_email: str = "",
    tool_id: str = "",
    model: str = "",
    instructions: str = "",
    skills: Sequence[Any] = (),
    input: Any = None,
    tools: Sequence[Any] = (),
    metadata: dict[str, Any] | None = None,
    reasoning: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    input_price_cents_per_1k_tokens: float | None = None,
    output_price_cents_per_1k_tokens: float | None = None,
    input_token_price_multiplier: float | None = None,
    output_token_price_multiplier: float | None = None,
    currency: str | None = None,
    timeout_seconds: float | None = None,
    extra_payload: dict[str, Any] | None = None,
    count_input_tokens: bool | None = None,
    usage_recorder: Any | None = None,
    event_sink: OpenAIEventSink | None = None,
    price_resolver: OpenAIPriceResolver | None = None,
    config: OpenAIConfig | None = None,
) -> OpenAIResult:
    """One-shot helper for direct callers that do not want to manage a gateway."""

    gateway = create_openai_gateway(
        usage_recorder=usage_recorder,
        billing_email=billing_email,
        event_sink=event_sink,
        price_resolver=price_resolver,
        config=config,
    )
    return gateway.create_response(
        OpenAIRequest(
            tool_name=tool_name,
            prompt=prompt,
            billing_email=billing_email,
            tool_id=tool_id,
            model=model,
            instructions=instructions,
            skills=skills,
            input=input,
            tools=tools,
            metadata=metadata or {},
            reasoning=reasoning,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
            input_price_cents_per_1k_tokens=input_price_cents_per_1k_tokens,
            output_price_cents_per_1k_tokens=output_price_cents_per_1k_tokens,
            input_token_price_multiplier=input_token_price_multiplier,
            output_token_price_multiplier=output_token_price_multiplier,
            currency=currency,
            timeout_seconds=timeout_seconds,
            extra_payload=extra_payload or {},
            count_input_tokens=count_input_tokens,
        )
    )


__all__ = [
    "DEFAULT_OPENAI_API_BASE",
    "DEFAULT_OPENAI_CURRENCY",
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OPENAI_TIMEOUT_SECONDS",
    "OpenAIConfig",
    "OpenAIConfigurationError",
    "OpenAIError",
    "OpenAIGateway",
    "OpenAIPriceResolver",
    "OpenAIRequest",
    "OpenAIRequestError",
    "OpenAIResult",
    "OpenAITrackingError",
    "call_openai_response",
    "create_openai_gateway",
    "load_openai_config",
]
