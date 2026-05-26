"""
Integration tests — natural gas domain ingestion pipeline.

Tests the full mapping from NOAA + EIA API responses to EvidenceRecord
assignments.  Both external APIs are mocked via injected httpx.AsyncClient;
no network calls are made.

Test inventory
--------------
TEST-NG-01  build_evidence_record maps all 4 variable UUIDs correctly
TEST-NG-02  temp below monthly normal  → TempAnom=False, HeatingDem=True
TEST-NG-03  temp above monthly normal and above HDD base → TempAnom=True, HeatingDem=False
TEST-NG-04  storage decreases week-over-week → StorageDraw=True
TEST-NG-05  storage increases week-over-week → StorageDraw=False
TEST-NG-06  latest price above 28-day median → PriceUp=True
TEST-NG-07  latest price at or below 28-day median → PriceUp=False
TEST-NG-08  station confidence scales with stations_used
TEST-NG-09  EIA variables always carry confidence=1.0
TEST-NG-10  full async fetch_evidence via mocked httpx clients
"""
from __future__ import annotations

import asyncio
import sys
import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.natural_gas_v1.domain import get_variables
from src.domains.natural_gas_v1.ingestion.eia_client import EIAClient, NatGasSnapshot
from src.domains.natural_gas_v1.ingestion.noaa_client import (
    DailyClimateObs,
    MONTHLY_NORMALS_C,
    HDD_BASE_C,
    NOAAClient,
)
from src.domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_JAN_1_2025 = date(2025, 1, 1)   # January: normal = 1.5°C
_JUL_1_2025 = date(2025, 7, 1)   # July:    normal = 25.0°C


def _make_climate_obs(
    *,
    temp_c: float,
    target_date: date = _JAN_1_2025,
    stations_used: int = 5,
) -> DailyClimateObs:
    """
    Build a DailyClimateObs fixture.  temp_anom and heating_dem are derived
    the same way the real NOAAClient does it.
    """
    hdd = max(0.0, HDD_BASE_C - temp_c)
    normal = MONTHLY_NORMALS_C[target_date.month]
    return DailyClimateObs(
        target_date=target_date,
        mean_temp_c=temp_c,
        hdd=hdd,
        temp_anom=temp_c > normal,
        heating_dem=hdd > 0.0,
        stations_used=stations_used,
        station_means={"KORD": temp_c},
    )


def _make_gas_snapshot(
    *,
    current_bcf: float = 2000.0,
    prev_bcf: float = 2100.0,
    latest_price: float = 5.0,
    median_price: float = 4.0,
) -> NatGasSnapshot:
    change = current_bcf - prev_bcf
    return NatGasSnapshot(
        storage_current_bcf=current_bcf,
        storage_prev_bcf=prev_bcf,
        storage_change_bcf=change,
        storage_draw=change < 0.0,
        latest_price=latest_price,
        median_price=median_price,
        price_up=latest_price > median_price,
    )


def _assignment_map(record) -> dict:
    """Return {variable_id: ObservedAssignment} for easy lookup."""
    return {a.variable_id: a for a in record.observed_assignments}


# ---------------------------------------------------------------------------
# TEST-NG-01 — UUID mapping
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    """All four assignments carry the canonical variable UUIDs from get_variables()."""
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=0.0)
    snap = _make_gas_snapshot()
    record = NaturalGasPipeline.build_evidence_record(obs, snap)

    assignment_ids = {a.variable_id for a in record.observed_assignments}
    expected_ids   = {v.variable_id for v in variables.values()}

    assert assignment_ids == expected_ids, (
        f"Assignment IDs do not match canonical variable IDs.\n"
        f"  got:      {assignment_ids}\n"
        f"  expected: {expected_ids}"
    )


# ---------------------------------------------------------------------------
# TEST-NG-02 — TempAnom=False when below monthly normal
# ---------------------------------------------------------------------------

def test_temp_below_normal_january():
    """
    January normal = 1.5°C.  Setting temp_c = 0.0°C gives:
        TempAnom  = False   (0.0 < 1.5)
        HeatingDem = True   (HDD = 18.33 - 0.0 = 18.33 > 0)
    """
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=0.0, target_date=_JAN_1_2025)
    snap = _make_gas_snapshot()
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["TempAnom"].variable_id].observed_value  is False
    assert amap[variables["HeatingDem"].variable_id].observed_value is True


# ---------------------------------------------------------------------------
# TEST-NG-03 — TempAnom=True and HeatingDem=False in summer heat
# ---------------------------------------------------------------------------

