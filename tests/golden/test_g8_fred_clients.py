"""
G8 — FRED client behaviour, per domain, at the HTTP layer (REFACTOR_SPEC 4.3).

Pins what each domain's FREDClient sends (series, windows, params) and how it
parses, sorts and fails, so merging the eight copies into domains/sources/fred.py
can be checked against the copies themselves rather than against mocks of
their methods.
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import date

import httpx
import pytest

from .snapshot import assert_matches_snapshot

DOMAINS = [
    "macro_regime_v1", "sovereign_debt_v1", "credit_cycle_v1", "energy_regime_v1",
    "labor_market_v1", "crypto_regime_v1", "geopolitics_v1", "sf_urban_v1",
]
END = date(2026, 3, 6)


def _canned(series_id: str) -> dict:
    # Out of order, one missing value ("."), one unparsable value, one bad date.
    seed = sum(map(ord, series_id))
    rows = [{"date": f"2026-0{m}-01", "value": f"{(seed % 97) / 10 + m * 0.25:.2f}"} for m in (2, 3, 1)]
    rows += [{"date": "2025-12-01", "value": "."}, {"date": "2025-11-01", "value": "n/a"},
             {"date": "not-a-date", "value": "1.0"}]
    return {"observations": rows}


def _client(module, handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return module.FREDClient(api_key="test-key", client=http, retry_backoff_s=(0.0, 0.0))


def _run(module) -> dict:
    sent: list[dict] = []

    def ok(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert params.pop("api_key") == "test-key"
        sent.append({"path": request.url.path, **params})
        return httpx.Response(200, json=_canned(params["series_id"]))

    async def go():
        out = {}
        all_series = await _client(module, ok).fetch_all_series(end_date=END)
        out["fetch_all_series"] = {
            sid: [[o.obs_date.isoformat(), o.value, o.series_id] for o in obs]
            for sid, obs in sorted(all_series.items())
        }
        first = sorted(all_series)[0]
        explicit = await _client(module, ok).fetch_series(first, end_date=END, start_date=date(2025, 1, 1), limit=12)
        out["fetch_series_explicit_window"] = [[o.obs_date.isoformat(), o.value] for o in explicit]

        failures = {}
        for name, handler in {
            "http_500": lambda r: httpx.Response(500, json={"error_message": "boom"}),
            "empty": lambda r: httpx.Response(200, json={"observations": []}),
            "all_missing": lambda r: httpx.Response(200, json={"observations": [{"date": "2026-01-01", "value": "."}]}),
            "not_json": lambda r: httpx.Response(200, text="<html>maintenance</html>"),
        }.items():
            try:
                await _client(module, handler).fetch_series(first, end_date=END)
                failures[name] = "no error"
            except Exception as exc:  # noqa: BLE001 — recording what is raised
                failures[name] = type(exc).__name__
        out["failures"] = failures
        try:
            await _client(module, lambda r: httpx.Response(500)).fetch_all_series(end_date=END)
            out["fetch_all_series_when_every_series_fails"] = "no error"
        except Exception as exc:  # noqa: BLE001 — recording what is raised
            out["fetch_all_series_when_every_series_fails"] = type(exc).__name__
        return out

    result = asyncio.run(go())
    result["requests"] = sorted(sent, key=lambda p: (p["series_id"], p["observation_start"], p["limit"]))
    return result


@pytest.mark.parametrize("domain", DOMAINS)
def test_g8_fred_client_matches_golden(domain):
    module = importlib.import_module(f"src.domains.{domain}.ingestion.fred_client")
    assert_matches_snapshot(f"g8_fred_{domain}", _run(module))
