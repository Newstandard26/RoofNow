"""Best-effort request rate limiting for the public /api/measure endpoint.

Why this matters: in live mode every request hits Google's paid Solar /
Geocoding APIs, so an unauthenticated public endpoint needs a throttle to
cap cost and abuse.

Scope & honesty: Vercel serverless functions are stateless and horizontally
scaled, so an in-process counter only limits a single *warm* instance, not
the whole fleet. That is still a meaningful first layer (Vercel reuses
instances, so a single client hammering one instance is curbed). For strict
global limits, back this with a shared store (Vercel KV / Upstash Redis) by
implementing the same ``check`` interface — the function code won't change.

The limiter itself is pure and unit-tested with an injectable clock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Tuple


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float  # seconds until the window resets (0 when allowed)


@dataclass
class FixedWindowRateLimiter:
    """Per-key fixed-window limiter. Thread-safe, O(1) per check."""

    max_requests: int
    window_seconds: float = 60.0
    clock: Callable[[], float] = field(default=None)  # type: ignore[assignment]
    _buckets: Dict[str, Tuple[float, int]] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        if self.clock is None:
            import time

            object.__setattr__(self, "clock", time.monotonic)
        if self.max_requests < 0:
            raise ValueError("max_requests must be >= 0")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0

    def check(self, key: str) -> RateLimitResult:
        """Count one request for ``key`` and report whether it's allowed."""
        if not self.enabled:
            return RateLimitResult(True, self.max_requests, self.max_requests, 0.0)

        now = self.clock()
        with self._lock:
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= self.window_seconds:
                start, count = now, 0  # window expired -> reset
            count += 1
            self._buckets[key] = (start, count)
            self._maybe_prune(now)

        allowed = count <= self.max_requests
        remaining = max(0, self.max_requests - count)
        retry_after = 0.0 if allowed else max(0.0, self.window_seconds - (now - start))
        return RateLimitResult(allowed, self.max_requests, remaining, retry_after)

    def _maybe_prune(self, now: float) -> None:
        """Drop expired buckets occasionally to bound memory. Caller holds lock."""
        if len(self._buckets) < 1024:
            return
        stale = [
            k for k, (start, _) in self._buckets.items()
            if now - start >= self.window_seconds
        ]
        for k in stale:
            del self._buckets[k]