def test_temp_above_normal_july():
    """
    July normal = 25.0°C.  HDD base = 18.33°C.  Setting temp_c = 30.0°C:
        TempAnom   = True   (30.0 > 25.0)
        HeatingDem = False  (HDD = max(0, 18.33 - 30.0) = 0)
    """
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=30.0, target_date=_JUL_1_2025)
    snap = _make_gas_snapshot()
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["TempAnom"].variable_id].observed_value   is True
    assert amap[variables["HeatingDem"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-NG-04 — StorageDraw=True when storage decreases
# ---------------------------------------------------------------------------

def test_storage_draw_when_decrease():
    """current_bcf < prev_bcf  →  StorageDraw=True."""
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=0.0)
    snap = _make_gas_snapshot(current_bcf=1900.0, prev_bcf=2000.0)   # draw of 100 Bcf
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["StorageDraw"].variable_id].observed_value is True


# ---------------------------------------------------------------------------
# TEST-NG-05 — StorageDraw=False when storage increases
# ---------------------------------------------------------------------------

def test_storage_build_when_increase():
    """current_bcf > prev_bcf  →  StorageDraw=False."""
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=25.0, target_date=_JUL_1_2025)
    snap = _make_gas_snapshot(current_bcf=2100.0, prev_bcf=2000.0)   # build of 100 Bcf
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["StorageDraw"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-NG-06 — PriceUp=True when latest > median
# ---------------------------------------------------------------------------

def test_price_up_when_above_median():
    """latest_price > median_price  →  PriceUp=True."""
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=0.0)
    snap = _make_gas_snapshot(latest_price=5.0, median_price=4.0)
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["PriceUp"].variable_id].observed_value is True


# ---------------------------------------------------------------------------
# TEST-NG-07 — PriceUp=False when latest ≤ median
# ---------------------------------------------------------------------------

def test_price_not_up_when_at_or_below_median():
    """latest_price ≤ median_price  →  PriceUp=False."""
    variables = get_variables()
    obs  = _make_climate_obs(temp_c=0.0)
    snap = _make_gas_snapshot(latest_price=4.0, median_price=4.0)  # equal → False
    record = NaturalGasPipeline.build_evidence_record(obs, snap)
    amap = _assignment_map(record)

    assert amap[variables["PriceUp"].variable_id].observed_value is False


# ---------------------------------------------------------------------------
# TEST-NG-08 — Station confidence scaling
# ---------------------------------------------------------------------------

def test_station_confidence_scales_with_stations_used():
    """
    Weather-variable confidence = max(0.4, stations_used / 5).
    5 stations  → 1.0
    3 stations  → 0.6
    1 station   → 0.4  (clamped minimum)
    EIA variables always carry 1.0 regardless.
    """
    variables = get_variables()
    snap = _make_gas_snapshot()

    for stations, expected_conf in [(5, 1.0), (3, 0.6), (1, 0.4)]:
        obs = _make_climate_obs(temp_c=0.0, stations_used=stations)
        record = NaturalGasPipeline.build_evidence_record(obs, snap)
        amap = _assignment_map(record)

        assert abs(amap[variables["TempAnom"].variable_id].confidence - expected_conf) < 1e-9, (
            f"stations={stations}: expected confidence {expected_conf}, "
            f"got {amap[variables['TempAnom'].variable_id].confidence}"
        )
        assert abs(amap[variables["HeatingDem"].variable_id].confidence - expected_conf) < 1e-9


# ---------------------------------------------------------------------------
# TEST-NG-09 — EIA variables always have confidence 1.0
# ---------------------------------------------------------------------------

def test_eia_variables_always_full_confidence():
    """StorageDraw and PriceUp carry confidence=1.0 regardless of NOAA stations."""
    variables = get_variables()
    snap = _make_gas_snapshot()

    for stations in [1, 2, 3, 5]:
        obs = _make_climate_obs(temp_c=0.0, stations_used=stations)
        record = NaturalGasPipeline.build_evidence_record(obs, snap)
        amap = _assignment_map(record)

        assert amap[variables["StorageDraw"].variable_id].confidence == 1.0
        assert amap[variables["PriceUp"].variable_id].confidence == 1.0


# ---------------------------------------------------------------------------
# TEST-NG-10 — Full async pipeline with mocked httpx clients
# ---------------------------------------------------------------------------

