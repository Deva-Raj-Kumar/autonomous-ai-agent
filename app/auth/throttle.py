"""Brute-force protection for /auth/login: too many failures -> wait.

Keyed by email + client IP, so an attacker can't lock a real user out from elsewhere
just by guessing (they only block their own IP for that email).

In memory, per process: fine for one server. With several workers or servers you'd
keep these counters in Redis so every process sees the same numbers.
"""

import time
from collections import deque


class LoginThrottle:
    def __init__(self, max_failures: int, window_seconds: float, clock=time.monotonic) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._clock = clock  # injectable, so tests don't have to sleep
        self._failures: dict[str, deque[float]] = {}

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again (0 = allowed now)."""
        failures = self._recent(key)
        if len(failures) < self._max:
            return 0
        return max(1, int(failures[0] + self._window - self._clock()) + 1)

    def record_failure(self, key: str) -> None:
        self._recent(key)
        self._failures.setdefault(key, deque()).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def tracked_keys(self) -> int:
        return len(self._failures)

    def _recent(self, key: str) -> deque[float]:
        """Failures inside the window; old ones are dropped, and so are keys left with
        none (otherwise every email ever tried would stay in memory forever)."""
        failures = self._failures.get(key)
        if failures is None:
            return deque()
        cutoff = self._clock() - self._window
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            del self._failures[key]
        return failures
