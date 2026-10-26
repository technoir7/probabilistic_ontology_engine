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

def _cma_handler(pages, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        seen.append(q)
        skip = int(q["skip"])
        return httpx.Response(200, json={"info": {"total": 3}, "data": pages[skip]})
    return handler


def test_cma_counts_distinct_artists_by_the_year_in_the_accession_number():
    from src.domains.art_prestige_regime_v1.ingestion.cma_client import CMAClient, HeldCollection

    pages = {
        0: [{"accession_number": "2019.12", "creators": [{"id": 1}, {"id": 2}]},
            {"accession_number": "2019.13.a", "creators": [{"id": 1}]}],
        2: [{"accession_number": "1980.238.1", "creators": [{"id": 9}]},
            {"accession_number": "TR.2019.5", "creators": [{"id": 3}]}],   # not an accession year
    }
    seen = []
    held = HeldCollection()

    def client():
        return CMAClient(client=httpx.AsyncClient(transport=httpx.MockTransport(_cma_handler(pages, seen))),
                         page_size=2, cache=held)

    assert asyncio.run(client().artists_by_year()) == {2019: 2, 1980: 1}
    assert [q["skip"] for q in seen] == ["0", "2"]
    assert asyncio.run(client().artists_by_year()) == {2019: 2, 1980: 1}
    assert len(seen) == 2   # a new source, as the server opens for every month, reads it once


def test_cma_failure_returns_none():
    from src.domains.art_prestige_regime_v1.ingestion.cma_client import CMAClient, HeldCollection

    client = CMAClient(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
                       cache=HeldCollection())
    assert asyncio.run(client.artists_by_year()) is None
