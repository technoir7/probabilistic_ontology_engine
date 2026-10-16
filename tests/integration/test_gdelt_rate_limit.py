"""
REFACTOR_SPEC B17: GDELT allows one request every 5 seconds and answers faster
callers with HTTP 200 and a plain-text notice, which the client cannot parse,
so every timeline fired concurrently came back empty.
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.geopolitics_v1.ingestion.gdelt_client import GDELT_QUERIES, GDELTClient
from src.domains.sources.gdelt import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


def _timeline_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"timeline": [{"series": "Volume Intensity", "data": [{"date": "20260301T000000Z", "value": 1.5}]}]})


def test_requests_are_spaced_at_least_five_seconds_apart_across_calls():
    clock = FakeClock()
    sent_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(clock.now)
        return _timeline_response(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GDELTClient(client=http, rate_limit=RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep))

    async def run():
        first = await client.fetch_all(end_date=date(2026, 3, 2))
        second = await client.fetch_all(end_date=date(2026, 3, 9))
        return first, second

    first, second = asyncio.run(run())

    assert len(sent_at) == 2 * len(GDELT_QUERIES)
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:])]
    assert min(gaps) >= 5.0
    assert all(len(v) == 1 for v in first.values())
    assert all(len(v) == 1 for v in second.values())
