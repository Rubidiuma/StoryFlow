from __future__ import annotations

"""Per-session sliding-window rate limiter."""

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class RateLimiter:
    """Allow at most max_requests per session within window_seconds."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock or time.monotonic
        self._history: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, session_id: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        history = self._history[session_id]
        # prune old entries
        while history and history[0] <= cutoff:
            history.pop(0)
        if len(history) >= self._max:
            return False
        history.append(now)
        return True
