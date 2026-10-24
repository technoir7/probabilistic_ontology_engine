"""
A request pacer shared by every client of one upstream API. Upstream limits
are per IP or per key, not per client object, so the pacer is process-wide:
each source module holds one and every client of that source waits on it.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class RateLimiter:
    """At most one call per *interval_s*, across every caller sharing it."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._next_slot: float | None = None

    async def wait(self) -> None:
        # Reserve the slot before awaiting, so concurrent callers queue in turn.
        now = self._clock()
        slot = now if self._next_slot is None else max(now, self._next_slot)
        self._next_slot = slot + self._interval
        if slot > now:
            await self._sleep(slot - now)

    def defer(self, seconds: float) -> None:
        """Hold every caller sharing this limiter for at least *seconds* from now."""
        until = self._clock() + seconds
        self._next_slot = until if self._next_slot is None else max(self._next_slot, until)
