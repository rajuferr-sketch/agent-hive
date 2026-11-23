"""Sliding-window rate limiter (per token identity or client IP).

Pure in-memory: protects the process from abuse without adding
infrastructure. Entries are pruned lazily; the window and limit come from
settings so operators can tune without code changes.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

from agent_hive.config.settings import get_settings


@dataclass(slots=True)
class RateVerdict:
    allowed: bool
    remaining: int
    retry_after_s: int


class RateLimiter:
    def __init__(self, limit: int | None = None, window_s: int | None = None) -> None:
        settings = get_settings()
        self.limit = settings.rate_limit_requests if limit is None else limit
        self.window = settings.rate_limit_window if window_s is None else window_s
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._monotonic = time.monotonic

    def check(self, key: str) -> RateVerdict:
        """Record a hit for ``key`` and decide if it is allowed."""
        now = self._monotonic()
        dq = self._hits[key]
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.limit:
            retry = int(max(1, self.window - (now - dq[0])))
            return RateVerdict(False, 0, retry)
        dq.append(now)
        # opportunistic prune of empty buckets to bound memory
        if len(self._hits) > 4096:
            for k in [k for k, v in self._hits.items() if not v][:1024]:
                self._hits.pop(k, None)
        return RateVerdict(True, self.limit - len(dq), 0)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
