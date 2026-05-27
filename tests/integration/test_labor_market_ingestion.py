"""
Integration tests — labor market domain ingestion pipeline.

Test inventory
--------------
TEST-LM-01  All 8 variable IDs are stable across module imports
TEST-LM-02  All 5 initial candidates are valid DAGs
TEST-LM-03  All candidates share the same variable set
TEST-LM-04  Soft probabilities are clamped to [0.01, 0.99]
TEST-LM-05  Rising unemployment → P(UnemploymentRising) > 0.5
TEST-LM-06  Falling unemployment → P(UnemploymentRising) < 0.5
TEST-LM-07  Positive real wage growth → P(RealWageGrowthPositive) > 0.5
TEST-LM-08  Negative real wage growth → P(RealWageGrowthPositive) < 0.5
TEST-LM-09  build_evidence_record maps all 8 variable UUIDs correctly
TEST-LM-10  build_evidence_record produces SOFT_OBSERVED missingness
TEST-LM-11  FRED client fetch_series with mocked HTTP
TEST-LM-12  FRED client skips missing values
TEST-LM-13  compute_snapshot falls back gracefully with no data
TEST-LM-14  Domain module_id matches candidates
TEST-LM-15  Existence thresholds are within valid ranges
TEST-LM-16  Domain registers in engine and evidence is ingested
TEST-LM-17  Candidates have distinct edge structures
TEST-LM-18  Full pipeline fetch_evidence with mocked FREDClient
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

from src.domains.labor_market_v1.domain import (
    LaborMarketV1,
    get_variables,
    make_labor_tightening_candidate,
    make_layoff_cycle_candidate,
    make_structural_shift_candidate,
    make_wage_price_spiral_candidate,
    make_null_candidate,
)
from src.domains.labor_market_v1.ingestion.fred_client import FREDClient, FREDObservation
from src.domains.labor_market_v1.ingestion.pipeline import (
    LaborMarketPipeline,
    compute_snapshot,
    _soft_bool,
    _compute_unemployment_rising,
    _compute_real_wage_growth_positive,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import MissingnessType

_TARGET_DATE = date(2024, 5, 3)


def _make_obs(series_id: str, values: list[float], step_days: int = 30) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * step_days), value=v, series_id=series_id)
        for i, v in enumerate(values)
    ]


def _make_full_observations(
    unrate_latest: float = 4.2,
    unrate_mean: float = 4.0,
    wages_now: float = 34.50,
    wages_yr_ago: float = 32.50,
    jtsjol_current: float = 8_000.0,
    jtsjol_mean: float = 9_000.0,
    icsa_current: float = 250.0,
    icsa_mean: float = 220.0,
    prs_now: float = 115.0,
    prs_yr_ago: float = 113.0,
    civpart_current: float = 62.5,
    civpart_mean: float = 63.0,
    cpi_now: float = 108.0,
    cpi_yr_ago: float = 104.0,
) -> dict[str, list[FREDObservation]]:
    # UNRATE: 15 monthly
    unrate_values = [unrate_mean] * 15
    unrate_values[0] = unrate_latest
    unrate_obs = _make_obs("UNRATE", unrate_values)

    # Wages: 14 monthly
    wages_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(wages_now if i == 0 else wages_yr_ago if i >= 12 else
                   wages_now - (wages_now - wages_yr_ago) * i / 12),
            series_id="CES0500000003",
        )
        for i in range(14)
    ]

    # JTSJOL: 24 monthly
    jtsjol_values = [jtsjol_mean] * 24
    jtsjol_values[0] = jtsjol_current
    jtsjol_obs = _make_obs("JTSJOL", jtsjol_values)

    # ICSA: 52 weekly
    import numpy as np
    rng = np.random.default_rng(42)
    icsa_values = list(rng.normal(icsa_mean, 15.0, 52).tolist())
    icsa_values[0] = icsa_current
    icsa_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 7), value=max(100.0, icsa_values[i]), series_id="ICSA")
        for i in range(52)
    ]

    # PRS85006092: quarterly — 8 quarters
    prs_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 90),
            value=(prs_now if i == 0 else prs_yr_ago if i >= 4 else
                   prs_now - (prs_now - prs_yr_ago) * i / 4),
            series_id="PRS85006092",
        )
        for i in range(8)
    ]

    # CIVPART: 24 monthly
    civpart_values = [civpart_mean] * 24
    civpart_values[0] = civpart_current
    civpart_obs = _make_obs("CIVPART", civpart_values)

    # CPI: 14 monthly
    cpi_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(cpi_now if i == 0 else cpi_yr_ago if i >= 12 else
                   cpi_now - (cpi_now - cpi_yr_ago) * i / 12),
            series_id="CPIAUCSL",
        )
        for i in range(14)
    ]

    return {
        "UNRATE":       unrate_obs,
        "CES0500000003": wages_obs,
        "JTSJOL":       jtsjol_obs,
        "ICSA":         icsa_obs,
        "PRS85006092":  prs_obs,
        "CIVPART":      civpart_obs,
        "CPIAUCSL":     cpi_obs,
    }


def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = LaborMarketV1()
    cand_vars = {v.name: v.variable_id for v in domain.initial_candidates()[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


def test_all_candidates_are_dags():
    for factory in [
        make_labor_tightening_candidate,
        make_layoff_cycle_candidate,
        make_structural_shift_candidate,
        make_wage_price_spiral_candidate,
        make_null_candidate,
    ]:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG"


def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    for factory in [
        make_labor_tightening_candidate,
        make_layoff_cycle_candidate,
        make_structural_shift_candidate,
        make_wage_price_spiral_candidate,
        make_null_candidate,
    ]:
        cand = factory()
        assert {v.name for v in cand.variables} == expected_names
        assert {v.variable_id for v in cand.variables} == expected_ids


@pytest.mark.parametrize("signal", [-100.0, -10.0, 0.0, 10.0, 100.0])
def test_soft_bool_clamped(signal: float):
    result = _soft_bool(signal)
    assert 0.01 <= result <= 0.99
    assert not math.isnan(result)


def test_rising_unemployment_produces_high_p():
    """UNRATE rising 1pp above 12m mean → P(UnemploymentRising) > 0.9."""
    obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(5.0 if i == 0 else 4.0), series_id="UNRATE")
        for i in range(15)
    ]
    sig, _ = _compute_unemployment_rising(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.9, f"Expected P > 0.9 for unemployment 1pp above mean, got {p:.3f}"


def test_falling_unemployment_produces_low_p():
    """UNRATE falling 0.5pp below 12m mean → P(UnemploymentRising) < 0.2."""
    obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(3.5 if i == 0 else 4.0), series_id="UNRATE")
        for i in range(15)
    ]
    sig, _ = _compute_unemployment_rising(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.2, f"Expected P < 0.2 for unemployment 0.5pp below mean, got {p:.3f}"


def test_positive_real_wage_growth():
    """Wages growing 5% YoY, CPI 2% → real wage +3% → P(RealWageGrowthPositive) > 0.9."""
    wage_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(105.0 if i == 0 else 100.0), series_id="CES0500000003")
        for i in range(14)
    ]
    cpi_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(102.0 if i == 0 else 100.0), series_id="CPIAUCSL")
        for i in range(14)
    ]
    sig, _ = _compute_real_wage_growth_positive(wage_obs, cpi_obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.9, f"Expected P > 0.9 for real wage +3%, got {p:.3f}"


def test_negative_real_wage_growth():
    """Wages 2% YoY, CPI 5% → real wage -3% → P(RealWageGrowthPositive) < 0.1."""
    wage_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(102.0 if i == 0 else 100.0), series_id="CES0500000003")
        for i in range(14)
    ]
    cpi_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(105.0 if i == 0 else 100.0), series_id="CPIAUCSL")
        for i in range(14)
    ]
    sig, _ = _compute_real_wage_growth_positive(wage_obs, cpi_obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.1, f"Expected P < 0.1 for real wage -3%, got {p:.3f}"


def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = LaborMarketPipeline.build_evidence_record(snapshot)
    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == expected_ids


def test_build_evidence_record_all_soft_observed():
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = LaborMarketPipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.probabilities is not None
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99


def test_fred_client_fetch_series_returns_observations():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "4.20"},
            {"date": "2024-04-03", "value": "4.10"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("UNRATE", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert result[0].value == 4.20


def test_fred_client_skips_missing_values():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "4.20"},
            {"date": "2024-04-03", "value": "."},
            {"date": "2024-03-03", "value": "4.00"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("UNRATE", end_date=date(2024, 5, 3)))
    assert len(result) == 2


def test_compute_snapshot_falls_back_gracefully_with_no_data():
    snapshot = compute_snapshot({}, _TARGET_DATE)
    for attr in [
        "p_unemployment_rising", "p_wage_inflation_persistent", "p_job_openings_falling",
        "p_layoff_cycle_beginning", "p_labor_productivity_weak", "p_participation_rate_falling",
        "p_real_wage_growth_positive", "p_tight_labor_market",
    ]:
        assert getattr(snapshot, attr) == 0.5, f"{attr} should be 0.5 with no data"


def test_domain_module_id_matches_candidates():
    domain = LaborMarketV1()
    mid = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == mid


def test_existence_thresholds_are_valid():
    t = LaborMarketV1().existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert t.prune_below < t.explore_band[0] < t.explore_band[1] < t.accept_above < 1.0


def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = LaborMarketV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert len(pop.active_candidates()) == 5

    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = LaborMarketPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


def test_candidates_have_distinct_edge_structures():
    domain = LaborMarketV1()
    sigs = [c.edge_structure_signature() for c in domain.initial_candidates()]
    assert len(set(sigs)) == len(sigs)


def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    mock_fred = AsyncMock(spec=FREDClient)
    observations = _make_full_observations(
        unrate_latest=5.0,   # rising → UnemploymentRising=True
        unrate_mean=4.0,
        wages_now=105.0,
        wages_yr_ago=100.0,
        cpi_now=102.0,
        cpi_yr_ago=100.0,  # real wage +3%
    )
    mock_fred.fetch_all_series = AsyncMock(return_value=observations)

    pipeline = LaborMarketPipeline(mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == {v.variable_id for v in variables.values()}
    assert "FRED" in record.source_ref
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    # UnemploymentRising should be high
    amap = {a.variable_id: a for a in record.observed_assignments}
    ur_var = variables["UnemploymentRising"]
    assert amap[ur_var.variable_id].probabilities[True] > 0.5

    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)
