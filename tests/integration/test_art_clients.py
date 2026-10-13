"""The art domain's HTTP clients, against canned responses (httpx.MockTransport)."""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.art_prestige_regime_v1.ingestion.aic_client import AICClient
from src.domains.art_prestige_regime_v1.ingestion.wikipedia_client import WikipediaClient


def test_wikipedia_monthly_views_are_bounded_by_the_target_month():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json={"items": [
            {"timestamp": "2026010100", "views": 120},
            {"timestamp": "2026020100", "views": 90},
        ]})

    client = WikipediaClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    views = asyncio.run(client.monthly_views("Ceramic art", end=date(2026, 2, 28), months=2))

    assert views == [(date(2026, 1, 1), 120), (date(2026, 2, 1), 90)]
    assert seen["url"].endswith("/per-article/en.wikipedia/all-access/user/Ceramic_art/monthly/20260101/20260228")
    assert "probabilistic-ontology-engine" in seen["ua"]  # Wikimedia requires an identifying User-Agent


def test_wikipedia_failure_returns_no_views():
    client = WikipediaClient(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert asyncio.run(client.monthly_views("No such article", end=date(2026, 2, 28), months=3)) == []


def test_aic_counts_acquisitions_matching_any_term():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"pagination": {"total": 61}, "data": []})

    client = AICClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    total = asyncio.run(client.acquisitions(2021, {"classification_titles.keyword": ["ceramics", "textile"]}))

    assert total == 61
    must = seen["body"]["query"]["bool"]["must"]
    assert must[0] == {"term": {"fiscal_year": 2021}}
    assert must[1]["bool"]["should"] == [{"terms": {"classification_titles.keyword": ["ceramics", "textile"]}}]
    assert seen["body"]["limit"] == 0


def test_aic_failure_returns_none():
    client = AICClient(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    assert asyncio.run(client.acquisitions(2021)) is None
