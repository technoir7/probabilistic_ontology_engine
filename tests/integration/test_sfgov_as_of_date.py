"""
REFACTOR_SPEC B12/B13: SF Open Data is read as of the target date and in
monthly counts. Every query is bounded above by end_date (a backfill must not
see later records) and aggregated server-side (no row cap truncating it).
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from src.domains.sf_urban_v1.ingestion.sfgov_client import MonthlyCount, SFGovClient

AS_OF = date(2026, 3, 1)


def test_every_query_is_bounded_by_end_date_and_aggregated():
    seen: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        dataset = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        seen[f"{dataset} {params['$select']}"] = params
        rows = [{"month": "2026-01-01T00:00:00.000", "n": "12"}, {"month": "2026-02-01T00:00:00.000", "n": "7"}]
        if "proposed_use" in params["$select"]:
            rows = [{**r, "proposed_use": "office"} for r in rows]
        return httpx.Response(200, json=rows)

    client = SFGovClient(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    data = asyncio.run(client.fetch_all(end_date=AS_OF))

    assert len(seen) == 4
    for params in seen.values():
        assert params["$where"].endswith(f"and '{AS_OF.isoformat()}T23:59:59'")
        assert "count(*)" in params["$select"] and params["$group"].startswith("month")
    assert data["permits"][0] == MonthlyCount(month=date(2026, 1, 1), count=12, category="office")
    assert data["business_closures"] == [MonthlyCount(date(2026, 1, 1), 12), MonthlyCount(date(2026, 2, 1), 7)]
