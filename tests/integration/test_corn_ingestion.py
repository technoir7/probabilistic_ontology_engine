"""
Integration tests — corn (ZC) domain ingestion pipeline.

External data sources are mocked; no network calls are made.

Test inventory
--------------
TEST-ZC-01  build_evidence_record maps all 4 variable UUIDs correctly
TEST-ZC-02  PlantingDelayed=True when progress is >5 pp behind 5-yr average
TEST-ZC-03  PlantingDelayed=False when progress is within threshold
TEST-ZC-04  DroughtIndex=True when GOOD+EXCELLENT < 55%
TEST-ZC-05  DroughtIndex=False when GOOD+EXCELLENT ≥ 55%
TEST-ZC-06  YieldForecastDown=True when current forecast < prior year final
TEST-ZC-07  YieldForecastDown=False when current forecast ≥ prior year final
TEST-ZC-10  CornPriceUp=True when settle > 20-day rolling average
TEST-ZC-11  CornPriceUp=False when settle ≤ 20-day rolling average
TEST-ZC-12  Off-season NASS data → MISSING missingness and confidence=0.0
TEST-ZC-13  In-season NASS observed data → confidence=1.0
TEST-ZC-14  Price assignment always OBSERVED with confidence=1.0
TEST-ZC-15  USDANASSClient.build_snapshot parses raw API rows correctly
TEST-ZC-16  Full async pipeline fetch_evidence with mocked clients
"""
from __future__ import annotations

import asyncio
import sys
import os
from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd
import pytest

from src.domains.corn_v1.domain import get_variables
from src.domains.corn_v1.ingestion import nasdaq_client as corn_nasdaq_client
from src.domains.corn_v1.ingestion.nasdaq_client import (
    CornNASDAQSnapshot,
    NASDAQClient,
)
from src.domains.corn_v1.ingestion.pipeline import CornPipeline
from src.domains.corn_v1.ingestion.usda_nass_client import (
    CornNASSSnapshot,
    USDANASSClient,
)
from src.engine.schemas import MissingnessType


# ---------------------------------------------------------------------------
# Shared dates and constants
# ---------------------------------------------------------------------------

# May 18 2025 = ISO week 20; planting season is active; growing season starting
_MAY_18_2025 = date(2025, 5, 18)
# January = off-season for NASS (no planting progress or crop conditions)
_JAN_10_2025 = date(2025, 1, 10)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_nass_snapshot(
    *,
    target_date: date = _MAY_18_2025,
    planting_progress_pct: float | None = 75.0,
    planting_5yr_avg_pct: float | None = 85.0,
    condition_good_exc_pct: float | None = 50.0,
    yield_forecast_bu_ac: float | None = 178.0,
    yield_prior_year_bu_ac: float | None = 183.1,
) -> CornNASSSnapshot:
    """Build a CornNASSSnapshot fixture with derived booleans computed."""
    planting_delayed = (
        planting_progress_pct is not None
        and planting_5yr_avg_pct is not None
        and planting_progress_pct < planting_5yr_avg_pct - 5.0
    )
    drought_index = (
        condition_good_exc_pct is not None
        and condition_good_exc_pct < 55.0
    )
    yield_forecast_down = (
        yield_forecast_bu_ac is not None
        and yield_prior_year_bu_ac is not None
        and yield_forecast_bu_ac < yield_prior_year_bu_ac
    )
    return CornNASSSnapshot(
        target_date=target_date,
        planting_progress_pct=planting_progress_pct,
        planting_5yr_avg_pct=planting_5yr_avg_pct,
        condition_good_exc_pct=condition_good_exc_pct,
        yield_forecast_bu_ac=yield_forecast_bu_ac,
        yield_prior_year_bu_ac=yield_prior_year_bu_ac,
        planting_delayed=planting_delayed,
        drought_index=drought_index,
        yield_forecast_down=yield_forecast_down,
    )


