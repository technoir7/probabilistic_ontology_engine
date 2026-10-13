"""The art domain's HTTP clients, against canned responses (httpx.MockTransport)."""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.art_prestige_regime_v1.ingestion.aic_client import AICClient, Acquisitions


def test_aic_counts_objects_and_distinct_artists_of_some_types():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"pagination": {"total": 61}, "data": [],
                                         "aggregations": {"artists": {"value": 23}}})

    client = AICClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    got = asyncio.run(client.acquisitions(2021, artwork_types=["Ceramics", "Textile"]))

    assert got == Acquisitions(objects=61, artists=23)
    assert seen["body"]["query"]["bool"]["filter"] == [
        {"term": {"fiscal_year": 2021}},
        {"terms": {"artwork_type_title.keyword": ["Ceramics", "Textile"]}},
    ]
    assert seen["body"]["aggs"] == {"artists": {"cardinality": {"field": "artist_id"}}}
    assert seen["body"]["limit"] == 0


def test_aic_failure_returns_none():
    client = AICClient(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    assert asyncio.run(client.acquisitions(2021)) is None