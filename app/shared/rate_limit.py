from collections import defaultdict
from time import time


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> int | None:
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
