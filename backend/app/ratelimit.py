"""In-memory sliding-window rate limiter (single instance, no external store)."""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable

class RateLimiter:
    """Allows `limit` hits per key per `window_sec`. A limit of 0 disables limiting."""

    def __init__(
        self,
        limit: int,
        window_sec: int = 3600,
        max_keys: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_sec
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, deque[float]] = {}

    def acquire(self, keys: list[str]) -> int:
        """Record one hit for every key.

        Returns 0 if allowed. Otherwise returns the number of seconds to wait; in that case
        nothing is recorded for any key (a blocked request does not extend the penalty).
        """
        if self._limit <= 0:
            return 0
        now = self._clock()
        retry_after = 0
        for key in keys:
            bucket = self._buckets.get(key)
            if bucket is None:
                continue
            self._trim(bucket, now)
            if len(bucket) >= self._limit:
                wait = math.ceil(bucket[0] + self._window - now)
                retry_after = max(retry_after, max(wait, 1))
        if retry_after:
            return retry_after
        for key in keys:
            self._buckets.setdefault(key, deque()).append(now)
        if len(self._buckets) > self._max_keys:
            self.prune()
        return 0

    def prune(self) -> None:
        """Drop expired buckets; if still too many keys, drop the least recently used ones."""
        now = self._clock()
        for key in list(self._buckets):
            bucket = self._buckets[key]
            self._trim(bucket, now)
            if not bucket:
                del self._buckets[key]
        overflow = len(self._buckets) - int(self._max_keys * 0.9)
        if overflow > 0:
            oldest_first = sorted(self._buckets, key=lambda k: self._buckets[k][-1])
            for key in oldest_first[:overflow]:
                del self._buckets[key]

    def _trim(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
