"""Per-API-key token bucket and a configurable chaos injector (random 5xx)."""

from __future__ import annotations

import os
import random
import threading
import time


class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int | None = None) -> None:
        self.rate = rate_per_minute / 60.0
        self.capacity = burst or rate_per_minute
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, round((1 - tokens) / self.rate, 2)


class Chaos:
    """Returns True when a request should fail with a 5xx. Rate from GIGSIM_CHAOS_RATE."""

    def __init__(self, rate: float | None = None, seed: int | None = None) -> None:
        self.rate = float(os.environ.get("GIGSIM_CHAOS_RATE", "0.02")) if rate is None else rate
        self._rng = random.Random(seed)

    def should_fail(self) -> bool:
        return self.rate > 0 and self._rng.random() < self.rate
