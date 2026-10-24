"""
Integration tests — geopolitics domain ingestion pipeline.

Test inventory
--------------
TEST-GP-01  Variable IDs stable across imports
TEST-GP-04  _soft_bool clamped to [0.05, 0.95] (geopolitics clamp)
TEST-GP-05  compute_snapshot falls back to 0.5 with empty data
TEST-GP-06  High conflict volume → P(ConflictIntensityElevated) > 0.5
TEST-GP-07  Low conflict volume → P(ConflictIntensityElevated) < 0.5
TEST-GP-08  build_evidence_record maps all 8 UUIDs
TEST-GP-09  build_evidence_record produces SOFT_OBSERVED
TEST-GP-11  Existence thresholds valid
TEST-GP-12  Domain registers in engine, evidence ingested
TEST-GP-14  GDELTClient parses mocked response
TEST-GP-15  GDELTClient returns empty list on HTTP error (graceful failure)
TEST-GP-16  Full pipeline fetch_evidence with mocked clients
TEST-GP-17  Prob clamp is [0.05, 0.95] for geopolitics
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.sources.soft_evidence import sigmoid as _sigmoid
from src.domains.geopolitics_v1.domain import (
    GeopoliticsV1,
    get_variables,
)
from src.domains.geopolitics_v1.ingestion.gdelt_client import (
    GDELTClient,
    GDELTObs,
)
from src.domains.geopolitics_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
)
from src.domains.geopolitics_v1.ingestion.pipeline import (
    GeopoliticsPipeline,
    GeopoliticsSnapshot,
    compute_snapshot,
    _soft_bool,
    _CLAMP_LO,
    _CLAMP_HI,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


def _make_gdelt_obs(label: str, values: list[float]) -> list[GDELTObs]:
    """Create synthetic GDELT observations, newest first."""
    obs = []
    for i, val in enumerate(values):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(GDELTObs(obs_date=d, value=val, query_label=label))
    return obs


def _make_fred_obs(
    series_id: str,
    num_obs: int = 260,
    base_value: float = 70.0,
) -> list[FREDObservation]:
    obs = []
    for i in range(num_obs):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(FREDObservation(obs_date=d, value=base_value, series_id=series_id))
    return obs


def _make_full_data(
    conflict_values: list[float] | None = None,
    wti_value: float = 80.0,
) -> tuple[dict, dict]:
    if conflict_values is None:
        conflict_values = [2.5] * 90

    gdelt_data = {
        "conflict": _make_gdelt_obs("conflict", conflict_values),
        "sanctions": _make_gdelt_obs("sanctions", [1.5] * 90),
        "diplomatic": _make_gdelt_obs("diplomatic", [1.0] * 90),
        "energy_sanction": _make_gdelt_obs("energy_sanction", [0.8] * 90),
    }

    # For z-score to work, we need some variance; keep wti_value but vary history
    wti_obs = []
    for i in range(260):
        d = _TARGET_DATE - timedelta(days=i)
        val = wti_value if i < 5 else 70.0  # recent = wti_value, history = 70
        wti_obs.append(FREDObservation(obs_date=d, value=val, series_id="DCOILWTICO"))

    fred_data = {
        "DCOILWTICO": wti_obs,
        "PPIACO": _make_fred_obs("PPIACO", 260, 200.0),
        "DTWEXBGS": _make_fred_obs("DTWEXBGS", 260, 105.0),
        "INDPRO": _make_fred_obs("INDPRO", 100, 105.0),
    }
    return gdelt_data, fred_data


# ---------------------------------------------------------------------------
# TEST-GP-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = GeopoliticsV1()
    domain_vars = {v.name: v.variable_id for v in domain.variables()}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == domain_vars[name]


# ---------------------------------------------------------------------------
# TEST-GP-04 — _soft_bool clamped to [0.05, 0.95]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [-100.0, -10.0, 0.0, 10.0, 100.0])
def test_soft_bool_clamped_to_geopolitics_range(signal: float):
    result = _soft_bool(signal)
    assert _CLAMP_LO <= result <= _CLAMP_HI
    assert not math.isnan(result)


# ---------------------------------------------------------------------------
# TEST-GP-05 — compute_snapshot falls back to 0.5 with empty data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_with_empty_data():
    snap = compute_snapshot({}, {}, _TARGET_DATE)
    assert snap.p_conflict_intensity_elevated == 0.5
    assert snap.p_trade_disruption_risk == 0.5
    assert snap.p_sanctions_pressure_elevated == 0.5
    assert snap.p_diplomatic_tension_high == 0.5
    assert snap.p_supply_chain_stress == 0.5
    assert snap.p_currency_war_signal == 0.5
    assert snap.p_energy_weaponization_risk == 0.5
    assert snap.p_global_trade_volume_weak == 0.5


# ---------------------------------------------------------------------------
# TEST-GP-06 — High conflict volume → P(ConflictIntensityElevated) > 0.5
# ---------------------------------------------------------------------------

def test_high_conflict_volume_drives_conflict_signal_high():
    """GDELT conflict values much higher than mean → P(ConflictIntensityElevated) > 0.5."""
    # Recent values very high, history low
    values = [10.0] * 28 + [1.0] * 62  # recent 28 days = 10, history = 1
    gdelt_data, fred_data = _make_full_data(conflict_values=values)
    snap = compute_snapshot(gdelt_data, fred_data, _TARGET_DATE)
    assert snap.p_conflict_intensity_elevated > 0.5, \
        f"Expected P > 0.5 for high conflict, got {snap.p_conflict_intensity_elevated:.3f}"


# ---------------------------------------------------------------------------
# TEST-GP-07 — Low conflict volume → P(ConflictIntensityElevated) < 0.5
# ---------------------------------------------------------------------------

def test_low_conflict_volume_drives_conflict_signal_low():
    """GDELT conflict values much lower than mean → P(ConflictIntensityElevated) < 0.5."""
    # Recent values very low, history high
    values = [0.1] * 28 + [8.0] * 62  # recent 28 days = 0.1, history = 8
    gdelt_data, fred_data = _make_full_data(conflict_values=values)
    snap = compute_snapshot(gdelt_data, fred_data, _TARGET_DATE)
    assert snap.p_conflict_intensity_elevated < 0.5, \
        f"Expected P < 0.5 for low conflict, got {snap.p_conflict_intensity_elevated:.3f}"


# ---------------------------------------------------------------------------
# TEST-GP-08 — build_evidence_record maps all 8 UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    gdelt_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(gdelt_data, fred_data, _TARGET_DATE)
    record = GeopoliticsPipeline.build_evidence_record(snapshot)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids


# ---------------------------------------------------------------------------
# TEST-GP-09 — build_evidence_record produces SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    gdelt_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(gdelt_data, fred_data, _TARGET_DATE)
    record = GeopoliticsPipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.probabilities is not None
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert _CLAMP_LO <= p_true <= _CLAMP_HI
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# TEST-GP-11 — Existence thresholds valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    domain = GeopoliticsV1()
    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-GP-12 — Domain registers in engine, evidence ingested
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = GeopoliticsV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert [(c.edges, c.lineage) for c in pop.active_candidates()] == [([], "unconnected")]

    gdelt_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(gdelt_data, fred_data, _TARGET_DATE)
    record = GeopoliticsPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-GP-14 — GDELTClient parses mocked response
# ---------------------------------------------------------------------------

def test_gdelt_client_parses_mocked_response():
    """GDELTClient correctly parses the timeline JSON structure."""
    mock_body = {
        "timeline": [
            {
                "series": "Volume Intensity",
                "data": [
                    {"date": "20240503T000000Z", "value": 3.45},
                    {"date": "20240502T000000Z", "value": 2.10},
                    {"date": "20240501T000000Z", "value": 1.89},
                ],
            }
        ]
    }

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=mock_body)

    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)

    client = GDELTClient(client=http_mock)
    result = asyncio.run(client.fetch_timeline("conflict war", "conflict", end_date=_TARGET_DATE))

    assert len(result) == 3
    assert result[0].obs_date == date(2024, 5, 3)
    assert result[0].value == 3.45
    assert result[0].query_label == "conflict"


# ---------------------------------------------------------------------------
# TEST-GP-15 — GDELTClient returns empty list on HTTP error
# ---------------------------------------------------------------------------

def test_gdelt_client_returns_empty_on_http_error():
    """GDELTClient gracefully handles HTTP errors by returning empty list."""
    import httpx

    from src.domains.sources.gdelt import RateLimiter, TimelineCache

    http_mock = AsyncMock()
    http_mock.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    elapsed = [0.0]

    async def sleep(seconds: float) -> None:  # the retries' backoffs, without the wait
        elapsed[0] += max(0.0, seconds)

    limiter = RateLimiter(5.0, clock=lambda: elapsed[0], sleep=sleep)
    client = GDELTClient(client=http_mock, rate_limit=limiter, cache=TimelineCache())
    result = asyncio.run(client.fetch_timeline("conflict war", "conflict"))

    # Retried like a throttle, then empty, not raised.
    assert result == []
    assert http_mock.get.await_count == 4


# ---------------------------------------------------------------------------
# TEST-GP-16 — Full pipeline fetch_evidence with mocked clients
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    gdelt_data, fred_data = _make_full_data()

    mock_gdelt = AsyncMock(spec=GDELTClient)
    mock_gdelt.fetch_all = AsyncMock(return_value=gdelt_data)

    mock_fred = AsyncMock(spec=FREDClient)
    mock_fred.fetch_all_series = AsyncMock(return_value=fred_data)

    pipeline = GeopoliticsPipeline(mock_gdelt, mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}
    assert "GDELT" in record.source_ref
    assert "FRED" in record.source_ref

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    mock_gdelt.fetch_all.assert_called_once_with(end_date=_TARGET_DATE)
    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)


# ---------------------------------------------------------------------------
# TEST-GP-17 — Prob clamp is [0.05, 0.95] for geopolitics
# ---------------------------------------------------------------------------

def test_geopolitics_prob_clamp_is_wider():
    """Verify that _CLAMP_LO=0.05 and _CLAMP_HI=0.95 for geopolitics."""
    assert _CLAMP_LO == 0.05, f"Expected _CLAMP_LO=0.05, got {_CLAMP_LO}"
    assert _CLAMP_HI == 0.95, f"Expected _CLAMP_HI=0.95, got {_CLAMP_HI}"

    # Verify extreme signals are clamped at these values
    extreme_lo = _soft_bool(-1000.0)
    extreme_hi = _soft_bool(1000.0)
    assert extreme_lo == 0.05
    assert extreme_hi == 0.95
