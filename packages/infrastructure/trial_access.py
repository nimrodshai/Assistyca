"""How long a new account may use Assistyca before it has to pay.

A trial is measured in days rather than messages because days are what an
operator can reason about and quote to a client. The length is per account:
a prospect worth a fortnight gets a fortnight without changing anything for
anyone else.

Two accounts are never limited: one that is paying, and one whose trial length
is zero. Zero is what every account created before trials existed carries, so
introducing this cannot switch off a client who is already working.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_TRIAL_DAYS = 2


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def resolve_default_trial_days() -> int:
    """The trial length a newly created account starts on."""

    raw = normalize_text(os.getenv("PORTAL_DEFAULT_TRIAL_DAYS"))
    if not raw:
        return DEFAULT_TRIAL_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TRIAL_DAYS


def _parse_moment(value: Any) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def describe_trial(
    user: dict[str, Any] | None,
    *,
    is_paying: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Whether this account may still be used, and what to say if not."""

    record = user if isinstance(user, dict) else {}
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        days = max(0, int(record.get("trialDays") or 0))
    except (TypeError, ValueError):
        days = 0
    started_at = _parse_moment(record.get("trialStartedAt"))

    if is_paying or days <= 0:
        return {
            "onTrial": False,
            "allowed": True,
            "expired": False,
            "trialDays": days,
            "endsAt": "",
            "daysLeft": 0,
        }

    # A length with no start has never begun counting. Treating it as expired
    # would lock out an account because of a field nobody filled in.
    if started_at is None:
        return {
            "onTrial": True,
            "allowed": True,
            "expired": False,
            "trialDays": days,
            "endsAt": "",
            "daysLeft": days,
        }

    ends_at = started_at + timedelta(days=days)
    remaining = ends_at - moment
    return {
        "onTrial": True,
        "allowed": remaining.total_seconds() > 0,
        "expired": remaining.total_seconds() <= 0,
        "trialDays": days,
        "endsAt": ends_at.isoformat(),
        # Rounded up, so the last part-day still reads as a day left rather
        # than as none while the trial is genuinely still running.
        "daysLeft": max(0, -(-int(remaining.total_seconds()) // 86400)),
    }


def build_trial_expired_message(product_name: str = "Assistyca") -> str:
    return (
        f"Your {product_name} trial has ended, so I've stopped here. "
        "Get in touch to keep your assistant running and I'll pick up where we left off."
    )


__all__ = [
    "DEFAULT_TRIAL_DAYS",
    "build_trial_expired_message",
    "describe_trial",
    "resolve_default_trial_days",
]
