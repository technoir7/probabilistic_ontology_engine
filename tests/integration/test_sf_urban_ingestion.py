"""
Integration tests — SF urban domain ingestion pipeline.

Test inventory
--------------
TEST-SF-01  Variable IDs stable across imports
TEST-SF-02  All 5 candidates are valid DAGs
TEST-SF-03  All candidates share same variable set
TEST-SF-04  _soft_bool clamped to [0.01, 0.99]
TEST-SF-05  compute_snapshot falls back to 0.5 with empty data
TEST-SF-06  High crime count → P(CrimeIndexElevated) > 0.5
TEST-SF-07  Low crime count → P(CrimeIndexElevated) < 0.5
TEST-SF-08  build_evidence_record maps all 8 UUIDs
TEST-SF-09  build_evidence_record produces SOFT_OBSERVED
TEST-SF-10  Domain module_id matches candidates
TEST-SF-11  Existence thresholds valid
TEST-SF-12  Domain registers in engine, evidence ingested
TEST-SF-13  Candidates have distinct edge structures
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

from src.domains.sf_urban_v1.domain import (
    SFUrbanV1,
    get_variables,
    make_tech_rebound_candidate,
    make_structural_decline_candidate,
    make_bifurcated_recovery_candidate,
    make_bottom_formation_candidate,
    make_null_candidate,
)
from src.domains.sf_urban_v1.ingestion.sfgov_client import (
    SFGovClient,
    SFPermitObs,
    SFIncidentObs,
    SFBusinessObs,
)
from src.domains.sf_urban_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
)
from src.domains.sf_urban_v1.ingestion.pipeline import (
    SFUrbanPipeline,
    SFUrbanSnapshot,
    compute_snapshot,
    _soft_bool,
    _sigmoid,
    _monthly_counts,
    _monthly_zscore,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


def _make_incidents(
    monthly_counts_map: dict[str, int],
) -> list[SFIncidentObs]:
    """Create synthetic incident observations from monthly counts.

    Uses a single representative date per month and repeats it count times
    to ensure the monthly bucket has the right count, bypassing the 28-day limit.
    """
    obs = []
    for month_str, count in monthly_counts_map.items():
        year, month = int(month_str[:4]), int(month_str[5:7])
        # Use day=1 as representative date, repeat count times
        d = date(year, month, 1)
        for _ in range(count):
            obs.append(SFIncidentObs(incident_date=d, category="Larceny Theft"))
    return obs


def _make_permits(num_total: int = 50, num_months: int = 12) -> list[SFPermitObs]:
    """Create synthetic permit observations spread across months."""
    obs = []
    per_month = max(1, num_total // num_months)
    for m in range(num_months):
        month_date = _TARGET_DATE.replace(day=1) - timedelta(days=m * 30)
        for day in range(1, per_month + 1):
            try:
                d = date(month_date.year, month_date.month, day)
                obs.append(SFPermitObs(filed_date=d, permit_type="building alteration"))
            except ValueError:
                pass
    return obs


def _make_businesses(
    start_count: int = 20,
    end_count: int = 5,
    num_months: int = 12,
) -> list[SFBusinessObs]:
    """Create synthetic business obs with some starts and closures."""
    obs = []
    start_per_month = max(1, start_count // num_months)
    end_per_month = max(1, end_count // num_months)

    for m in range(num_months):
        month_date = _TARGET_DATE.replace(day=1) - timedelta(days=m * 30)
        year, month = month_date.year, month_date.month
        # New businesses
        for day in range(1, start_per_month + 1):
            try:
                d = date(year, month, day)
                obs.append(SFBusinessObs(start_date=d, end_date=None))
            except ValueError:
                pass
        # Closures
        for day in range(1, end_per_month + 1):
            try:
                d = date(year, month, min(day + 15, 28))
                start = date(year - 2, month, 1)
                obs.append(SFBusinessObs(start_date=start, end_date=d))
            except ValueError:
                pass
    return obs


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
    # Build incidents with variability for z-score
    if crime_level == "high":
        # Recent month much higher than history
        monthly = {"2024-05": 200, "2024-04": 80, "2024-03": 85, "2024-02": 78, "2024-01": 82,
                   "2023-12": 80, "2023-11": 75, "2023-10": 83, "2023-09": 79, "2023-08": 77,
                   "2023-07": 81, "2023-06": 84}
    elif crime_level == "low":
        # Recent month much lower than history
        monthly = {"2024-05": 10, "2024-04": 90, "2024-03": 88, "2024-02": 85, "2024-01": 92,
                   "2023-12": 87, "2023-11": 91, "2023-10": 89, "2023-09": 86, "2023-08": 90,
                   "2023-07": 88, "2023-06": 85}
    else:
        monthly = {"2024-05": 80, "2024-04": 82, "2024-03": 79, "2024-02": 81, "2024-01": 83,
                   "2023-12": 80, "2023-11": 78, "2023-10": 82, "2023-09": 80, "2023-08": 81,
                   "2023-07": 79, "2023-06": 83}

    sfgov_data = {
        "permits": _make_permits(num_total=500, num_months=13),
        "incidents": _make_incidents(monthly),
        "businesses": _make_businesses(start_count=130, end_count=52, num_months=13),
    }

    fred_data = {
        "SMU06418205101000001SA": _make_fred_obs(
            "SMU06418205101000001SA", 24, 200.0, tech_emp_trend
        ),
        "SMU06418207072000001SA": _make_fred_obs("SMU06418207072000001SA", 24, 150.0),
        "SMU06418200000000001SA": _make_fred_obs("SMU06418200000000001SA", 24, 1200.0),
    }
    return sfgov_data, fred_data


# ---------------------------------------------------------------------------
# TEST-SF-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = SFUrbanV1()
    cands = domain.initial_candidates()
    cand_vars = {v.name: v.variable_id for v in cands[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


# ---------------------------------------------------------------------------
# TEST-SF-02 — All 5 candidates are valid DAGs
# ---------------------------------------------------------------------------

def test_all_candidates_are_dags():
    factories = [
        make_tech_rebound_candidate,
        make_structural_decline_candidate,
        make_bifurcated_recovery_candidate,
        make_bottom_formation_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG constraint"


# ---------------------------------------------------------------------------
# TEST-SF-03 — All candidates share the canonical variable set
# ---------------------------------------------------------------------------

def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    factories = [
        make_tech_rebound_candidate,
        make_structural_decline_candidate,
        make_bifurcated_recovery_candidate,
        make_bottom_formation_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        cand_names = {v.name for v in cand.variables}
        assert cand_names == expected_names
        assert {v.variable_id for v in cand.variables} == expected_ids


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
# TEST-SF-10 — Domain module_id matches candidates
# ---------------------------------------------------------------------------

def test_domain_module_id_matches_candidates():
    domain = SFUrbanV1()
    module_id = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == module_id


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
    assert len(pop.active_candidates()) == 5

    sfgov_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    record = SFUrbanPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-SF-13 — Candidates have distinct edge structures
# ---------------------------------------------------------------------------

def test_candidates_have_distinct_edge_structures():
    domain = SFUrbanV1()
    candidates = domain.initial_candidates()
    signatures = [c.edge_structure_signature() for c in candidates]
    assert len(set(signatures)) == len(signatures), \
        "Some candidates share the same edge structure"


# ---------------------------------------------------------------------------
# TEST-SF-14 — SFGovClient returns empty lists on HTTP error
# ---------------------------------------------------------------------------

def test_sfgov_client_returns_empty_on_http_error():
    """SFGovClient gracefully handles HTTP errors by returning empty lists."""
    import httpx

    http_mock = AsyncMock()
    http_mock.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    client = SFGovClient(client=http_mock)

    # All three fetch methods should return empty lists, not raise
    permits = asyncio.run(client.fetch_permits())
    incidents = asyncio.run(client.fetch_incidents())
    businesses = asyncio.run(client.fetch_businesses())

    assert permits == []
    assert incidents == []
    assert businesses == []


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
        info_emp.append(FREDObservation(obs_date=d, value=val, series_id="SMU06418205101000001SA"))

    fred_data = {
        "SMU06418205101000001SA": info_emp,
        "SMU06418207072000001SA": _make_fred_obs("SMU06418207072000001SA", 24, 150.0),
        "SMU06418200000000001SA": _make_fred_obs("SMU06418200000000001SA", 24, 1200.0),
    }
    sfgov_data = {
        "permits": _make_permits(),
        "incidents": _make_incidents({"2024-05": 80}),
        "businesses": _make_businesses(),
    }

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
        info_emp.append(FREDObservation(obs_date=d, value=max(val, 50.0), series_id="SMU06418205101000001SA"))

    fred_data = {
        "SMU06418205101000001SA": info_emp,
        "SMU06418207072000001SA": _make_fred_obs("SMU06418207072000001SA", 24, 150.0),
        "SMU06418200000000001SA": _make_fred_obs("SMU06418200000000001SA", 24, 1200.0),
    }
    sfgov_data = {
        "permits": _make_permits(),
        "incidents": _make_incidents({"2024-05": 80}),
        "businesses": _make_businesses(),
    }

    snap = compute_snapshot(sfgov_data, fred_data, _TARGET_DATE)
    assert snap.p_tech_hiring_accelerating < 0.5, \
        f"Expected P < 0.5 for falling tech employment, got {snap.p_tech_hiring_accelerating:.3f}"
