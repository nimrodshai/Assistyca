"""Shared tool-model selection utilities."""

from __future__ import annotations

from typing import Any

from packages.infrastructure.task_complexity import TaskComplexity, model_for_complexity


# What a client gets before they pick a model of their own.
DEFAULT_TOOL_MODEL = model_for_complexity(TaskComplexity.IMPORTANT)

TOOL_MODEL_OPTIONS = (
    {
        "id": "gpt-5.4-nano",
        "name": "GPT-5.4 Nano",
        "band": "Lean",
        "summary": "Lowest cost for lightweight tasks and high-volume automation.",
    },
    {
        "id": "gpt-5.4-mini",
        "name": "GPT-5.4 Mini",
        "band": "Efficient",
        "summary": "A lower-cost step up from nano for strong everyday replies and drafting.",
    },
    {
        "id": "gpt-5.4",
        "name": "GPT-5.4",
        "band": "Balanced",
        "summary": "A strong balance of quality, speed, and cost for most tools.",
    },
    {
        "id": "gpt-5.5",
        "name": "GPT-5.5",
        "band": "Premium",
        "summary": "Best for harder reasoning, deeper research, and higher-stakes output.",
    },
)


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_tool_model(value: Any, *, default: str = DEFAULT_TOOL_MODEL) -> str:
    normalized = normalize_text(value)
    return normalized or normalize_text(default) or DEFAULT_TOOL_MODEL


def resolve_tool_model(settings: dict[str, Any] | None = None, *, default: str = DEFAULT_TOOL_MODEL) -> str:
    source = settings if isinstance(settings, dict) else {}
    return normalize_tool_model(source.get("model"), default=default)


def list_tool_model_options() -> list[dict[str, str]]:
    return [dict(option) for option in TOOL_MODEL_OPTIONS]


__all__ = [
    "DEFAULT_TOOL_MODEL",
    "TOOL_MODEL_OPTIONS",
    "list_tool_model_options",
    "normalize_tool_model",
    "resolve_tool_model",
]
