"""
Live integration tests — SF urban v1 data sources.

All tests are marked @pytest.mark.live and are SKIPPED in normal CI runs.
Run manually with:
    .venv/bin/python -m pytest tests/ -v -m live

What is verified
----------------
LIVE-SF-01  FRED SANF806INFO (SF information employment) → 200 OK, non-empty obs
LIVE-SF-02  FRED SANF806LEIH (SF leisure & hospitality employment) → 200 OK, non-empty obs
LIVE-SF-03  FRED SANF806NA   (SF total nonfarm employment) → 200 OK, non-empty obs
LIVE-SF-04  SF Gov permits endpoint (i98e-djp9.json) → 200 OK
LIVE-SF-05  SF Gov crime endpoint (wg3w-h783.json) → 200 OK
LIVE-SF-06  SF Gov business registrations (g8m3-pdis.json) → 200 OK

Prerequisites
-------------
FRED_API_KEY must be set (via .env or environment variable).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dotenv import load_dotenv

load_dotenv()

from src.domains.sf_urban_v1.ingestion.fred_client import (
    FREDClient,
    FRED_SERIES,
)
from src.domains.sf_urban_v1.ingestion.sfgov_client import SFGovClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        pytest.skip("FRED_API_KEY not set — skipping live FRED tests")
    return key


_LOOKBACK_DAYS = 730
_END_DATE = date.today()
_START_DATE = _END_DATE - timedelta(days=_LOOKBACK_DAYS)


# ---------------------------------------------------------------------------
# LIVE-SF-01  FRED information sector (SANF806INFO)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_fred_info_employment():
    """SANF806INFO returns 200 and has observations in the 2-year window."""
    series_id = FRED_SERIES["info_emp"]   # SANF806INFO
    assert series_id == "SANF806INFO", f"Unexpected series key: {series_id}"

    async def _run():
        async with FREDClient(api_key=_fred_api_key()) as client:
            return await client.fetch_series(
                series_id, end_date=_END_DATE, start_date=_START_DATE
            )

    obs = asyncio.run(_run())
    assert len(obs) > 0, (
        f"FRED {series_id}: expected non-empty observations for "
        f"{_START_DATE} → {_END_DATE}, got 0"
    )
    # Spot-check structure
    first = obs[0]
    assert first.series_id == series_id
    assert first.value > 0
    assert _START_DATE <= first.obs_date <= _END_DATE


# ---------------------------------------------------------------------------
# LIVE-SF-02  FRED leisure & hospitality (SANF806LEIH)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_fred_leisure_hospitality_employment():
    """SANF806LEIH returns 200 and has observations in the 2-year window."""
    series_id = FRED_SERIES["hospitality_emp"]   # SANF806LEIH
    assert series_id == "SANF806LEIH", f"Unexpected series key: {series_id}"

    async def _run():
        async with FREDClient(api_key=_fred_api_key()) as client:
            return await client.fetch_series(
                series_id, end_date=_END_DATE, start_date=_START_DATE
            )

    obs = asyncio.run(_run())
    assert len(obs) > 0, (
        f"FRED {series_id}: expected non-empty observations for "
        f"{_START_DATE} → {_END_DATE}, got 0"
    )
    first = obs[0]
    assert first.series_id == series_id
    assert first.value > 0
    assert _START_DATE <= first.obs_date <= _END_DATE


# ---------------------------------------------------------------------------
# LIVE-SF-03  FRED total nonfarm employment (SANF806NA)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_fred_total_nonfarm_employment():
    """SANF806NA returns 200 and has observations in the 2-year window."""
    series_id = FRED_SERIES["total_emp"]   # SANF806NA
    assert series_id == "SANF806NA", f"Unexpected series key: {series_id}"

    async def _run():
        async with FREDClient(api_key=_fred_api_key()) as client:
            return await client.fetch_series(
                series_id, end_date=_END_DATE, start_date=_START_DATE
            )

    obs = asyncio.run(_run())
    assert len(obs) > 0, (
        f"FRED {series_id}: expected non-empty observations for "
        f"{_START_DATE} → {_END_DATE}, got 0"
    )
    first = obs[0]
    assert first.series_id == series_id
    assert first.value > 0
    assert _START_DATE <= first.obs_date <= _END_DATE


# ---------------------------------------------------------------------------
# LIVE-SF-04  SF Gov building permits (i98e-djp9.json)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.parametrize("fetch", ["fetch_permits", "fetch_incidents", "fetch_business_openings", "fetch_business_closures"])
def test_live_sfgov_monthly_counts(fetch):
    """
    Each SF Open Data monthly series returns 200 OK with at least 12 complete
    months of counts (what the z-scores need). Previously failed with a 301
    (host moved, B16) and before that returned truncated rows (B13).
    """
    async def _run():
        async with SFGovClient(timeout=30.0) as client:
            return await getattr(client, fetch)()

    rows = asyncio.run(_run())
    months = {r.month for r in rows}
    assert len(months) >= 12, f"{fetch}: only {len(months)} months returned"
    assert all(r.count > 0 for r in rows)
    if fetch == "fetch_permits":
        assert any("office" in r.category for r in rows), "no office permits: proposed_use not returned?"
