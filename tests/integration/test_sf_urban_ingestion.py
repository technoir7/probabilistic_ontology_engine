"""
Integration tests — SF urban domain ingestion pipeline.

Test inventory
--------------
TEST-SF-01  Variable IDs stable across imports
TEST-SF-04  _soft_bool clamped to [0.01, 0.99]
TEST-SF-05  compute_snapshot falls back to 0.5 with empty data
TEST-SF-06  High crime count → P(CrimeIndexElevated) > 0.5
TEST-SF-07  Low crime count → P(CrimeIndexElevated) < 0.5
TEST-SF-08  build_evidence_record maps all 8 UUIDs
TEST-SF-09  build_evidence_record produces SOFT_OBSERVED
TEST-SF-11  Existence thresholds valid
TEST-SF-12  Domain registers in engine, evidence ingested
TEST-SF-14  SFGovClient returns empty lists on HTTP error (graceful failure)
TEST-SF-15  Full pipeline fetch_evidence with mocked clients
TEST-SF-16  Rising tech employment → P(TechHiringAccelerating) > 0.5
TEST-SF-17  Falling tech employment → P(TechHiringAccelerating) < 0.5
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.sources.soft_evidence import sigmoid as _sigmoid
from src.domains.sf_urban_v1.domain import (
    SFUrbanV1,
    get_variables,
)
from src.domains.sf_urban_v1.ingestion.sfgov_client import MonthlyCount, SFGovClient
from src.domains.sf_urban_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
)
from src.domains.sf_urban_v1.ingestion.pipeline import (
    SFUrbanPipeline,
    SFUrbanSnapshot,
    compute_snapshot,
    _soft_bool,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


# The signals compare complete months only, so fixtures end with the latest
# month before _TARGET_DATE's (2024-04); 2024-05 is in progress and ignored.
def _complete_months(n: int = 13) -> list[date]:
    months = []
    d = _TARGET_DATE.replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
        months.append(d)
    return sorted(months)


def _counts(values: list[int], category: str = "") -> list[MonthlyCount]:
    """One MonthlyCount per complete month, oldest first, from *values*."""
    months = _complete_months(len(values))
    return [MonthlyCount(month=m, count=c, category=category) for m, c in zip(months, values)]


def _make_incidents(latest: int, history: list[int]) -> list[MonthlyCount]:
    return _counts(history + [latest])


def _make_permits() -> list[MonthlyCount]:
    """Office and other permits per month, office share varying a little."""
    office = [12, 10, 11, 13, 9, 12, 10, 11, 12, 10, 13, 11, 12]
    other = [40, 42, 39, 41, 43, 40, 38, 42, 41, 39, 40, 42, 41]
    return _counts(office, "office") + _counts(other, "1 family dwelling")


def _make_business_openings() -> list[MonthlyCount]:
    return _counts([10, 11, 9, 10, 12, 10, 11, 9, 10, 11, 10, 12, 10])


def _make_business_closures() -> list[MonthlyCount]:
    return _counts([4, 5, 3, 4, 4, 5, 3, 4, 5, 4, 3, 4, 4])


def _sfgov(incidents: list[MonthlyCount]) -> dict:
    return {
        "permits": _make_permits(),
        "incidents": incidents,
        "business_openings": _make_business_openings(),
        "business_closures": _make_business_closures(),
    }


def _make_fred_obs(
    series_id: str,
    num_obs: int = 24,
    base_value: float = 100.0,
    trend: float = 0.0,
) -> list[FREDObservation]:
    """Create monthly FRED employment observations, newest first."""
    obs = []
    for i in range(num_obs):
        d = _TARGET_DATE.replace(day=1) - timedelta(days=i * 30)
        val = base_value * (1.0 + trend * (num_obs - i) / num_obs)
        obs.append(FREDObservation(obs_date=d, value=val, series_id=series_id))
    return obs


def _make_full_data(
    tech_emp_trend: float = 0.0,
    crime_level: str = "normal",
) -> tuple[dict, dict]:
    # Latest complete month vs a stable history (variability for the z-score)
    history = [80, 85, 78, 82, 80, 75, 83, 79, 77, 81, 84]
    latest = {"high": 200, "low": 10}.get(crime_level, 81)
    sfgov_data = _sfgov(_make_incidents(latest, history))

    fred_data = {
        "SANF806INFO": _make_fred_obs("SANF806INFO", 24, 200.0, tech_emp_trend),
        "SANF806LEIH": _make_fred_obs("SANF806LEIH", 24, 150.0),
        "SANF806NA":   _make_fred_obs("SANF806NA",   24, 1200.0),
    }
    return sfgov_data, fred_data


# ---------------------------------------------------------------------------
# TEST-SF-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = SFUrbanV1()
    domain_vars = {v.name: v.variable_id for v in domain.variables()}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == domain_vars[name]


# ---------------------------------------------------------------------------
# TEST-SF-04 — _soft_bool clamped to [0.01, 0.99]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [-100.0, -10.0, 0.0, 10.0, 100.0])
def test_soft_bool_clamped(signal: float):
    result = _soft_bool(signal)
    assert 0.01 <= result <= 0.99
    assert not math.isnan(result)


# ---------------------------------------------------------------------------
# TEST-SF-05 — compute_snapshot falls back to 0.5 with empty data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_with_empty_data():
    snap = compute_snapshot({}, {}, _TARGET_DATE)
    assert snap.p_tech_hiring_accelerating == 0.5
    assert snap.p_office_vacancy_falling == 0.5
    assert snap.p_retail_closure_elevated == 0.5
    assert snap.p_permit_activity_rising == 0.5
    assert snap.p_crime_index_elevated == 0.5
    assert snap.p_startup_formation_rising == 0.5
    assert snap.p_foot_traffic_recovering == 0.5
    assert snap.p_population_flow_positive == 0.5


# ---------------------------------------------------------------------------
# TEST-SF-06 — High crime count → P(CrimeIndexElevated) > 0.5
# ---------------------------------------------------------------------------

def test_high_crime_drives_crime_signal_high():
    """Recent month with much higher incidents → P(CrimeIndexElevated) > 0.5."""
    sfgov_data, fred_data = _make_full_data(crime_level="high")
    snap = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    assert snap.p_crime_index_elevated > 0.5, \
        f"Expected P > 0.5 for high crime, got {snap.p_crime_index_elevated:.3f}"


# ---------------------------------------------------------------------------
# TEST-SF-07 — Low crime count → P(CrimeIndexElevated) < 0.5
# ---------------------------------------------------------------------------

def test_low_crime_drives_crime_signal_low():
    """Recent month with much lower incidents → P(CrimeIndexElevated) < 0.5."""
    sfgov_data, fred_data = _make_full_data(crime_level="low")
    snap = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    assert snap.p_crime_index_elevated < 0.5, \
        f"Expected P < 0.5 for low crime, got {snap.p_crime_index_elevated:.3f}"


# ---------------------------------------------------------------------------
# TEST-SF-08 — build_evidence_record maps all 8 UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    sfgov_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    record = SFUrbanPipeline.build_evidence_record(snapshot)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids


# ---------------------------------------------------------------------------
# TEST-SF-09 — build_evidence_record produces SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    sfgov_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    record = SFUrbanPipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.probabilities is not None
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# TEST-SF-11 — Existence thresholds valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    domain = SFUrbanV1()
    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-SF-12 — Domain registers in engine, evidence ingested
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = SFUrbanV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert [(c.edges, c.lineage) for c in pop.active_candidates()] == [([], "unconnected")]

    sfgov_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    record = SFUrbanPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-SF-14 — SFGovClient returns empty lists on HTTP error
# ---------------------------------------------------------------------------

def test_sfgov_client_returns_empty_on_http_error():
    """SFGovClient gracefully handles HTTP errors by returning empty lists."""
    import httpx

    http_mock = AsyncMock()
    http_mock.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    client = SFGovClient(client=http_mock)

    # Every fetch returns an empty list, not an exception
    for fetch in (client.fetch_permits, client.fetch_incidents,
                  client.fetch_business_openings, client.fetch_business_closures):
        assert asyncio.run(fetch()) == []


# ---------------------------------------------------------------------------
# TEST-SF-15 — Full pipeline fetch_evidence with mocked clients
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    sfgov_data, fred_data = _make_full_data()

    mock_sfgov = AsyncMock(spec=SFGovClient)
    mock_sfgov.fetch_all = AsyncMock(return_value=sfgov_data)

    mock_fred = AsyncMock(spec=FREDClient)
    mock_fred.fetch_all_series = AsyncMock(return_value=fred_data)

    pipeline = SFUrbanPipeline(mock_sfgov, mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}
    assert "SFGov" in record.source_ref
    assert "FRED" in record.source_ref

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    mock_sfgov.fetch_all.assert_called_once_with(end_date=_TARGET_DATE)
    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)


# ---------------------------------------------------------------------------
# TEST-SF-16 — Rising tech employment → P(TechHiringAccelerating) > 0.5
# ---------------------------------------------------------------------------

def test_rising_tech_employment_drives_signal_high():
    """FRED info employment rising strongly YoY → P(TechHiringAccelerating) > 0.5.

    Build a series where recent YoY growth is much higher than historical YoY
    growth, so the z-score is positive. Create variance in historical changes
    so the z-score is non-zero.
    """
    # Build employment data with a big jump in recent months vs flat history
    # Index 0=newest (2024-05), 12=year ago (2023-05), 23=oldest (2022-06)
    info_emp = []
    for i in range(24):
        d = _TARGET_DATE.replace(day=1) - timedelta(days=i * 30)
        if i < 6:
            # Recent 6 months: big values (growth)
            val = 250.0 + (5 - i) * 5.0  # 275, 270, 265, 260, 255, 250
        elif i < 12:
            # 6-12 months ago: stable
            val = 200.0 + (i % 3) * 2.0  # some variance: 200, 202, 204
        else:
            # 12-24 months ago: lower baseline with variance
            val = 190.0 + (i % 5) * 3.0  # 190, 193, 196, 199, 202...
        info_emp.append(FREDObservation(obs_date=d, value=val, series_id="SANF806INFO"))

    fred_data = {
        "SANF806INFO": info_emp,
        "SANF806LEIH": _make_fred_obs("SANF806LEIH", 24, 150.0),
        "SANF806NA":   _make_fred_obs("SANF806NA",   24, 1200.0),
    }
    sfgov_data = _sfgov(_make_incidents(80, [80, 82, 79, 81]))

    snap = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    assert snap.p_tech_hiring_accelerating > 0.5, \
        f"Expected P > 0.5 for rising tech employment, got {snap.p_tech_hiring_accelerating:.3f}"


# ---------------------------------------------------------------------------
# TEST-SF-17 — Falling tech employment → P(TechHiringAccelerating) < 0.5
# ---------------------------------------------------------------------------

def test_falling_tech_employment_drives_signal_low():
    """FRED info employment falling YoY → P(TechHiringAccelerating) < 0.5."""
    # Build employment data where recent < year-ago
    info_emp = []
    for i in range(24):
        d = _TARGET_DATE.replace(day=1) - timedelta(days=i * 30)
        # Values decreasing over time (newest = lowest)
        val = 200.0 - (24 - i) * 2.0  # 200 at oldest, 152 at newest
        info_emp.append(FREDObservation(obs_date=d, value=max(val, 50.0), series_id="SANF806INFO"))

    fred_data = {
        "SANF806INFO": info_emp,
        "SANF806LEIH": _make_fred_obs("SANF806LEIH", 24, 150.0),
        "SANF806NA":   _make_fred_obs("SANF806NA",   24, 1200.0),
    }
    sfgov_data = _sfgov(_make_incidents(80, [80, 82, 79, 81]))

    snap = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    assert snap.p_tech_hiring_accelerating < 0.5, \
        f"Expected P < 0.5 for falling tech employment, got {snap.p_tech_hiring_accelerating:.3f}"