def _make_noaa_http_response(temp_value: float, n_readings: int = 10) -> MagicMock:
    """
    Build a mock httpx response for the NWS station observations endpoint.
    Produces `n_readings` valid temperature observations at `temp_value` °C.
    """
    features = [
        {
            "properties": {
                "temperature": {
                    "value": temp_value,
                    "qualityControl": "V",
                }
            }
        }
        for _ in range(n_readings)
    ]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"features": features})
    return resp


def _make_eia_http_response(series_id_fragment: str) -> MagicMock:
    """
    Build a mock httpx response for the EIA v2 seriesid endpoint.
    Differentiates storage vs price series via URL fragment.
    """
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    if "NW2_EPG0_SWO" in series_id_fragment:   # storage series
        resp.json = MagicMock(return_value={
            "response": {
                "data": [
                    {"value": "1900.0"},   # current week  → draw
                    {"value": "2000.0"},   # previous week
                    {"value": "1950.0"},   # two weeks ago (safety fetch)
                ]
            }
        })
    else:                                        # price series (RNGWHHD)
        # 27 values at 4.0, then the latest at 5.0 → median≈4.0, price_up=True
        prices = [{"value": "4.0"}] * 27 + [{"value": "5.0"}]
        # API returns newest-first, so latest is prices[0]
        prices_newest_first = [{"value": "5.0"}] + [{"value": "4.0"}] * 27
        resp.json = MagicMock(return_value={
            "response": {"data": prices_newest_first}
        })

    return resp


