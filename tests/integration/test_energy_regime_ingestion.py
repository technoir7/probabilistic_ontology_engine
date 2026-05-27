"""
Integration tests — energy regime domain ingestion pipeline.

Test inventory
--------------
TEST-ER-01  All 8 variable IDs are stable across module imports
TEST-ER-02  All 5 initial candidates are valid DAGs
TEST-ER-03  All candidates share the same variable set
TEST-ER-04  Soft probabilities are clamped to [0.01, 0.99]
TEST-ER-05  High energy CPI YoY → P(EnergyInflationPersistent) > 0.5
TEST-ER-06  Low energy CPI YoY → P(EnergyInflationPersistent) < 0.5
TEST-ER-07  build_evidence_record maps all 8 variable UUIDs correctly
TEST-ER-08  build_evidence_record produces SOFT_OBSERVED missingness
TEST-ER-09  compute_snapshot falls back gracefully with no data
TEST-ER-10  Domain module_id matches candidates
TEST-ER-11  Existence thresholds are within valid ranges
TEST-ER-12  Domain registers in engine and evidence is ingested
TEST-ER-13  Candidates have distinct edge structures
TEST-ER-14  Full pipeline fetch_evidence with mocked FRED + yfinance
TEST-ER-15  FRED client skips missing values
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
import numpy as np

from src.domains.energy_regime_v1.domain import (
    EnergyRegimeV1,
    get_variables,
    make_supply_shock_candidate,
    make_demand_driven_candidate,
    make_geopolitical_premium_candidate,
    make_renewables_transition_candidate,
    make_null_candidate,
)
from src.domains.energy_regime_v1.ingestion.fred_client import FREDClient, FREDObservation
from src.domains.energy_regime_v1.ingestion.yfinance_client import EnergyYFinanceClient, YFObservation
from src.domains.energy_regime_v1.ingestion.pipeline import (
    EnergyRegimePipeline,
    EnergyRegimeSnapshot,
    compute_snapshot,
    _soft_bool,
    _compute_energy_inflation_persistent,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import MissingnessType

_TARGET_DATE = date(2024, 5, 3)


def _make_fred_obs(series_id: str, values: list[float], step_days: int = 1) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * step_days), value=v, series_id=series_id)
        for i, v in enumerate(values)
    ]


def _make_yf_obs(ticker: str, prices: list[float]) -> list[YFObservation]:
    return [
        YFObservation(obs_date=_TARGET_DATE - timedelta(days=i), close_price=p, ticker=ticker)
        for i, p in enumerate(prices)
    ]


def _make_full_yf_observations(
    clf_now: float = 80.0, clf_13w_ago: float = 70.0,
    ngf_now: float = 2.50, ngf_13w_ago: float = 2.20,
    xle_now: float = 90.0, xle_13w_ago: float = 82.0,
    icln_now: float = 14.0, icln_13w_ago: float = 13.0,
) -> dict[str, list[YFObservation]]:
    rng = np.random.default_rng(42)

    def _price_series(now: float, ago: float, ticker: str) -> list[YFObservation]:
        prices = list(rng.normal(now, now * 0.02, 400).tolist())
        prices[0] = now
        prices[91] = ago
        return _make_yf_obs(ticker, [abs(p) for p in prices])

    return {
        "CL=F":  _price_series(clf_now, clf_13w_ago, "CL=F"),
        "NG=F":  _price_series(ngf_now, ngf_13w_ago, "NG=F"),
        "XLE":   _price_series(xle_now, xle_13w_ago, "XLE"),
        "ICLN":  _price_series(icln_now, icln_13w_ago, "ICLN"),
    }


def _make_full_fred_observations(
    wti_now: float = 80.0, wti_13w_ago: float = 70.0,
    cpiengsl_latest: float = 120.0, cpiengsl_yr_ago: float = 110.0,
    indpro_now: float = 104.0, indpro_3m_ago: float = 103.0,
    unrate_now: float = 3.9, unrate_3m_ago: float = 3.8,
) -> dict[str, list[FREDObservation]]:
    rng = np.random.default_rng(42)

    wti_values = list(rng.normal(wti_now, 2.0, 300).tolist())
    wti_values[0] = wti_now
    wti_obs = _make_fred_obs("DCOILWTICO", [abs(v) for v in wti_values])

    cpiengsl_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(cpiengsl_latest if i == 0 else cpiengsl_yr_ago if i >= 12 else
                   cpiengsl_latest - (cpiengsl_latest - cpiengsl_yr_ago) * i / 12),
            series_id="CPIENGSL",
        )
        for i in range(15)
    ]

    indpro_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(indpro_now if i == 0 else indpro_3m_ago), series_id="INDPRO")
        for i in range(6)
    ]

    unrate_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(unrate_now if i == 0 else unrate_3m_ago), series_id="UNRATE")
        for i in range(6)
    ]

    return {
        "DCOILWTICO": wti_obs,
        "CPIENGSL": cpiengsl_obs,
        "INDPRO": indpro_obs,
        "UNRATE": unrate_obs,
    }


def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = EnergyRegimeV1()
    cand_vars = {v.name: v.variable_id for v in domain.initial_candidates()[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


def test_all_candidates_are_dags():
    for factory in [
        make_supply_shock_candidate,
        make_demand_driven_candidate,
        make_geopolitical_premium_candidate,
        make_renewables_transition_candidate,
        make_null_candidate,
    ]:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG"


def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    for factory in [
        make_supply_shock_candidate,
        make_demand_driven_candidate,
        make_geopolitical_premium_candidate,
        make_renewables_transition_candidate,
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


def test_high_energy_inflation_produces_high_p():
    """CPIENGSL YoY = 15% (well above 5% threshold) → P(EnergyInflationPersistent) > 0.5."""
    obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(115.0 if i == 0 else 100.0), series_id="CPIENGSL")
        for i in range(15)
    ]
    sig, _ = _compute_energy_inflation_persistent(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for 15% energy inflation, got {p:.3f}"


def test_low_energy_inflation_produces_low_p():
    """CPIENGSL YoY = 2% (below 5% threshold) → P(EnergyInflationPersistent) < 0.5."""
    obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30),
                        value=(102.0 if i == 0 else 100.0), series_id="CPIENGSL")
        for i in range(15)
    ]
    sig, _ = _compute_energy_inflation_persistent(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for 2% energy inflation, got {p:.3f}"


def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    yf_obs = _make_full_yf_observations()
    fred_obs = _make_full_fred_observations()
    snapshot = compute_snapshot(yf_obs, fred_obs, _TARGET_DATE)
    record = EnergyRegimePipeline.build_evidence_record(snapshot)
    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == expected_ids


def test_build_evidence_record_all_soft_observed():
    yf_obs = _make_full_yf_observations()
    fred_obs = _make_full_fred_observations()
    snapshot = compute_snapshot(yf_obs, fred_obs, _TARGET_DATE)
    record = EnergyRegimePipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99


def test_compute_snapshot_falls_back_gracefully_with_no_data():
    snapshot = compute_snapshot({}, {}, _TARGET_DATE)
    for attr in [
        "p_oil_price_surge", "p_nat_gas_price_surge", "p_energy_equity_momentum",
        "p_opec_supply_constraint", "p_renewables_displacement",
        "p_energy_inflation_persistent", "p_geopolitical_risk_elevated",
        "p_demand_destruction_risk",
    ]:
        assert getattr(snapshot, attr) == 0.5, f"{attr} should be 0.5 with no data"


def test_domain_module_id_matches_candidates():
    domain = EnergyRegimeV1()
    mid = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == mid


def test_existence_thresholds_are_valid():
    t = EnergyRegimeV1().existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert t.prune_below < t.explore_band[0] < t.explore_band[1] < t.accept_above < 1.0


def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = EnergyRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert len(pop.active_candidates()) == 5

    yf_obs = _make_full_yf_observations()
    fred_obs = _make_full_fred_observations()
    snapshot = compute_snapshot(yf_obs, fred_obs, _TARGET_DATE)
    record = EnergyRegimePipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


def test_candidates_have_distinct_edge_structures():
    domain = EnergyRegimeV1()
    sigs = [c.edge_structure_signature() for c in domain.initial_candidates()]
    assert len(set(sigs)) == len(sigs)


def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()

    mock_fred = AsyncMock(spec=FREDClient)
    mock_fred.fetch_all_series = AsyncMock(return_value=_make_full_fred_observations(
        cpiengsl_latest=115.0, cpiengsl_yr_ago=100.0  # 15% YoY → EnergyInflationPersistent=True
    ))

    mock_yf = AsyncMock(spec=EnergyYFinanceClient)
    mock_yf.fetch_all = AsyncMock(return_value=_make_full_yf_observations())

    pipeline = EnergyRegimePipeline(mock_fred, mock_yf)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == {v.variable_id for v in variables.values()}
    assert "yfinance" in record.source_ref or "FRED" in record.source_ref
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    # Energy inflation should be elevated with 15% YoY
    amap = {a.variable_id: a for a in record.observed_assignments}
    energy_inflation_var = variables["EnergyInflationPersistent"]
    ei_assignment = amap[energy_inflation_var.variable_id]
    assert ei_assignment.probabilities[True] > 0.5


def test_fred_client_skips_missing_values():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "80.0"},
            {"date": "2024-05-02", "value": "."},
            {"date": "2024-05-01", "value": "79.5"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("DCOILWTICO", end_date=date(2024, 5, 3)))
    assert len(result) == 2
