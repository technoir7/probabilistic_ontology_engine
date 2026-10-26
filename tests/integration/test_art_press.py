"""The art press clients (Guardian Open Platform, NYT Archive), against canned
responses: per month, how many art articles there were and how many carry
each tag."""
from __future__ import annotations

import asyncio

import httpx

from src.domains.art_prestige_regime_v1.ingestion.guardian_client import GuardianClient
from src.domains.art_prestige_regime_v1.ingestion.nyt_client import NYTClient
from src.domains.art_prestige_regime_v1.ingestion.tag_counts import MonthCache, TagCounts
from src.domains.sources.rate_limit import RateLimiter


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _guardian_page(page, pages, articles):
    return {"response": {"status": "ok", "pages": pages, "currentPage": page,
                         "results": [{"tags": [{"id": t} for t in tags]} for tags in articles]}}


def test_guardian_counts_every_page_of_a_months_art_section():
    seen = []

    def handler(request):
        q = dict(request.url.params)
        seen.append(q)
        if q["page"] == "1":
            return httpx.Response(200, json=_guardian_page(1, 2, [["artanddesign/painting"], ["artanddesign/painting", "uk/london"]]))
        return httpx.Response(200, json=_guardian_page(2, 2, [[]]))

    client = GuardianClient("k", client=_client(handler), rate_limit=RateLimiter(0), cache=MonthCache())
    got = asyncio.run(client.month(2024, 2))

    assert got == TagCounts(articles=3, tags={"artanddesign/painting": 2, "uk/london": 1})
    assert [q["page"] for q in seen] == ["1", "2"]
    assert seen[0]["section"] == "artanddesign"
    assert (seen[0]["from-date"], seen[0]["to-date"]) == ("2024-02-01", "2024-02-29")
    assert seen[0]["show-tags"] == "keyword"


def test_nyt_counts_the_articles_tagged_art_and_their_other_subjects():
    def kw(*subjects, name="subject"):
        return [{"name": name, "value": s} for s in subjects]

    docs = [
        {"keywords": kw("Art", "Museums")},
        {"keywords": kw("ART", "Auctions ", name="Subject")},   # names and case vary across eras
        {"keywords": kw("Museums")},                           # not an art article
        {"keywords": kw("Art") + [{"name": "glocations", "value": "Paris"}]},
        {"keywords": None},
    ]
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"response": {"docs": docs}})

    client = NYTClient("k", client=_client(handler), rate_limit=RateLimiter(0), cache=MonthCache())
    got = asyncio.run(client.month(2003, 7))

    assert got == TagCounts(articles=3, tags={"museums": 1, "auctions": 1})
    assert seen["path"] == "/svc/archive/v1/2003/7.json"


def test_a_failed_month_is_none_so_it_reads_missing():
    for make in (GuardianClient, NYTClient):
        client = make("k", client=_client(lambda r: httpx.Response(500)), rate_limit=RateLimiter(0), backoff_s=(), cache=MonthCache())
        assert asyncio.run(client.month(2020, 1)) is None


def test_a_throttled_request_is_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"response": {"docs": [{"keywords": [{"name": "subject", "value": "Art"}]}]}})

    client = NYTClient("k", client=_client(handler), rate_limit=RateLimiter(0), backoff_s=(0,), cache=MonthCache())
    assert asyncio.run(client.month(2020, 1)) == TagCounts(articles=1, tags={})
    assert len(calls) == 2


def test_a_share_is_of_the_months_art_articles():
    counts = TagCounts(articles=40, tags={"museums": 10})
    assert counts.share("museums") == 0.25
    assert counts.share("auctions") == 0.0


def test_a_month_read_lately_is_not_asked_for_again_whichever_client_asks():
    # The server opens a new source, so new clients, for every month it fetches.
    calls, now = [], [0.0]

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"response": {"docs": [{"keywords": [{"name": "subject", "value": "Art"}]}]}})

    cache = MonthCache(ttl_s=100, clock=lambda: now[0])
    for _ in range(3):
        asyncio.run(NYTClient("k", client=_client(handler), rate_limit=RateLimiter(0), cache=cache).month(2020, 1))
    assert len(calls) == 1
    now[0] = 101
    asyncio.run(NYTClient("k", client=_client(handler), rate_limit=RateLimiter(0), cache=cache).month(2020, 1))
    assert len(calls) == 2