def _make_nasdaq_snapshot(
    *,
    target_date: date = _MAY_18_2025,
    settle_cents: float = 540.25,
    avg_cents: float = 520.0,
) -> CornNASDAQSnapshot:
    return CornNASDAQSnapshot(
        target_date=target_date,
        settle_cents_per_bushel=settle_cents,
        rolling_20d_avg_cents=avg_cents,
        price_up=settle_cents > avg_cents,
    )


def _assignment_map(record) -> dict:
    """Return {variable_id: ObservedAssignment} for easy lookup."""
    return {a.variable_id: a for a in record.observed_assignments}


# ---------------------------------------------------------------------------
# TEST-ZC-01 — UUID mapping
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    """All four assignments carry the canonical variable UUIDs from get_variables()."""
    variables = get_variables()
    nass   = _make_nass_snapshot()
    nasdaq = _make_nasdaq_snapshot()

    record = CornPipeline.build_evidence_record(nass, nasdaq)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    expected_ids   = {v.variable_id for v in variables.values()}

    assert assignment_ids == expected_ids, (
        f"Assignment IDs do not match canonical variable IDs.\n"
        f"  got:      {assignment_ids}\n"
        f"  expected: {expected_ids}"
    )


# ---------------------------------------------------------------------------
# TEST-ZC-02 / TEST-ZC-03 — PlantingDelayed
# ---------------------------------------------------------------------------

def test_planting_delayed_when_behind_5yr_avg():
    """
    progress=75, 5yr_avg=85 → delay = 10 pp > threshold 5 pp → PlantingDelayed=True.
    """
    variables = get_variables()
    nass   = _make_nass_snapshot(planting_progress_pct=75.0, planting_5yr_avg_pct=85.0)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["PlantingDelayed"].variable_id].observed_value is True


def test_planting_on_pace_when_within_threshold():
    """
    progress=82, 5yr_avg=85 → delay = 3 pp < threshold 5 pp → PlantingDelayed=False.
    """
    variables = get_variables()
    nass   = _make_nass_snapshot(planting_progress_pct=82.0, planting_5yr_avg_pct=85.0)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["PlantingDelayed"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-ZC-04 / TEST-ZC-05 — DroughtIndex
# ---------------------------------------------------------------------------

def test_drought_index_when_below_threshold():
    """condition_good_exc_pct=50 < 55 → DroughtIndex=True."""
    variables = get_variables()
    nass   = _make_nass_snapshot(condition_good_exc_pct=50.0)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["DroughtIndex"].variable_id].observed_value is True


def test_no_drought_when_above_threshold():
    """condition_good_exc_pct=62 ≥ 55 → DroughtIndex=False."""
    variables = get_variables()
    nass   = _make_nass_snapshot(condition_good_exc_pct=62.0)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["DroughtIndex"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-ZC-06 / TEST-ZC-07 — YieldForecastDown
# ---------------------------------------------------------------------------

def test_yield_forecast_down_when_below_prior_year():
    """forecast=178.0 < prior=183.1 → YieldForecastDown=True."""
    variables = get_variables()
    nass   = _make_nass_snapshot(yield_forecast_bu_ac=178.0, yield_prior_year_bu_ac=183.1)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["YieldForecastDown"].variable_id].observed_value is True


