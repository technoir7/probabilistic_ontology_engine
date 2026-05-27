"""
Integration tests — sovereign debt domain ingestion pipeline.

Test inventory
--------------
TEST-SD-01  All 8 variable IDs are stable across module imports
TEST-SD-02  All 5 initial candidates are valid DAGs
TEST-SD-03  All candidates share the same variable set
TEST-SD-04  Soft probabilities are clamped to [0.01, 0.99] for all signals
TEST-SD-05  Sigmoid calibration: deeply inverted dollar (USD strong) → P(DollarStrengthening) > 0.6
TEST-SD-06  Active Fed QT → P(FedBalanceSheetShrinking) > 0.9
TEST-SD-07  HY OAS above 6.5% → P(CreditDefaultRisk) > 0.5
TEST-SD-08  HY OAS below 4.5% → P(CreditDefaultRisk) < 0.5
TEST-SD-09  build_evidence_record maps all 8 variable UUIDs correctly
TEST-SD-10  build_evidence_record produces SOFT_OBSERVED missingness on all assignments
TEST-SD-11  FRED client fetch_series with mocked HTTP returns correct observations
TEST-SD-12  FRED client skips missing (".") values
TEST-SD-13  compute_snapshot falls back gracefully with insufficient data
TEST-SD-14  Domain module_id matches candidates
TEST-SD-15  Existence thresholds are within valid ranges
TEST-SD-16  Domain registers and activates in the engine
TEST-SD-17  Candidates have distinct edge structures
TEST-SD-18  Full pipeline fetch_evidence with mocked FREDClient
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

from src.domains.sovereign_debt_v1.domain import (
    SovereignDebtV1,
    get_variables,
    make_us_fiscal_stress_candidate,
    make_dollar_dominance_erosion_candidate,
    make_em_contagion_candidate,
    make_global_liquidity_crunch_candidate,
    make_null_candidate,
)
from src.domains.sovereign_debt_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
    FRED_SERIES,
)
from src.domains.sovereign_debt_v1.ingestion.pipeline import (
    SovereignDebtPipeline,
    SovereignDebtSnapshot,
    compute_snapshot,
    _soft_bool,
    _sigmoid,
    _compute_fed_balance_sheet_shrinking,
    _compute_credit_default_risk,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


def _make_obs(series_id: str, values: list[float], base_date: date = _TARGET_DATE) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=base_date - timedelta(days=i), value=v, series_id=series_id)
        for i, v in enumerate(values)
    ]


def _make_full_observations(
    dgs10_current: float = 4.50,
    dgs10_mean: float = 3.50,
    hy_spread_current: float = 4.00,
    hy_spread_mean: float = 3.80,
    dexuseu_current: float = 1.05,   # lower = stronger USD
    dexuseu_mean: float = 1.10,
    walcl_now: float = 7_800.0,
    walcl_13w: float = 8_100.0,
    dtwexbgs_current: float = 110.0,
    dtwexbgs_mean: float = 100.0,
    gfdebtn_now: float = 34_000.0,
    gfdebtn_yr_ago: float = 32_000.0,
    m2sl_now: float = 20_000.0,
    m2sl_3m_ago: float = 20_400.0,
) -> dict[str, list[FREDObservation]]:
    import numpy as np
    rng = np.random.default_rng(42)

    # DGS10: 260 daily
    dgs10_values = [dgs10_mean] * 260
    dgs10_values[0] = dgs10_current
    dgs10_obs = _make_obs("DGS10", dgs10_values)

    # BAMLH0A0HYM2: 260 daily
    hy_values = (rng.normal(hy_spread_mean, 0.30, 260)).tolist()
    hy_values[0] = hy_spread_current
    hy_obs = _make_obs("BAMLH0A0HYM2", hy_values)

    # DEXUSEU: 260 daily
    dex_values = [dexuseu_mean] * 260
    dex_values[0] = dexuseu_current
    dex_obs = _make_obs("DEXUSEU", dex_values)

    # WALCL: 20 weekly
    walcl_values = [walcl_now] + [walcl_now - (walcl_now - walcl_13w) * i / 13 for i in range(1, 14)] + [walcl_13w] * 6
    walcl_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 7), value=walcl_values[i], series_id="WALCL")
        for i in range(20)
    ]

    # DTWEXBGS: 100 weekly
    dtwex_values = [dtwexbgs_mean] * 100
    dtwex_values[0] = dtwexbgs_current
    dtwex_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 7), value=dtwex_values[i], series_id="DTWEXBGS")
        for i in range(100)
    ]

    # GFDEBTN: quarterly — 8 quarters
    gfdebtn_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 90),
            value=(gfdebtn_now if i == 0 else gfdebtn_yr_ago if i == 4 else
                   gfdebtn_now - (gfdebtn_now - gfdebtn_yr_ago) * i / 4),
            series_id="GFDEBTN",
        )
        for i in range(8)
    ]

    # M2SL: monthly — 6 months
    m2sl_values = [m2sl_now, m2sl_now, m2sl_now, m2sl_3m_ago, m2sl_3m_ago, m2sl_3m_ago]
    m2sl_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=m2sl_values[i], series_id="M2SL")
        for i in range(6)
    ]

    return {
        "DGS10": dgs10_obs,
        "BAMLH0A0HYM2": hy_obs,
        "DEXUSEU": dex_obs,
        "WALCL": walcl_obs,
        "DTWEXBGS": dtwex_obs,
        "GFDEBTN": gfdebtn_obs,
        "M2SL": m2sl_obs,
    }


# ---------------------------------------------------------------------------
# TEST-SD-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = SovereignDebtV1()
    cands = domain.initial_candidates()
    cand_vars = {v.name: v.variable_id for v in cands[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


# ---------------------------------------------------------------------------
# TEST-SD-02 — All 5 candidates are valid DAGs
# ---------------------------------------------------------------------------

def test_all_candidates_are_dags():
    factories = [
        make_us_fiscal_stress_candidate,
        make_dollar_dominance_erosion_candidate,
        make_em_contagion_candidate,
        make_global_liquidity_crunch_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG constraint"


# ---------------------------------------------------------------------------
# TEST-SD-03 — All candidates share the canonical variable set
# ---------------------------------------------------------------------------

def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    factories = [
        make_us_fiscal_stress_candidate,
        make_dollar_dominance_erosion_candidate,
        make_em_contagion_candidate,
        make_global_liquidity_crunch_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        cand_names = {v.name for v in cand.variables}
        assert cand_names == expected_names
        assert {v.variable_id for v in cand.variables} == expected_ids


# ---------------------------------------------------------------------------
# TEST-SD-04 — Soft probabilities clamped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [-100.0, -10.0, 0.0, 10.0, 100.0])
def test_soft_bool_clamped(signal: float):
    result = _soft_bool(signal)
    assert 0.01 <= result <= 0.99
    assert not math.isnan(result)


# ---------------------------------------------------------------------------
# TEST-SD-05 — DollarStrengthening calibration
# ---------------------------------------------------------------------------

def test_strong_usd_produces_high_dollar_strengthening_p():
    """USD very strong (DEXUSEU far below mean) → P(DollarStrengthening) > 0.6."""
    obs = _make_full_observations(dexuseu_current=0.95, dexuseu_mean=1.15)
    snap = compute_snapshot(obs, _TARGET_DATE)
    assert snap.p_dollar_strengthening > 0.6, \
        f"Expected P > 0.6 for strong USD, got {snap.p_dollar_strengthening:.3f}"


# ---------------------------------------------------------------------------
# TEST-SD-06 — FedBalanceSheetShrinking calibration
# ---------------------------------------------------------------------------

def test_active_qt_produces_high_fed_shrinking_p():
    """WALCL falls 3% over 13 weeks (active QT) → P(FedBalanceSheetShrinking) > 0.9."""
    walcl_values = [7_800.0] + [7_900.0 + 15.0 * i for i in range(13)] + [8_100.0] * 6
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 7),
            value=walcl_values[i],
            series_id="WALCL",
        )
        for i in range(20)
    ]
    sig, _ = _compute_fed_balance_sheet_shrinking(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.9, f"Expected P > 0.9 for active QT, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-SD-07 & 08 — CreditDefaultRisk calibration
# ---------------------------------------------------------------------------

def test_high_hy_spread_produces_high_credit_default_risk():
    """BAMLH0A0HYM2 = 7.0% (above 6.0% threshold) → P(CreditDefaultRisk) > 0.5."""
    obs = _make_obs("BAMLH0A0HYM2", [7.0] * 5)
    sig, _ = _compute_credit_default_risk(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for HY spread at 7.0%, got {p:.3f}"
    assert p > 0.8, f"Expected P > 0.8 for HY spread at 7.0%, got {p:.3f}"


def test_low_hy_spread_produces_low_credit_default_risk():
    """BAMLH0A0HYM2 = 3.5% (well below threshold) → P(CreditDefaultRisk) < 0.5."""
    obs = _make_obs("BAMLH0A0HYM2", [3.5] * 5)
    sig, _ = _compute_credit_default_risk(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for HY spread at 3.5%, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-SD-09 — build_evidence_record maps all 8 variable UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids


# ---------------------------------------------------------------------------
# TEST-SD-10 — All assignments are SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.probabilities is not None
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# TEST-SD-11 — FRED client with mocked HTTP
# ---------------------------------------------------------------------------

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
    result = asyncio.run(client.fetch_series("DGS10", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert result[0].obs_date == date(2024, 5, 3)
    assert result[0].value == 4.50
    assert result[0].series_id == "DGS10"


# ---------------------------------------------------------------------------
# TEST-SD-12 — FRED client skips missing values
# ---------------------------------------------------------------------------

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
    result = asyncio.run(client.fetch_series("DGS10", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert date(2024, 5, 2) not in {o.obs_date for o in result}


# ---------------------------------------------------------------------------
# TEST-SD-13 — Graceful fallback with insufficient data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_gracefully_with_no_data():
    snapshot = compute_snapshot({}, _TARGET_DATE)
    assert snapshot.p_us_yield_spiking == 0.5
    assert snapshot.p_spread_widening == 0.5
    assert snapshot.p_dollar_strengthening == 0.5
    assert snapshot.p_fed_balance_sheet_shrinking == 0.5
    assert snapshot.p_em_stress_elevated == 0.5
    assert snapshot.p_fiscal_dominance_risk == 0.5
    assert snapshot.p_credit_default_risk == 0.5
    assert snapshot.p_global_liquidity_contracting == 0.5


# ---------------------------------------------------------------------------
# TEST-SD-14 — Domain module_id matches candidates
# ---------------------------------------------------------------------------

def test_domain_module_id_matches_candidates():
    domain = SovereignDebtV1()
    module_id = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == module_id


# ---------------------------------------------------------------------------
# TEST-SD-15 — Existence thresholds are valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    domain = SovereignDebtV1()
    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-SD-16 — Domain registers in the engine
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = SovereignDebtV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert len(pop.active_candidates()) == 5

    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-SD-17 — Candidates have distinct edge structures
# ---------------------------------------------------------------------------

def test_candidates_have_distinct_edge_structures():
    domain = SovereignDebtV1()
    candidates = domain.initial_candidates()
    signatures = [c.edge_structure_signature() for c in candidates]
    assert len(set(signatures)) == len(signatures), \
        "Some candidates share the same edge structure"


# ---------------------------------------------------------------------------
# TEST-SD-18 — Full pipeline fetch_evidence with mocked FREDClient
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    mock_fred = AsyncMock(spec=FREDClient)
    observations = _make_full_observations(
        walcl_now=7_800.0,   # QT → FedBalanceSheetShrinking=True
        walcl_13w=8_100.0,
        hy_spread_current=7.0,  # > 6.0% threshold → CreditDefaultRisk=True
    )
    mock_fred.fetch_all_series = AsyncMock(return_value=observations)

    pipeline = SovereignDebtPipeline(mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}
    assert "FRED" in record.source_ref

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)
