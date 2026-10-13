"""
domains/sources/gdelt.py: the shared GDELT DOC timeline client.

B22: GDELT returns {"timeline": [{"series": "<name>", "data": [...points]}]}.
The geopolitics client read the points from "series" (the name string), so it
parsed nothing, and every GDELT signal was empty in production; its test
mocked the same wrong shape. The shape below is a trimmed real response.
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.sources.gdelt import GDELTClient, RateLimiter

REAL_RESPONSE = {
    "query_details": {"title": '"AI-generated" theme:TAX_FNCACT_ARTIST sourcelang:english', "date_resolution": "day"},
    "timeline": [{"series": "Volume Intensity", "data": [
        {"date": "20260928T000000Z", "value": 0.0033},
        {"date": "20260929T000000Z", "value": 0.0044},
        {"date": "20260930T000000Z", "value": 0.0027},
    ]}],
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


def _client(handler, limiter=None) -> GDELTClient:
    clock = FakeClock()
    return GDELTClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limit=limiter or RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep),
    )


def test_parses_the_points_of_a_real_response_newest_first():
    client = _client(lambda r: httpx.Response(200, json=REAL_RESPONSE))
    obs = asyncio.run(client.fetch_timeline("q", "ai", lookback_days=3, end_date=date(2026, 9, 30)))
    assert [(o.obs_date, o.value) for o in obs] == [
        (date(2026, 9, 30), 0.0027), (date(2026, 9, 29), 0.0044), (date(2026, 9, 28), 0.0033),
    ]


def test_the_rate_limit_notice_is_an_empty_result():
    client = _client(lambda r: httpx.Response(200, text="Please limit requests to one every 5 seconds"))
    assert asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30))) == []


def test_clients_sharing_a_limiter_stay_five_seconds_apart():
    clock = FakeClock()
    limiter = RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep)
    sent_at: list[float] = []

    def handler(request):
        sent_at.append(clock.now)
        return httpx.Response(200, json=REAL_RESPONSE)

    # Geopolitics and art each open their own client; GDELT limits the IP.
    a, b = _client(handler, limiter), _client(handler, limiter)

    async def run():
        await asyncio.gather(
            a.fetch_timeline("q1", "a", end_date=date(2026, 9, 30)),
            b.fetch_timeline("q2", "b", end_date=date(2026, 9, 30)),
            a.fetch_timeline("q3", "a", end_date=date(2026, 9, 30)),
        )

    asyncio.run(run())
    gaps = [y - x for x, y in zip(sent_at, sent_at[1:])]
    assert len(sent_at) == 3 and min(gaps) >= 5.0
