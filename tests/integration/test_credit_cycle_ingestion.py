"""
Integration tests — credit cycle domain ingestion pipeline.

Test inventory
--------------
TEST-CC-01  All 8 variable IDs are stable across module imports
TEST-CC-02  All 5 initial candidates are valid DAGs
TEST-CC-03  All candidates share the same variable set
TEST-CC-04  Soft probabilities are clamped to [0.01, 0.99]
TEST-CC-05  HY OAS above 7% → P(CorporateDefaultRisk) > 0.8
TEST-CC-06  HY OAS below 4% → P(CorporateDefaultRisk) < 0.2
TEST-CC-07  Negative credit impulse → P(CreditImpulseNegative) > 0.5
TEST-CC-08  build_evidence_record maps all 8 variable UUIDs correctly
TEST-CC-09  build_evidence_record produces SOFT_OBSERVED missingness
TEST-CC-10  FRED client fetch_series with mocked HTTP returns correct observations
TEST-CC-11  FRED client skips missing values
TEST-CC-12  compute_snapshot falls back gracefully with no data
TEST-CC-13  Domain module_id matches candidates
TEST-CC-14  Existence thresholds are within valid ranges
TEST-CC-15  Domain registers in engine and evidence is ingested
TEST-CC-16  Candidates have distinct edge structures
TEST-CC-17  Full pipeline fetch_evidence with mocked FREDClient
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

from src.domains.credit_cycle_v1.domain import (
    CreditCycleV1,
    get_variables,
    make_monetary_tightening_candidate,
    make_default_cycle_candidate,
    make_liquidity_withdrawal_candidate,
    make_credit_normalization_candidate,
    make_null_candidate,
)
from src.domains.credit_cycle_v1.ingestion.fred_client import FREDClient, FREDObservation
from src.domains.credit_cycle_v1.ingestion.pipeline import (
    CreditCyclePipeline,
    compute_snapshot,
    _soft_bool,
    _compute_corporate_default_risk,
    _compute_credit_impulse_negative,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import MissingnessType

_TARGET_DATE = date(2024, 5, 3)


def _make_obs(series_id: str, values: list[float], base_date: date = _TARGET_DATE) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=base_date - timedelta(days=i), value=v, series_id=series_id)
        for i, v in enumerate(values)
    ]


def _make_full_observations(
    hy_spread_current: float = 4.50,
    hy_spread_mean: float = 3.80,
    drtscilm_current: float = 5.0,
    drtscilm_mean: float = 3.0,
    totci_now: float = 1_000.0,
    totci_3m_ago: float = 1_020.0,
    ig_spread_current: float = 1.20,
    ig_spread_mean: float = 1.10,
    dgs5_current: float = 4.20,
    dgs5_mean: float = 3.50,
) -> dict[str, list[FREDObservation]]:
    import numpy as np
    rng = np.random.default_rng(42)

    hy_values = (rng.normal(hy_spread_mean, 0.30, 260)).tolist()
    hy_values[0] = hy_spread_current
    hy_obs = _make_obs("BAMLH0A0HYM2", hy_values)

    drtscilm_values = (rng.normal(drtscilm_mean, 1.5, 20)).tolist()
    drtscilm_values[0] = drtscilm_current
    drtscilm_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 90), value=drtscilm_values[i], series_id="DRTSCILM")
        for i in range(20)
    ]

    totci_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(totci_now if i == 0 else totci_3m_ago), series_id="TOTCI")
        for i in range(6)
    ]

    ig_values = (rng.normal(ig_spread_mean, 0.10, 260)).tolist()
    ig_values[0] = ig_spread_current
    ig_obs = _make_obs("BAMLC0A0CM", ig_values)

    dgs5_values = [dgs5_mean] * 260
    dgs5_values[0] = dgs5_current
    dgs5_obs = _make_obs("DGS5", dgs5_values)

    return {
        "BAMLH0A0HYM2": hy_obs,
        "DRTSCILM": drtscilm_obs,
        "TOTCI": totci_obs,
        "BAMLC0A0CM": ig_obs,
        "DGS5": dgs5_obs,
    }


def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = CreditCycleV1()
    cand_vars = {v.name: v.variable_id for v in domain.initial_candidates()[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


def test_all_candidates_are_dags():
    for factory in [
        make_monetary_tightening_candidate,
        make_default_cycle_candidate,
        make_liquidity_withdrawal_candidate,
        make_credit_normalization_candidate,
        make_null_candidate,
    ]:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG"


def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    for factory in [
        make_monetary_tightening_candidate,
        make_default_cycle_candidate,
        make_liquidity_withdrawal_candidate,
        make_credit_normalization_candidate,
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


def test_high_hy_spread_produces_high_corporate_default_risk():
    """HY OAS at 7.0% → P(CorporateDefaultRisk) > 0.8."""
    obs = _make_obs("BAMLH0A0HYM2", [7.0] * 5)
    sig, _ = _compute_corporate_default_risk(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.8, f"Expected P > 0.8 for HY at 7.0%, got {p:.3f}"


def test_low_hy_spread_produces_low_corporate_default_risk():
    """HY OAS at 3.5% → P(CorporateDefaultRisk) < 0.2."""
    obs = _make_obs("BAMLH0A0HYM2", [3.5] * 5)
    sig, _ = _compute_corporate_default_risk(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.2, f"Expected P < 0.2 for HY at 3.5%, got {p:.3f}"


def test_negative_credit_impulse():
    """TOTCI declining → P(CreditImpulseNegative) > 0.5."""
    obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=(950.0 if i == 0 else 1000.0), series_id="TOTCI")
        for i in range(6)
    ]
    sig, _ = _compute_credit_impulse_negative(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for declining credit, got {p:.3f}"


def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = CreditCyclePipeline.build_evidence_record(snapshot)
    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == expected_ids


def test_build_evidence_record_all_soft_observed():
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = CreditCyclePipeline.build_evidence_record(snapshot)
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
            {"date": "2024-05-03", "value": "4.50"},
            {"date": "2024-05-02", "value": "4.45"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("BAMLH0A0HYM2", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert result[0].value == 4.50


def test_fred_client_skips_missing_values():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "4.50"},
            {"date": "2024-05-02", "value": "."},
            {"date": "2024-05-01", "value": "4.40"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("BAMLH0A0HYM2", end_date=date(2024, 5, 3)))
    assert len(result) == 2


def test_compute_snapshot_falls_back_gracefully_with_no_data():
    snapshot = compute_snapshot({}, _TARGET_DATE)
    assert snapshot.p_hy_spread_elevated == 0.5
    assert snapshot.p_leveraged_loan_stress == 0.5
    assert snapshot.p_corporate_default_risk == 0.5
    assert snapshot.p_credit_impulse_negative == 0.5
    assert snapshot.p_bank_lending_tightening == 0.5
    assert snapshot.p_investment_grade_spread == 0.5
    assert snapshot.p_high_yield_issuance_falling == 0.5
    assert snapshot.p_refinancing_stress == 0.5


def test_domain_module_id_matches_candidates():
    domain = CreditCycleV1()
    mid = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == mid


def test_existence_thresholds_are_valid():
    t = CreditCycleV1().existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert t.prune_below < t.explore_band[0] < t.explore_band[1] < t.accept_above < 1.0


def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = CreditCycleV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert len(pop.active_candidates()) == 5

    obs = _make_full_observations()
    snapshot = compute_snapshot(obs, _TARGET_DATE)
    record = CreditCyclePipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


def test_candidates_have_distinct_edge_structures():
    domain = CreditCycleV1()
    sigs = [c.edge_structure_signature() for c in domain.initial_candidates()]
    assert len(set(sigs)) == len(sigs)


def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    mock_fred = AsyncMock(spec=FREDClient)
    observations = _make_full_observations(hy_spread_current=7.0)
    mock_fred.fetch_all_series = AsyncMock(return_value=observations)

    pipeline = CreditCyclePipeline(mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assert {a.variable_id for a in record.observed_assignments} == {v.variable_id for v in variables.values()}
    assert "FRED" in record.source_ref
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)