def test_yield_not_down_when_above_prior_year():
    """forecast=185.0 > prior=183.1 → YieldForecastDown=False."""
    variables = get_variables()
    nass   = _make_nass_snapshot(yield_forecast_bu_ac=185.0, yield_prior_year_bu_ac=183.1)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)
    assert amap[variables["YieldForecastDown"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-ZC-10 / TEST-ZC-11 — CornPriceUp (via yfinance snapshot builder)
# ---------------------------------------------------------------------------

def _make_zc1_history(latest_settle: float, prior_settle: float, n_prior: int = 20) -> pd.DataFrame:
    """Build mock yfinance ZC=F daily price history in chronological order."""
    prices = [prior_settle] * n_prior + [latest_settle]
    return pd.DataFrame(
        {"Close": prices},
        index=pd.date_range(end="2025-05-18", periods=len(prices), freq="D"),
    )


def test_corn_price_up_when_settle_above_avg():
    """settle=540.25, 20d avg=520.0 → CornPriceUp=True."""
    history = _make_zc1_history(latest_settle=540.25, prior_settle=520.0, n_prior=20)
    snap = NASDAQClient.build_snapshot(_MAY_18_2025, history)
    assert snap.price_up is True
    assert snap.settle_cents_per_bushel == 540.25
    assert abs(snap.rolling_20d_avg_cents - 520.0) < 0.01


def test_corn_price_not_up_when_settle_below_avg():
    """settle=500.0, 20d avg=520.0 → CornPriceUp=False."""
    history = _make_zc1_history(latest_settle=500.0, prior_settle=520.0, n_prior=20)
    snap = NASDAQClient.build_snapshot(_MAY_18_2025, history)
    assert snap.price_up is False


# ---------------------------------------------------------------------------
# TEST-ZC-12 — Off-season NASS data yields MISSING assignments
# ---------------------------------------------------------------------------

def test_off_season_nass_yields_missing_assignments():
    """
    When NASS data is unavailable (all None — January is off-season):
        PlantingDelayed  → MissingnessType.MISSING, confidence=0.0, value=False
        DroughtIndex     → MissingnessType.MISSING, confidence=0.0
        YieldForecastDown → MissingnessType.MISSING, confidence=0.0
    """
    variables = get_variables()
    nass = _make_nass_snapshot(
        target_date=_JAN_10_2025,
        planting_progress_pct=None,
        planting_5yr_avg_pct=None,
        condition_good_exc_pct=None,
        yield_forecast_bu_ac=None,
        yield_prior_year_bu_ac=None,
    )
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap = _assignment_map(record)

    for var_name in ("PlantingDelayed", "DroughtIndex", "YieldForecastDown"):
        a = amap[variables[var_name].variable_id]
        assert a.missingness == MissingnessType.MISSING, (
            f"{var_name} should be MISSING but got {a.missingness}"
        )
        assert a.confidence == 0.0, (
            f"{var_name} missing confidence should be 0.0 but got {a.confidence}"
        )
        assert a.observed_value is False, (
            f"{var_name} missing value should default to False but got {a.observed_value}"
        )


# ---------------------------------------------------------------------------
# TEST-ZC-13 — In-season NASS data is OBSERVED with confidence=1.0
# ---------------------------------------------------------------------------

def test_in_season_nass_observed_and_confident():
    """
    When NASS data is available, assignments carry soft evidence (SOFT_OBSERVED)
    with confidence=1.0 and a valid probability distribution.
    The hard boolean MAP value is preserved in observed_value.
    """
    variables = get_variables()
    nass   = _make_nass_snapshot()   # all fields populated
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)

    for var_name in ("PlantingDelayed", "DroughtIndex", "YieldForecastDown"):
        a = amap[variables[var_name].variable_id]
        assert a.missingness == MissingnessType.SOFT_OBSERVED, (
            f"{var_name} should be SOFT_OBSERVED but got {a.missingness}"
        )
        assert a.confidence == 1.0
        assert a.probabilities is not None, f"{var_name} should have probabilities"
        total = sum(a.probabilities.values())
        assert abs(total - 1.0) < 0.02, (
            f"{var_name} probabilities should sum to 1.0, got {total:.4f}"
        )


# ---------------------------------------------------------------------------
# TEST-ZC-14 — Price data is always OBSERVED with confidence=1.0
# ---------------------------------------------------------------------------

def test_price_always_observed_and_confident():
    """
    CornPriceUp is always SOFT_OBSERVED (sigmoid-calibrated), confidence=1.0.
    The hard boolean MAP remains in observed_value.
    """
    variables = get_variables()
    # Use off-season NASS (would be MISSING) — price should still be soft-observed
    nass   = _make_nass_snapshot(planting_progress_pct=None, condition_good_exc_pct=None, yield_forecast_bu_ac=None)
    record = CornPipeline.build_evidence_record(nass, _make_nasdaq_snapshot())
    amap   = _assignment_map(record)

    a = amap[variables["CornPriceUp"].variable_id]
    assert a.missingness == MissingnessType.SOFT_OBSERVED
    assert a.confidence == 1.0
    assert a.probabilities is not None
    assert abs(sum(a.probabilities.values()) - 1.0) < 0.02


# ---------------------------------------------------------------------------
# TEST-ZC-15 — USDANASSClient.build_snapshot parses raw rows correctly
# ---------------------------------------------------------------------------

def _make_nass_planting_rows(current_year: int) -> list[dict]:
    """
    Current year: week 20, 75% planted.
    Prior 5 years: week 20, values 83/84/85/86/87 → avg=85.
    ISO week 20 dates (Sunday ends):
      2025-05-18, 2024-05-19, 2023-05-21, 2022-05-22, 2021-05-23, 2020-05-17
    """
    rows = [
        {"year": str(current_year), "week_ending": "2025-05-18", "unit_desc": "PCT PLANTED", "Value": "75"},
        {"year": str(current_year - 1), "week_ending": "2024-05-19", "unit_desc": "PCT PLANTED", "Value": "83"},
        {"year": str(current_year - 2), "week_ending": "2023-05-21", "unit_desc": "PCT PLANTED", "Value": "84"},
        {"year": str(current_year - 3), "week_ending": "2022-05-22", "unit_desc": "PCT PLANTED", "Value": "85"},
        {"year": str(current_year - 4), "week_ending": "2021-05-23", "unit_desc": "PCT PLANTED", "Value": "86"},
        {"year": str(current_year - 5), "week_ending": "2020-05-17", "unit_desc": "PCT PLANTED", "Value": "87"},
    ]
    return rows


def _make_nass_condition_rows(current_year: int) -> list[dict]:
    """Current year week 20: GOOD=40%, EXCELLENT=10% → sum=50 < 55 → drought=True."""
    return [
        {"year": str(current_year), "week_ending": "2025-05-18", "unit_desc": "PCT GOOD",      "Value": "40"},
        {"year": str(current_year), "week_ending": "2025-05-18", "unit_desc": "PCT EXCELLENT",  "Value": "10"},
    ]


def _make_nass_yield_rows(current_year: int) -> list[dict]:
    """2024 final=183.1; 2025 June forecast=178.0 → down=True."""
    return [
        {"year": str(current_year - 1), "unit_desc": "BU / ACRE", "Value": "183.1"},  # prior year final
        {"year": str(current_year),     "unit_desc": "BU / ACRE", "Value": "178.0"},  # current forecast
    ]


def test_nass_snapshot_builder_from_raw_rows():
    """
    USDANASSClient.build_snapshot correctly parses all three NASS row types.
    Setup:
        planting: current=75, 5yr avg=85 → PlantingDelayed=True
        conditions: GOOD+EXCELLENT=50 < 55 → DroughtIndex=True
        yield: 178.0 < 183.1 → YieldForecastDown=True
    """
    year = 2025
    target = _MAY_18_2025

    planting_rows  = _make_nass_planting_rows(year)
    condition_rows = _make_nass_condition_rows(year)
    yield_rows     = _make_nass_yield_rows(year)

    snap = USDANASSClient.build_snapshot(target, planting_rows, condition_rows, yield_rows)

    assert snap.planting_progress_pct == 75.0
    assert snap.planting_5yr_avg_pct is not None
    assert abs(snap.planting_5yr_avg_pct - 85.0) < 0.01,  \
        f"Expected 5yr avg ≈ 85, got {snap.planting_5yr_avg_pct}"
    assert snap.planting_delayed is True

    assert snap.condition_good_exc_pct == 50.0
    assert snap.drought_index is True

    assert snap.yield_forecast_bu_ac == 178.0
    assert snap.yield_prior_year_bu_ac == 183.1
    assert snap.yield_forecast_down is True


# ---------------------------------------------------------------------------
# TEST-ZC-16 — Full async pipeline with all 3 mocked httpx clients
# ---------------------------------------------------------------------------

def _make_http_response(json_body: dict) -> MagicMock:
    """Build a mock httpx response that returns json_body."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_body)
    return resp


def _nass_get_side_effect(year: int):
    """
    Route NASS API calls by statisticcat_desc param.
    Returns different mock responses for PROGRESS / CONDITION / YIELD.
    """
    planting_body = {
        "data": _make_nass_planting_rows(year)
    }
    condition_body = {
        "data": _make_nass_condition_rows(year)
    }
    yield_body = {
        "data": _make_nass_yield_rows(year)
    }

    def side_effect(url, **kwargs):
        params = kwargs.get("params", {})
        stat_cat = params.get("statisticcat_desc", "")
        if stat_cat == "PROGRESS":
            return _make_http_response(planting_body)
        elif stat_cat == "CONDITION":
            return _make_http_response(condition_body)
        elif stat_cat == "YIELD":
            return _make_http_response(yield_body)
        else:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"data": []})
            return resp

    return side_effect


def _make_zc1_yfinance_history() -> pd.DataFrame:
    """yfinance ZC=F: latest=540.25, 20d avg=520.0 → CornPriceUp=True."""
    return _make_zc1_history(latest_settle=540.25, prior_settle=520.0, n_prior=20)


def test_fetch_evidence_full_async(monkeypatch):
    """
    End-to-end test of CornPipeline.fetch_evidence() with external data
    sources mocked. No real network calls are made.

    Setup:
        NASS planting: 75% current vs 85% 5yr avg → PlantingDelayed=True
        NASS conditions: 50% good/exc < 55 threshold → DroughtIndex=True
        NASS yield: 178.0 < 183.1 prior year → YieldForecastDown=True
        yfinance: 540.25 close > 520.0 avg → CornPriceUp=True
    """
    variables = get_variables()
    year = _MAY_18_2025.year

    # --- mock NASS client ---
    nass_http_mock = AsyncMock()
    nass_http_mock.get = AsyncMock(side_effect=_nass_get_side_effect(year))
    nass = USDANASSClient(api_key="", client=nass_http_mock)

    # --- mock yfinance price client ---
    yfinance_download_mock = MagicMock(return_value=_make_zc1_yfinance_history())
    monkeypatch.setattr(corn_nasdaq_client.yf, "download", yfinance_download_mock)
    nasdaq = NASDAQClient()

    # --- run async pipeline ---
    pipeline = CornPipeline(nass, nasdaq)
    record = asyncio.run(pipeline.fetch_evidence(_MAY_18_2025))

    # --- structural checks ---
    assert len(record.observed_assignments) == 4
    amap = _assignment_map(record)
    assert set(amap.keys()) == {v.variable_id for v in variables.values()}

    # --- value checks ---
    assert amap[variables["PlantingDelayed"].variable_id].observed_value  is True
    assert amap[variables["DroughtIndex"].variable_id].observed_value     is True
    assert amap[variables["YieldForecastDown"].variable_id].observed_value is True
    assert amap[variables["CornPriceUp"].variable_id].observed_value       is True

    # --- missingness / confidence ---
    # In-season NASS and price assignments are now SOFT_OBSERVED with
    # sigmoid-calibrated probability distributions.
    for var_name in ("PlantingDelayed", "DroughtIndex", "YieldForecastDown"):
        a = amap[variables[var_name].variable_id]
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.confidence == 1.0
        assert a.probabilities is not None

    a = amap[variables["CornPriceUp"].variable_id]
    assert a.missingness == MissingnessType.SOFT_OBSERVED
    assert a.confidence == 1.0
    assert a.probabilities is not None

    # --- call count checks ---
    # NASS: 3 calls (planting + conditions + yield), all to same URL with different params
    assert nass_http_mock.get.call_count == 3
    # yfinance: 1 call
    yfinance_download_mock.assert_called_once_with(
        ticker="ZC=F",
        period="1mo",
        interval="1d",
    )
