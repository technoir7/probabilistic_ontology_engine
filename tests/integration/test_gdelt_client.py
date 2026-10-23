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

from src.domains.sources.gdelt import GDELTClient, RateLimiter, TimelineCache

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
        cache=TimelineCache(),
    )


def test_parses_the_points_of_a_real_response_newest_first():
    client = _client(lambda r: httpx.Response(200, json=REAL_RESPONSE))
    obs = asyncio.run(client.fetch_timeline("q", "ai", lookback_days=3, end_date=date(2026, 9, 30)))
    assert [(o.obs_date, o.value) for o in obs] == [
        (date(2026, 9, 30), 0.0027), (date(2026, 9, 29), 0.0044), (date(2026, 9, 28), 0.0033),
    ]


NOTICE = "Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com for larger queries."


def _replies(*responses):
    """A handler that answers with *responses* in turn and records when each request arrived."""
    clock = FakeClock()
    sent_at: list[float] = []
    queue = list(responses)

    def handler(request):
        sent_at.append(clock.now)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    limiter = RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep)
    return _client(handler, limiter), sent_at


def _fetch(client):
    return asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30)))


def test_a_throttled_request_is_retried_after_backing_off():
    # Live runs from a dev machine and from Railway: most requests came back
    # 429 even at one per 5 s, and giving up left those months MISSING.
    client, sent_at = _replies(httpx.Response(429), httpx.Response(200, json=REAL_RESPONSE))
    assert len(_fetch(client)) == 3
    assert len(sent_at) == 2 and sent_at[1] - sent_at[0] >= 30.0


def test_the_rate_limit_notice_counts_as_throttled():
    client, sent_at = _replies(httpx.Response(200, text=NOTICE), httpx.Response(200, json=REAL_RESPONSE))
    assert len(_fetch(client)) == 3 and len(sent_at) == 2


def test_a_longer_retry_after_is_honoured():
    client, sent_at = _replies(httpx.Response(429, headers={"Retry-After": "90"}), httpx.Response(200, json=REAL_RESPONSE))
    _fetch(client)
    assert sent_at[1] - sent_at[0] >= 90.0


def test_gives_up_with_an_empty_result_after_the_last_backoff():
    client, sent_at = _replies(*[httpx.Response(429)] * 4)
    assert _fetch(client) == []
    assert len(sent_at) == 4


def _dropped():
    return httpx.RemoteProtocolError("Server disconnected without sending a response.")


def test_a_dropped_connection_is_retried_like_a_throttle():
    # The live test of every domain (2026-10-23): GDELT closed the connection
    # without answering, and geopolitics lost three of its eight signals.
    client, sent_at = _replies(_dropped(), httpx.Response(200, json=REAL_RESPONSE))
    assert len(_fetch(client)) == 3
    assert len(sent_at) == 2 and sent_at[1] - sent_at[0] >= 30.0


def test_gives_up_on_a_connection_that_keeps_dropping():
    client, sent_at = _replies(*[_dropped()] * 4)
    assert _fetch(client) == []
    assert len(sent_at) == 4


def test_other_errors_are_not_retried():
    client, sent_at = _replies(httpx.Response(500))
    assert _fetch(client) == [] and len(sent_at) == 1


def test_a_throttle_holds_back_every_client_sharing_the_limiter():
    clock = FakeClock()
    limiter = RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep)
    queue = [httpx.Response(429), httpx.Response(200, json=REAL_RESPONSE), httpx.Response(200, json=REAL_RESPONSE)]
    sent: list[tuple[str, float]] = []

    def handler(request):
        sent.append((request.url.params["query"], clock.now))
        return queue.pop(0)

    a, b = _client(handler, limiter), _client(handler, limiter)

    async def run():
        await a.fetch_timeline("first", "a", end_date=date(2026, 9, 30))
        await b.fetch_timeline("second", "b", end_date=date(2026, 9, 30))

    asyncio.run(run())
    # GDELT penalises the IP, so the other client waits out the backoff too.
    assert [q for q, _ in sent] == ["first", "first", "second"]
    assert sent[1][1] - sent[0][1] >= 30.0


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


def _counting_client(responses, cache):
    sent: list[str] = []
    queue = list(responses)

    def handler(request):
        sent.append(request.url.params["enddatetime"])
        return queue.pop(0)

    clock = FakeClock()
    client = GDELTClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limit=RateLimiter(5.0, clock=clock.monotonic, sleep=clock.sleep),
        cache=cache,
    )
    return client, sent


def test_an_identical_request_is_answered_from_the_shared_cache():
    clock = FakeClock()
    cache = TimelineCache(ttl_s=3600, clock=clock.monotonic)
    # The art pipeline opens new clients for every month; the cache is shared.
    a, sent = _counting_client([httpx.Response(200, json=REAL_RESPONSE)], cache)
    b, _ = _counting_client([], cache)
    first = asyncio.run(a.fetch_timeline("q", "x", lookback_days=3, end_date=date(2026, 9, 30)))
    second = asyncio.run(b.fetch_timeline("q", "x", lookback_days=3, end_date=date(2026, 9, 30)))
    assert first == second and len(first) == 3 and len(sent) == 1


def test_a_different_request_or_an_expired_entry_goes_to_gdelt():
    clock = FakeClock()
    cache = TimelineCache(ttl_s=3600, clock=clock.monotonic)
    client, sent = _counting_client([httpx.Response(200, json=REAL_RESPONSE)] * 3, cache)
    asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30)))
    asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 29)))
    clock.now += 3601
    asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30)))
    assert len(sent) == 3


def test_failures_are_not_cached():
    cache = TimelineCache()
    client, sent = _counting_client([httpx.Response(500), httpx.Response(200, json=REAL_RESPONSE)], cache)
    assert asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30))) == []
    assert len(asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, 30)))) == 3
    assert len(sent) == 2


def test_the_cache_keeps_only_the_newest_entries():
    cache = TimelineCache(max_entries=2)
    client, sent = _counting_client([httpx.Response(200, json=REAL_RESPONSE)] * 4, cache)
    for day in (28, 29, 30, 28):
        asyncio.run(client.fetch_timeline("q", "x", end_date=date(2026, 9, day)))
    assert len(sent) == 4  # the 28th was evicted by the 30th