def _make_historical_eia_http_response(series_id_fragment: str) -> MagicMock:
    """Mock EIA response containing latest and historical rows together."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    if "NW2_EPG0_SWO" in series_id_fragment:
        resp.json = MagicMock(return_value={
            "response": {
                "data": [
                    {"period": "2025-01-20", "value": "120.0"},
                    {"period": "2025-01-13", "value": "130.0"},
                    {"period": "2025-01-06", "value": "100.0"},
                    {"period": "2024-12-30", "value": "90.0"},
                ]
            }
        })
    else:
        price_rows = [
            {"period": "2025-01-20", "value": "6.0"},
            {"period": "2025-01-19", "value": "4.0"},
            {"period": "2025-01-18", "value": "4.0"},
            {"period": "2025-01-17", "value": "4.0"},
            {"period": "2025-01-16", "value": "4.0"},
            {"period": "2025-01-15", "value": "4.0"},
            {"period": "2025-01-14", "value": "4.0"},
            {"period": "2025-01-13", "value": "4.0"},
            {"period": "2025-01-12", "value": "4.0"},
            {"period": "2025-01-11", "value": "4.0"},
            {"period": "2025-01-10", "value": "2.0"},
        ]
        price_rows.extend(
            {"period": f"2025-01-{day:02d}", "value": "4.0"}
            for day in range(9, 0, -1)
        )
        price_rows.extend(
            {"period": f"2024-12-{day:02d}", "value": "4.0"}
            for day in range(31, 10, -1)
        )
        resp.json = MagicMock(return_value={"response": {"data": price_rows}})

    return resp


def _natural_gas_values(record) -> dict[str, bool]:
    variables = get_variables()
    by_id = {v.variable_id: name for name, v in variables.items()}
    return {
        by_id[a.variable_id]: a.observed_value
        for a in record.observed_assignments
    }


def test_fetch_evidence_full_async():
    """
    End-to-end test of NaturalGasPipeline.fetch_evidence() with both HTTP
    clients mocked.  No real network calls are made.

    Setup:
        NOAA: all 5 stations return 10 readings at 0.0°C (January baseline)
            → CONUS mean = 0.0°C
            → TempAnom  = False  (0.0 < 1.5 = Jan normal)
            → HeatingDem = True  (HDD = 18.33 > 0)
        EIA storage: 1900 Bcf current, 2000 Bcf previous
            → StorageDraw = True  (draw of 100 Bcf)
        EIA price: latest=5.0, 27 readings at 4.0 → median=4.0
            → PriceUp = True  (5.0 > 4.0)
    """
    variables = get_variables()

    # --- mock NOAA client (all stations return 0.0°C) ---
    noaa_response = _make_noaa_http_response(temp_value=0.0, n_readings=10)
    noaa_http_mock = AsyncMock()
    noaa_http_mock.get = AsyncMock(return_value=noaa_response)
    noaa = NOAAClient(client=noaa_http_mock)

    # --- mock EIA client (URL-dependent routing via side_effect) ---
    def eia_get_side_effect(url, **kwargs):
        return _make_eia_http_response(url)

    eia_http_mock = AsyncMock()
    eia_http_mock.get = AsyncMock(side_effect=eia_get_side_effect)
    eia = EIAClient(api_key="test-key-unused", client=eia_http_mock)

    # --- run async pipeline ---
    pipeline = NaturalGasPipeline(noaa, eia)
    record = asyncio.run(pipeline.fetch_evidence(_JAN_1_2025))

    # --- structural checks ---
    assert len(record.observed_assignments) == 4
    amap = _assignment_map(record)
    assert set(amap.keys()) == {v.variable_id for v in variables.values()}

    # --- value checks ---
    assert amap[variables["TempAnom"].variable_id].observed_value   is False
    assert amap[variables["HeatingDem"].variable_id].observed_value is True
    assert amap[variables["StorageDraw"].variable_id].observed_value is True
    assert amap[variables["PriceUp"].variable_id].observed_value    is True

    # --- confidence checks ---
    # All 5 stations → weather confidence = 1.0
    assert amap[variables["TempAnom"].variable_id].confidence  == 1.0
    assert amap[variables["HeatingDem"].variable_id].confidence == 1.0
    # EIA always 1.0
    assert amap[variables["StorageDraw"].variable_id].confidence == 1.0
    assert amap[variables["PriceUp"].variable_id].confidence     == 1.0

    # --- NOAA was called 5 times (once per station) ---
    assert noaa_http_mock.get.call_count == 5

    # --- EIA was called 2 times (storage + price series) ---
    assert eia_http_mock.get.call_count == 2


def test_eia_fetch_snapshot_uses_historical_target_date():
    """
    The mocked API returns both latest and older rows every time.  Historical
    target dates must select the rows at or before that date, not row 0.
    """
    seen_ends: list[str] = []

    def eia_get_side_effect(url, **kwargs):
        seen_ends.append(kwargs["params"]["end"])
        return _make_historical_eia_http_response(url)

    eia_http_mock = AsyncMock()
    eia_http_mock.get = AsyncMock(side_effect=eia_get_side_effect)
    eia = EIAClient(api_key="test-key-unused", client=eia_http_mock)

    jan_10 = asyncio.run(eia.fetch_snapshot(date(2025, 1, 10)))
    jan_20 = asyncio.run(eia.fetch_snapshot(date(2025, 1, 20)))

    assert jan_10.storage_current_bcf == 100.0
    assert jan_10.storage_prev_bcf == 90.0
    assert jan_10.storage_draw is False
    assert jan_10.latest_price == 2.0
    assert jan_10.price_up is False

    assert jan_20.storage_current_bcf == 120.0
    assert jan_20.storage_prev_bcf == 130.0
    assert jan_20.storage_draw is True
    assert jan_20.latest_price == 6.0
    assert jan_20.price_up is True

    assert seen_ends == [
        "2025-01-10",
        "2025-01-10",
        "2025-01-20",
        "2025-01-20",
    ]


def test_backfill_style_fetches_do_not_duplicate_latest_eia_values():
    """
    Backfill-style pipeline calls with different target dates should produce
    different EIA-derived assignments when historical rows differ.
    """

    class FakeNOAA:
        async def fetch_daily_obs(self, target_date: date) -> DailyClimateObs:
            return _make_climate_obs(temp_c=0.0, target_date=target_date)

    def eia_get_side_effect(url, **kwargs):
        return _make_historical_eia_http_response(url)

    eia_http_mock = AsyncMock()
    eia_http_mock.get = AsyncMock(side_effect=eia_get_side_effect)
    eia = EIAClient(api_key="test-key-unused", client=eia_http_mock)
    pipeline = NaturalGasPipeline(FakeNOAA(), eia)

    jan_10_record = asyncio.run(pipeline.fetch_evidence(date(2025, 1, 10)))
    jan_20_record = asyncio.run(pipeline.fetch_evidence(date(2025, 1, 20)))

    jan_10_values = _natural_gas_values(jan_10_record)
    jan_20_values = _natural_gas_values(jan_20_record)

    assert jan_10_values["StorageDraw"] is False
    assert jan_10_values["PriceUp"] is False
    assert jan_20_values["StorageDraw"] is True
    assert jan_20_values["PriceUp"] is True
    assert jan_10_values != jan_20_values


def test_source_ref_uses_requested_target_date():
    obs = _make_climate_obs(temp_c=0.0, target_date=date(2025, 1, 10))
    snap = _make_gas_snapshot()

    record = NaturalGasPipeline.build_evidence_record(obs, snap)

    assert record.source_ref.endswith("@2025-01-10")
