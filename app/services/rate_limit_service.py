from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from app.core.exceptions import AppError


class RateLimitService:
    """
    Simple in-memory limiter for MVP use.
    Replace with Redis or a distributed limiter in production.
    """

    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls_per_minute = max_calls_per_minute
        self._calls: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check_call_allowed(self, bucket: str = "global") -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        async with self._lock:
            queue = self._calls[bucket]
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self.max_calls_per_minute:
                raise AppError(
                    "RATE_LIMIT_EXCEEDED",
                    f"Maximum of {self.max_calls_per_minute} test calls per minute exceeded.",
                    status_code=429,
                )
            queue.append(datetime.now(timezone.utc))
