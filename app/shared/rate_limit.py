from collections import defaultdict
from time import time


class InMemoryRateLimiter:
    """Per-process in-memory rate limiter.

    NOTE: This limiter is per-process and does NOT coordinate across uvicorn
    workers. In a multi-worker deployment each worker maintains its own counter,
    so the effective limit is ``max_requests * worker_count``.

    To make limits accurate across workers, replace with a Redis-backed
    counter (e.g. ``redis-py`` + ``INCR`` + ``EXPIRE``) or a database-backed
    approach using SQLite's WAL mode for concurrent reads.
    """

    EVICT_EVERY = 100

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = defaultdict(list)
        self._check_count = 0

    def _evict_stale(self) -> None:
        now = time()
        window_start = now - self.window_seconds
        stale = [key for key, records in self._records.items() if not any(t >= window_start for t in records)]
        for key in stale:
            del self._records[key]

    def check(self, key: str) -> int | None:
        self._check_count += 1
        if self._check_count % self.EVICT_EVERY == 0:
            self._evict_stale()

        now = time()
        window_start = now - self.window_seconds
        records = [timestamp for timestamp in self._records[key] if timestamp >= window_start]

        if len(records) >= self.max_requests:
            oldest_within_window = records[0]
            retry_after = int((oldest_within_window + self.window_seconds) - now)
            self._records[key] = records
            return max(retry_after, 1)

        records.append(now)
        self._records[key] = records
        return None
