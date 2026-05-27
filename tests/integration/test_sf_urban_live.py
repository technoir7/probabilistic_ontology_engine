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
def test_live_sfgov_permits():
    """SF Gov permits endpoint returns 200 OK and non-empty records."""
    async def _run():
        async with SFGovClient(timeout=30.0) as client:
            return await client.fetch_permits(lookback_days=365)

    permits = asyncio.run(_run())
    assert len(permits) > 0, (
        "SF Gov permits (i98e-djp9.json): expected non-empty results, got 0 — "
        "check endpoint availability and column names"
    )
    # Spot-check a record
    first = permits[0]
    assert first.filed_date is not None
    assert isinstance(first.permit_type, str)


# ---------------------------------------------------------------------------
# LIVE-SF-05  SF Gov crime / police incidents (wg3w-h783.json)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_sfgov_crime():
    """SF Gov crime endpoint returns 200 OK and non-empty records."""
    async def _run():
        async with SFGovClient(timeout=30.0) as client:
            return await client.fetch_incidents(lookback_days=365)

    incidents = asyncio.run(_run())
    assert len(incidents) > 0, (
        "SF Gov crime (wg3w-h783.json): expected non-empty results, got 0 — "
        "check endpoint availability and column names"
    )
    first = incidents[0]
    assert first.incident_date is not None
    assert isinstance(first.category, str)


# ---------------------------------------------------------------------------
# LIVE-SF-06  SF Gov business registrations (g8m3-pdis.json)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_live_sfgov_business_registrations():
    """SF Gov business registrations endpoint returns 200 OK and non-empty records.

    This endpoint previously failed with HTTP 400 due to wrong column names
    (lic_start_dt / lic_end_dt).  The fix uses location_start_date /
    location_end_date with a proper ISO datetime filter.
    """
    async def _run():
        async with SFGovClient(timeout=30.0) as client:
            return await client.fetch_businesses(lookback_days=365)

    businesses = asyncio.run(_run())
    assert len(businesses) > 0, (
        "SF Gov businesses (g8m3-pdis.json): expected non-empty results, got 0 — "
        "check column names (location_start_date / location_end_date) and "
        "Socrata SoQL datetime filter syntax"
    )
    first = businesses[0]
    assert first.start_date is not None
    # end_date may be None (still-active business) — just check the type
    assert first.end_date is None or isinstance(first.end_date, date)
