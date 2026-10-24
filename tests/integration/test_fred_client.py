"""
domains/sources/fred.py: the shared FRED client.

FRED allows 120 requests a minute per key and answers faster callers with
HTTP 429. A 23 Oct rebuild went over it; since an HTTP error came back as an
empty series, a refused series was recorded as MISSING and a refused week as
having no evidence at all, so outages were learned as ignorance.
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from src.domains.sources.fred import FREDClient, FredHTTPError
from src.domains.sources.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


def _observations(*values: float) -> dict:
    return {"observations": [{"date": f"2026-0{9 - i}-01", "value": str(v)} for i, v in enumerate(values)]}


class TwoSeries(FREDClient):
    SERIES = {"a": "AAA", "b": "BBB"}


def _client(handler, clock: FakeClock, interval_s: float = 0.5, backoff_s=(30.0, 60.0)) -> TwoSeries:
    return TwoSeries(
        api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limit=RateLimiter(interval_s, clock=clock.monotonic, sleep=clock.sleep),
        retry_backoff_s=backoff_s,
    )


def test_a_throttled_request_waits_and_is_retried():
    clock = FakeClock()
    sent_at: list[float] = []
    replies = [httpx.Response(429), httpx.Response(200, json=_observations(3.0, 2.0))]

    def handler(request):
        sent_at.append(clock.now)
        return replies.pop(0)

    obs = asyncio.run(_client(handler, clock).fetch_series("AAA", end_date=date(2026, 9, 30)))

    assert [o.value for o in obs] == [3.0, 2.0]
    assert sent_at[1] - sent_at[0] >= 30.0


def test_retry_after_is_honoured_when_longer_than_the_backoff():
    clock = FakeClock()
    sent_at: list[float] = []
    replies = [httpx.Response(429, headers={"Retry-After": "90"}), httpx.Response(200, json=_observations(1.0))]

    def handler(request):
        sent_at.append(clock.now)
        return replies.pop(0)

    asyncio.run(_client(handler, clock).fetch_series("AAA", end_date=date(2026, 9, 30)))
    assert sent_at[1] - sent_at[0] >= 90.0


def test_a_server_error_that_persists_raises_after_the_retries():
    clock = FakeClock()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with pytest.raises(FredHTTPError) as err:
        asyncio.run(_client(handler, clock).fetch_series("AAA", end_date=date(2026, 9, 30)))
    assert err.value.status == 500
    assert len(calls) == 3  # first try and two retries


def test_a_client_error_is_not_retried():
    clock = FakeClock()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400)

    with pytest.raises(FredHTTPError):
        asyncio.run(_client(handler, clock).fetch_series("AAA", end_date=date(2026, 9, 30)))
    assert len(calls) == 1


def test_requests_are_paced_across_concurrent_series():
    clock = FakeClock()
    sent_at: list[float] = []

    def handler(request):
        sent_at.append(clock.now)
        return httpx.Response(200, json=_observations(1.0))

    asyncio.run(_client(handler, clock, interval_s=0.5).fetch_all_series(end_date=date(2026, 9, 30)))
    assert sorted(sent_at) == [1000.0, 1000.5]


def test_a_series_fred_could_not_serve_fails_the_fetch_instead_of_reading_as_missing():
    clock = FakeClock()

    def handler(request):
        if request.url.params["series_id"] == "BBB":
            return httpx.Response(500)
        return httpx.Response(200, json=_observations(1.0))

    with pytest.raises(FredHTTPError):
        asyncio.run(_client(handler, clock).fetch_all_series(end_date=date(2026, 9, 30)))


def test_a_series_with_no_observations_in_the_window_still_reads_as_missing():
    clock = FakeClock()

    def handler(request):
        if request.url.params["series_id"] == "BBB":
            return httpx.Response(200, json={"observations": []})
        return httpx.Response(200, json=_observations(1.0))

    result = asyncio.run(_client(handler, clock).fetch_all_series(end_date=date(2026, 9, 30)))
    assert result["BBB"] == [] and len(result["AAA"]) == 1
