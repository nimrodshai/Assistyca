"""Shared in-process rate limiting for portal endpoints.

The portal runs as a single ThreadingHTTPServer process, so a plain in-memory
sliding window is sufficient and avoids adding a dependency. If the deployment
ever grows past one instance this needs to move to shared storage -- until then,
per-process limits are the honest boundary.

Buckets are keyed by an arbitrary string (client IP, normalized email, or a
combination). Expired entries are pruned opportunistically so the structure stays
bounded by the number of distinct keys seen inside the longest window.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitRule:
    """Allow at most `limit` events per `window_seconds` for a given key."""

    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("Rate limit must be positive.")
        if self.window_seconds <= 0:
            raise ValueError("Rate limit window must be positive.")


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.allowed


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window counter."""

    # Stop tracking a key once it holds no events inside the window.
    _PRUNE_EVERY_SECONDS = 60.0

    def __init__(self, *, time_source=time.monotonic) -> None:
        self._time_source = time_source
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}
        self._last_prune = time_source()

    def check(self, key: str, rule: RateLimitRule) -> RateLimitDecision:
        """Record an attempt for `key` and report whether it is allowed.

        A rejected attempt is not recorded, so a client that backs off recovers
        as soon as the window slides rather than being held out indefinitely.
        """

        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

        now = self._time_source()
        cutoff = now - rule.window_seconds

        with self._lock:
            self._maybe_prune_locked(now)
            bucket = self._events.get(normalized_key)
            if bucket is None:
                bucket = deque()
                self._events[normalized_key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= rule.limit:
                retry_after = max(1, int(bucket[0] + rule.window_seconds - now) + 1)
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

            bucket.append(now)
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

    def reset(self, key: str) -> None:
        """Forget a key, e.g. after a successful sign-in."""

        normalized_key = str(key or "").strip().lower()
        if not normalized_key:
            return
        with self._lock:
            self._events.pop(normalized_key, None)

    def _maybe_prune_locked(self, now: float) -> None:
        if now - self._last_prune < self._PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        # A key is dropped once its newest event is older than the longest window
        # we plausibly use. One hour is comfortably above every rule below.
        cutoff = now - 3600.0
        stale = [key for key, bucket in self._events.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._events.pop(key, None)


# Rules used by the portal. Kept together so the limits are reviewable in one place.
OTP_REQUEST_PER_IP = RateLimitRule(limit=10, window_seconds=600)
OTP_REQUEST_PER_EMAIL = RateLimitRule(limit=5, window_seconds=600)
OTP_VERIFY_PER_IP = RateLimitRule(limit=20, window_seconds=600)
OTP_VERIFY_PER_EMAIL = RateLimitRule(limit=10, window_seconds=600)
CONTACT_PER_IP = RateLimitRule(limit=5, window_seconds=3600)
CONTACT_AGENT_PER_IP = RateLimitRule(limit=15, window_seconds=3600)
CONTACT_AGENT_GLOBAL = RateLimitRule(limit=300, window_seconds=3600)
# Each registration creates an account and sends one WhatsApp message.
REGISTER_PER_IP = RateLimitRule(limit=5, window_seconds=3600)
# Each voice note is one transcription call on the account's bill.
VOICE_TRANSCRIBE_PER_USER = RateLimitRule(limit=120, window_seconds=3600)
