"""Per-user token bucket for MCP tool calls (stays under the marketplace's own limit)."""

from __future__ import annotations

import threading
import time


class UserRateLimiter:
    def __init__(self, per_minute: int, burst: int | None = None) -> None:
        self.rate = per_minute / 60.0
        self.capacity = burst or max(1, per_minute)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, user: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(user, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._state[user] = (tokens - 1, now)
                return True, 0.0
            self._state[user] = (tokens, now)
            return False, round((1 - tokens) / self.rate, 1)
