"""
REFACTOR_SPEC B12: SF business data must be "as of" end_date. A business that
opened after end_date, or a closure after end_date, did not exist yet.
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.sf_urban_v1.ingestion.sfgov_client import SFBusinessObs, SFGovClient

AS_OF = date(2026, 3, 1)


def _client(rows: list[dict]) -> SFGovClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/g8m3-pdis.json")
        return httpx.Response(200, json=rows)

    return SFGovClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_businesses_are_reported_as_of_end_date():
    rows = [
        {"location_start_date": "2026-01-10T00:00:00.000"},
        {"location_start_date": "2026-01-15T00:00:00.000", "location_end_date": "2026-02-20T00:00:00.000"},
        {"location_start_date": "2026-01-20T00:00:00.000", "location_end_date": "2026-05-01T00:00:00.000"},
        {"location_start_date": "2026-04-01T00:00:00.000"},
    ]
    result = asyncio.run(_client(rows).fetch_businesses(end_date=AS_OF))

    assert result == [
        SFBusinessObs(start_date=date(2026, 1, 10), end_date=None),
        SFBusinessObs(start_date=date(2026, 1, 15), end_date=date(2026, 2, 20)),
        # Closed after AS_OF: still open as of AS_OF.
        SFBusinessObs(start_date=date(2026, 1, 20), end_date=None),
        # Opened after AS_OF: dropped.
    ]
