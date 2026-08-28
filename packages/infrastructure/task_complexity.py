"""Task complexity levels and the model each level runs on.

Every LLM-backed task in the codebase declares how demanding it is, and that
level decides which model the task runs on. Keeping the mapping here means
changing a model is one edit instead of a hunt through call sites.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any


class TaskComplexity(str, Enum):
    """How demanding an LLM task is."""

    # Open-ended reasoning, live research, or output a customer acts on directly.
    IMPORTANT = "important"
    # Constrained drafting or structured edits inside a fixed shape.
    MEDIUM = "medium"
    # Short, mechanical work such as classification or field extraction.
    SMALL = "small"


COMPLEXITY_MODELS = {
    TaskComplexity.IMPORTANT: "gpt-5.5",
    TaskComplexity.MEDIUM: "gpt-5.4-mini",
    TaskComplexity.SMALL: "gpt-5.4-nano",
}


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def model_for_complexity(complexity: Any) -> str:
    """Return the model a task of this complexity runs on.

    An unreadable level falls back to the strongest model: treating an unknown
    task as important keeps quality intact, where silently dropping it to the
    cheapest model could ship poor output to a customer.
    """
    try:
        level = TaskComplexity(complexity)
    except ValueError:
        level = TaskComplexity.IMPORTANT
    return COMPLEXITY_MODELS[level]


def resolve_task_model(complexity: Any, *env_var_names: str) -> str:
    """Return the first environment override that is set, else the model this
    complexity level maps to.

    Overrides stay available for incident response; the complexity level is the
    normal way a task's model is decided.
    """
    for name in env_var_names:
        override = normalize_text(os.getenv(name))
        if override:
            return override
    return model_for_complexity(complexity)


__all__ = [
    "COMPLEXITY_MODELS",
    "TaskComplexity",
    "model_for_complexity",
    "resolve_task_model",
]
