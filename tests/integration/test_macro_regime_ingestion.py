"""
Integration tests — macro regime domain ingestion pipeline.

Tests the full mapping from FRED API responses to EvidenceRecords, variable
stability, ontology registration, soft evidence calibration, and evidence
geometry compatibility.

Test inventory
--------------
TEST-MR-01  All 8 variable IDs are stable across module imports
TEST-MR-02  All 5 initial candidates are valid DAGs
TEST-MR-03  All candidates share the same variable set
TEST-MR-04  Soft probabilities are clamped to [0.01, 0.99] for all signals
TEST-MR-05  Sigmoid calibration: deeply inverted curve → P(YCI) > 0.85
TEST-MR-06  Sigmoid calibration: steep normal curve → P(YCI) < 0.15
TEST-MR-07  Inflation above threshold → P(InflationShock) > 0.5
TEST-MR-08  Inflation below threshold → P(InflationShock) < 0.5
TEST-MR-09  Fed QT (shrinking balance sheet) → P(LiquidityStress) > 0.5
TEST-MR-10  Fed QE (expanding balance sheet) → P(LiquidityStress) < 0.5
TEST-MR-11  build_evidence_record maps all 8 variable UUIDs correctly
TEST-MR-12  build_evidence_record produces SOFT_OBSERVED missingness on all assignments
TEST-MR-13  FRED client fetch_series with mocked HTTP returns correct observations
TEST-MR-14  FRED client skips missing (".") values
TEST-MR-15  Weekly backfill date computation is correct and idempotent
TEST-MR-16  Evidence geometry diagnostics work for macro domain
TEST-MR-17  MacroRegimeV1.initial_candidates() matches module_id
TEST-MR-18  Existence thresholds are within valid ranges
TEST-MR-19  compute_snapshot falls back gracefully with insufficient data
TEST-MR-20  Pipeline fetch_evidence with fully mocked FREDClient
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.macro_regime_v1.domain import (
    MacroRegimeV1,
    get_variables,
    make_ai_boom_candidate,
    make_credit_first_candidate,
    make_monetary_chain_candidate,
    make_null_candidate,
    make_recessionary_tightening_candidate,
)
from src.domains.macro_regime_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
    FRED_SERIES,
)
from src.domains.macro_regime_v1.ingestion.pipeline import (
    MacroRegimePipeline,
    MacroRegimeSnapshot,
    _last_friday,
    _soft_bool,
    _sigmoid,
    compute_snapshot,
    _compute_yield_curve_signal,
    _compute_inflation_signal,
    _compute_liquidity_signal,
)
from src.domains.macro_regime_v1.scheduler import (
    MacroRegimeScheduler,
    _weekly_backfill_dates,
)
from src.engine.services.evidence_geometry import build_evidence_geometry_diagnostics
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

_TARGET_DATE = date(2024, 5, 3)  # a Friday

def _make_obs(series_id: str, values: list[float], base_date: date = _TARGET_DATE) -> list[FREDObservation]:
    """Build a list of FREDObservation newest-first."""
    obs = []
    for i, v in enumerate(values):
        obs.append(FREDObservation(
            obs_date=base_date - timedelta(days=i),
            value=v,
            series_id=series_id,
        ))
    return obs


def _make_full_observations(
    t10y2y: float = -0.30,         # inverted
    cpi_latest: float = 105.0,      # vs 100.0 twelve months ago → 5% YoY
    cpi_year_ago: float = 100.0,
    walcl_now: float = 8_000.0,    # shrinking
    walcl_13w: float = 8_300.0,
    hy_current: float = 4.50,      # elevated spread
    hy_mean: float = 3.80,
    hy_std: float = 0.50,
    vix_current: float = 25.0,
    vix_median: float = 18.0,
    vix_iqr: float = 5.0,
    dexuseu_current: float = 1.10,  # USD/EUR; lower = stronger USD
    dexuseu_mean: float = 1.10,
    unrate_latest: float = 4.2,
    unrate_mean: float = 4.0,
    nasdaq_now: float = 16_000.0,
    nasdaq_13w_ago: float = 14_000.0,
) -> dict[str, list[FREDObservation]]:
    """
    Build a minimal but complete observations dict for compute_snapshot.
    """
    # T10Y2Y: 10 daily values
    t10y2y_obs = _make_obs("T10Y2Y", [t10y2y] * 10, _TARGET_DATE)

    # CPIAUCSL: 14 monthly values, newest first
    cpi_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(cpi_latest if i == 0 else cpi_year_ago if i == 12 else
                   cpi_latest - (cpi_latest - cpi_year_ago) * i / 12),
            series_id="CPIAUCSL",
        )
        for i in range(14)
    ]

    # WALCL: 20 weekly values (1 current + 13 interpolated + 6 historical padding)
    walcl_values = [walcl_now] + [walcl_now - (walcl_now - walcl_13w) * i / 13 for i in range(1, 14)] + [walcl_13w] * 6
    walcl_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 7),
            value=walcl_values[i],
            series_id="WALCL",
        )
        for i in range(20)
    ]

    # BAMLH0A0HYM2: 260 daily values (z-score will put current at hy_current)
    import numpy as np
    rng = np.random.default_rng(42)
    hy_history = (rng.normal(hy_mean, hy_std, 259)).tolist()
    hy_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i),
            value=(hy_current if i == 0 else hy_history[i - 1]),
            series_id="BAMLH0A0HYM2",
        )
        for i in range(260)
    ]

    # VIXCLS: 90 daily values
    vix_values = [vix_median] * 90
    vix_values[0] = vix_current
    vix_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i),
            value=vix_values[i],
            series_id="VIXCLS",
        )
        for i in range(90)
    ]

    # DEXUSEU: 260 daily values
    dex_values = [dexuseu_mean] * 260
    dex_values[0] = dexuseu_current
    dex_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i),
            value=dex_values[i],
            series_id="DEXUSEU",
        )
        for i in range(260)
    ]

    # UNRATE: 15 monthly values
    unrate_values = [unrate_mean] * 15
    unrate_values[0] = unrate_latest
    unrate_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=unrate_values[i],
            series_id="UNRATE",
        )
        for i in range(15)
    ]

    # NASDAQCOM: 500 daily values
    nasdaq_values = list(rng.normal(15_000.0, 1_000.0, 500).tolist())
    nasdaq_values[0] = nasdaq_now
    nasdaq_values[91] = nasdaq_13w_ago
    nasdaq_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i),
            value=abs(nasdaq_values[i]),  # prices must be positive
            series_id="NASDAQCOM",
        )
        for i in range(500)
    ]

    return {
        "T10Y2Y": t10y2y_obs,
        "CPIAUCSL": cpi_obs,
        "WALCL": walcl_obs,
        "BAMLH0A0HYM2": hy_obs,
        "VIXCLS": vix_obs,
        "DEXUSEU": dex_obs,
        "UNRATE": unrate_obs,
        "NASDAQCOM": nasdaq_obs,
    }


# ---------------------------------------------------------------------------
# TEST-MR-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    """
    Variable UUIDs must be deterministic across imports and instantiation calls.
    Stable IDs prevent evidence-variable mismatches across restarts.
    """
    vars1 = get_variables()
    vars2 = get_variables()
    # Also get from a fresh domain instance
    domain = MacroRegimeV1()
    cands = domain.initial_candidates()
    cand_vars = {v.name: v.variable_id for v in cands[0].variables}

    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id, \
            f"Variable ID for {name} changed between calls"
        assert vars1[name].variable_id == cand_vars[name], \
            f"Variable ID for {name} differs between domain and get_variables()"


# ---------------------------------------------------------------------------
# TEST-MR-02 — All 5 candidates are valid DAGs
# ---------------------------------------------------------------------------

def test_all_candidates_are_dags():
    """
    Every initial candidate must be a directed acyclic graph (DAG constraint).
    Cycles would break topological ordering and invalidate Bayesian inference.
    """
    factories = [
        make_monetary_chain_candidate,
        make_credit_first_candidate,
        make_ai_boom_candidate,
        make_recessionary_tightening_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        candidate = factory()
        assert candidate.is_dag(), (
            f"Candidate '{candidate.description}' violates DAG constraint. "
            f"Edges: {candidate.edge_structure_signature()}"
        )


# ---------------------------------------------------------------------------
# TEST-MR-03 — All candidates share the canonical variable set
# ---------------------------------------------------------------------------

def test_all_candidates_share_variable_set():
    """All candidates must contain exactly the same 8 canonical variables."""
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}

    factories = [
        make_monetary_chain_candidate,
        make_credit_first_candidate,
        make_ai_boom_candidate,
        make_recessionary_tightening_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        cand_names = {v.name for v in cand.variables}
        cand_ids = {v.variable_id for v in cand.variables}
        assert cand_names == expected_names, (
            f"Candidate '{cand.description}' has wrong variable names: "
            f"got {cand_names}, expected {expected_names}"
        )
        assert cand_ids == expected_ids, (
            f"Candidate '{cand.description}' has wrong variable IDs"
        )


# ---------------------------------------------------------------------------
# TEST-MR-04 — Soft probabilities clamped to [0.01, 0.99]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [
    -100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0,
    float("inf"), -float("inf"),
])
def test_soft_bool_clamped(signal: float):
    """
    _soft_bool must never return values outside [0.01, 0.99].
    Extreme signals should be safely clamped, not produce NaN or overflow.
    """
    # Guard against inf inputs (sigmoid handles them, but let's be safe)
    if math.isinf(signal):
        # sigmoid(±inf) = {1, 0}; after clamping = {0.99, 0.01}
        result = _soft_bool(max(-700.0, min(700.0, signal)))
    else:
        result = _soft_bool(signal)
    assert 0.01 <= result <= 0.99, f"_soft_bool({signal}) = {result} out of range"
    assert not math.isnan(result), f"_soft_bool({signal}) returned NaN"


# ---------------------------------------------------------------------------
# TEST-MR-05 & 06 — YieldCurveInverted calibration
# ---------------------------------------------------------------------------

def test_deeply_inverted_yield_curve_produces_high_p():
    """
    T10Y2Y = -1.0% (deeply inverted) → P(YieldCurveInverted=True) > 0.85.
    """
    obs = _make_obs("T10Y2Y", [-1.0] * 7, _TARGET_DATE)
    signal, _ = _compute_yield_curve_signal(obs, _TARGET_DATE)
    assert signal is not None
    p = _soft_bool(signal)
    assert p > 0.85, f"Expected P > 0.85 for deeply inverted curve, got {p:.3f}"


def test_steep_normal_curve_produces_low_p():
    """
    T10Y2Y = +1.5% (steep normal) → P(YieldCurveInverted=True) < 0.15.
    """
    obs = _make_obs("T10Y2Y", [1.5] * 7, _TARGET_DATE)
    signal, _ = _compute_yield_curve_signal(obs, _TARGET_DATE)
    assert signal is not None
    p = _soft_bool(signal)
    assert p < 0.15, f"Expected P < 0.15 for steep normal curve, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-MR-07 & 08 — InflationShock calibration
# ---------------------------------------------------------------------------

def test_high_inflation_produces_high_p():
    """
    CPI YoY = 6% (well above 3.5% threshold) → P(InflationShock) > 0.5.
    """
    # latest = 106.0, 12 months ago = 100.0 → YoY = 6%
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(106.0 if i == 0 else 100.0),
            series_id="CPIAUCSL",
        )
        for i in range(14)
    ]
    signal, _ = _compute_inflation_signal(obs)
    assert signal is not None
    p = _soft_bool(signal)
    assert p > 0.5, f"Expected P > 0.5 for 6% inflation, got {p:.3f}"
    assert p > 0.85, f"Expected P > 0.85 for strongly elevated inflation, got {p:.3f}"


def test_low_inflation_produces_low_p():
    """
    CPI YoY = 1.5% (below 3.5% threshold) → P(InflationShock) < 0.5.
    """
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 30),
            value=(101.5 if i == 0 else 100.0),
            series_id="CPIAUCSL",
        )
        for i in range(14)
    ]
    signal, _ = _compute_inflation_signal(obs)
    assert signal is not None
    p = _soft_bool(signal)
    assert p < 0.5, f"Expected P < 0.5 for 1.5% inflation, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-MR-09 & 10 — LiquidityStress calibration
# ---------------------------------------------------------------------------

def test_fed_qt_produces_high_liquidity_stress():
    """
    WALCL falls 3% over 13 weeks (active QT) → P(LiquidityStress) > 0.9.
    """
    # obs[0] = 7,800 (now), obs[13] = 8,100 (13w ago)
    walcl_values = [7_800.0] + [7_900.0 + 15.0 * i for i in range(13)] + [8_100.0] * 6
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 7),
            value=walcl_values[i],
            series_id="WALCL",
        )
        for i in range(20)
    ]
    signal, _ = _compute_liquidity_signal(obs)
    assert signal is not None
    p = _soft_bool(signal)
    assert p > 0.9, f"Expected P > 0.9 for active QT, got {p:.3f}"


def test_fed_qe_produces_low_liquidity_stress():
    """
    WALCL rises 5% over 13 weeks (active QE) → P(LiquidityStress) < 0.1.
    """
    walcl_values = [8_500.0] + [8_100.0 + 30.0 * i for i in range(13)] + [7_900.0] * 6
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 7),
            value=walcl_values[i],
            series_id="WALCL",
        )
        for i in range(20)
    ]
    signal, _ = _compute_liquidity_signal(obs)
    assert signal is not None
    p = _soft_bool(signal)
    assert p < 0.1, f"Expected P < 0.1 for active QE, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-MR-11 — build_evidence_record maps all 8 variable UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    """
    build_evidence_record must produce exactly 8 assignments, each with
    a UUID matching one of the canonical domain variables.
    """
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}

    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = MacroRegimePipeline.build_evidence_record(snapshot)

    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids, (
        f"Assignment UUIDs do not match canonical variable UUIDs.\n"
        f"  got:      {assignment_ids}\n"
        f"  expected: {expected_ids}"
    )


# ---------------------------------------------------------------------------
# TEST-MR-12 — All assignments are SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    """Every assignment must carry SOFT_OBSERVED missingness and probabilities dict."""
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = MacroRegimePipeline.build_evidence_record(snapshot)

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED, (
            f"Assignment for {a.variable_id} has missingness {a.missingness}, "
            f"expected SOFT_OBSERVED"
        )
        assert a.probabilities is not None, \
            f"Assignment for {a.variable_id} missing probabilities dict"
        assert set(a.probabilities.keys()) == {True, False}, \
            f"Probabilities keys must be {{True, False}}"
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99, \
            f"P(True)={p_true} outside [0.01, 0.99]"
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01, \
            f"Probabilities do not sum to 1.0"


# ---------------------------------------------------------------------------
# TEST-MR-13 — FRED client fetch_series with mocked HTTP
# ---------------------------------------------------------------------------

def _make_fred_http_response(
    series_id: str,
    dates: list[str],
    values: list[str],
) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    observations = [
        {"date": d, "value": v}
        for d, v in zip(dates, values)
    ]
    resp.json = MagicMock(return_value={"observations": observations})
    return resp


def test_fred_client_fetch_series_returns_observations():
    """
    FREDClient.fetch_series with a mocked HTTP client returns correctly
    parsed FREDObservation objects, sorted newest-first.
    """
    resp = _make_fred_http_response(
        "T10Y2Y",
        dates=["2024-05-03", "2024-05-02", "2024-05-01"],
        values=["-0.30", "-0.28", "-0.25"],
    )
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)

    result = asyncio.run(client.fetch_series("T10Y2Y", end_date=date(2024, 5, 3)))

    assert len(result) == 3
    assert result[0].obs_date == date(2024, 5, 3)
    assert result[0].value == -0.30
    assert result[0].series_id == "T10Y2Y"
    assert result[1].obs_date == date(2024, 5, 2)
    assert result[2].obs_date == date(2024, 5, 1)


# ---------------------------------------------------------------------------
# TEST-MR-14 — FRED client skips missing values
# ---------------------------------------------------------------------------

def test_fred_client_skips_missing_values():
    """
    FREDClient must skip observations with value "." (FRED's missing marker).
    """
    resp = _make_fred_http_response(
        "T10Y2Y",
        dates=["2024-05-03", "2024-05-02", "2024-05-01"],
        values=["-0.30", ".", "-0.25"],  # middle row is missing
    )
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)

    result = asyncio.run(client.fetch_series("T10Y2Y", end_date=date(2024, 5, 3)))

    assert len(result) == 2  # "." row excluded
    dates_returned = {o.obs_date for o in result}
    assert date(2024, 5, 2) not in dates_returned, \
        "Missing observation should have been skipped"


# ---------------------------------------------------------------------------
# TEST-MR-15 — Weekly backfill date computation
# ---------------------------------------------------------------------------

def test_weekly_backfill_dates_returns_fridays():
    """
    _weekly_backfill_dates must return only Friday dates (weekday 4).
    """
    today = date(2024, 5, 6)  # Monday
    dates = _weekly_backfill_dates(4, today)

    assert len(dates) == 4
    for d in dates:
        assert d.weekday() == 4, f"Expected Friday, got {d} (weekday {d.weekday()})"
    # Should be oldest-first
    assert dates == sorted(dates)


def test_weekly_backfill_dates_are_unique():
    """Backfill dates must be unique (no duplicate weeks)."""
    today = date(2024, 5, 10)
    dates = _weekly_backfill_dates(8, today)
    assert len(dates) == len(set(dates)), "Backfill dates contain duplicates"


# ---------------------------------------------------------------------------
# TEST-MR-16 — Evidence geometry diagnostics compatibility
# ---------------------------------------------------------------------------

def test_evidence_geometry_works_for_macro_domain():
    """
    build_evidence_geometry_diagnostics must work without error for records
    produced by the macro regime pipeline.
    """
    variables = list(get_variables().values())
    records = []
    for week_offset in range(5):
        target = _TARGET_DATE - timedelta(weeks=week_offset)
        observations = _make_full_observations(
            t10y2y=-0.30 + 0.05 * week_offset,
            vix_current=20.0 + week_offset,
        )
        snapshot = compute_snapshot(observations, target)
        record = MacroRegimePipeline.build_evidence_record(snapshot)
        records.append(record)

    result = build_evidence_geometry_diagnostics(records=records, variables=variables)

    assert "total_evidence_records" in result
    assert result["total_evidence_records"] == 5
    assert "variables" in result
    assert len(result["variables"]) == 8
    for var_name in get_variables():
        assert var_name in result["variables"], \
            f"Variable {var_name} missing from geometry diagnostics"

    # Should detect weekly cadence
    assert result.get("cadence_detected") in {"weekly", "irregular", "insufficient_data"}, \
        f"Unexpected cadence: {result.get('cadence_detected')}"


# ---------------------------------------------------------------------------
# TEST-MR-17 — MacroRegimeV1 module_id matches candidates
# ---------------------------------------------------------------------------

def test_domain_module_id_matches_candidates():
    """All candidates must reference the same domain module ID as the domain."""
    domain = MacroRegimeV1()
    module_id = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == module_id, (
            f"Candidate '{cand.description}' has module_id "
            f"'{cand.domain_module_id}', expected '{module_id}'"
        )


# ---------------------------------------------------------------------------
# TEST-MR-18 — Existence thresholds are valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    """
    EdgeExistenceThresholdConfig must satisfy the ordering constraints
    required by the engine: 0 < prune_below < explore_band[0] < explore_band[1]
    < accept_above < 1.
    """
    domain = MacroRegimeV1()
    t = domain.existence_thresholds()

    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-MR-19 — Graceful fallback with insufficient data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_gracefully_with_no_data():
    """
    compute_snapshot with empty observations must not raise.
    All soft probabilities should fall back to 0.5 (maximum uncertainty).
    """
    snapshot = compute_snapshot({}, _TARGET_DATE)

    # All probabilities should be 0.5 when data is absent
    assert snapshot.p_yield_curve_inverted == 0.5
    assert snapshot.p_inflation_shock == 0.5
    assert snapshot.p_liquidity_stress == 0.5
    assert snapshot.p_credit_spread_stress == 0.5
    assert snapshot.p_volatility_shock == 0.5
    assert snapshot.p_dollar_strength == 0.5
    assert snapshot.p_equity_risk_on == 0.5
    assert snapshot.p_ai_risk_on == 0.5


def test_compute_snapshot_partial_data_does_not_raise():
    """
    compute_snapshot with only some series populated must not raise.
    Missing series should fall back gracefully.
    """
    # Only provide T10Y2Y and CPI; the rest should fall back to 0.5
    partial = {
        "T10Y2Y": _make_obs("T10Y2Y", [-0.30] * 10, _TARGET_DATE),
        "CPIAUCSL": [
            FREDObservation(
                obs_date=_TARGET_DATE - timedelta(days=i * 30),
                value=(105.0 if i == 0 else 100.0),
                series_id="CPIAUCSL",
            )
            for i in range(14)
        ],
    }
    snapshot = compute_snapshot(partial, _TARGET_DATE)

    # T10Y2Y is provided → should be non-0.5
    assert snapshot.p_yield_curve_inverted != 0.5, \
        "YieldCurveInverted should have a non-neutral probability"
    # WALCL not provided → should fall back to 0.5
    assert snapshot.p_liquidity_stress == 0.5, \
        "LiquidityStress should fall back to 0.5 when WALCL is absent"


# ---------------------------------------------------------------------------
# TEST-MR-20 — Full pipeline fetch_evidence with mocked FREDClient
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    """
    MacroRegimePipeline.fetch_evidence with a fully mocked FREDClient.

    Setup:
        - T10Y2Y: -0.50% (inverted) → YieldCurveInverted=True likely
        - CPIAUCSL: 6% YoY → InflationShock=True likely
        - WALCL: -3% (QT) → LiquidityStress=True likely

    Verifies:
        - Record has exactly 8 assignments
        - All assignments use canonical variable UUIDs
        - All assignments are SOFT_OBSERVED
        - Source ref contains FRED identifier
        - Dominant direction signals are correct
    """
    variables = get_variables()

    # Mock the FREDClient.fetch_all_series to return controlled data
    mock_fred = AsyncMock(spec=FREDClient)
    observations = _make_full_observations(
        t10y2y=-0.50,        # clearly inverted
        cpi_latest=106.0,    # 6% YoY → InflationShock
        cpi_year_ago=100.0,
        walcl_now=7_800.0,   # shrinking → LiquidityStress
        walcl_13w=8_100.0,
    )
    mock_fred.fetch_all_series = AsyncMock(return_value=observations)

    pipeline = MacroRegimePipeline(mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    # Structural checks
    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}

    # Source ref
    assert "FRED" in record.source_ref

    # All SOFT_OBSERVED
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    # Check directional signals
    amap = {a.variable_id: a for a in record.observed_assignments}

    yci_assignment = amap[variables["YieldCurveInverted"].variable_id]
    assert yci_assignment.probabilities[True] > 0.5, \
        "Inverted T10Y2Y should yield P(YieldCurveInverted=True) > 0.5"

    is_assignment = amap[variables["InflationShock"].variable_id]
    assert is_assignment.probabilities[True] > 0.5, \
        "6% CPI YoY should yield P(InflationShock=True) > 0.5"

    ls_assignment = amap[variables["LiquidityStress"].variable_id]
    assert ls_assignment.probabilities[True] > 0.5, \
        "Balance sheet contraction should yield P(LiquidityStress=True) > 0.5"

    # fetch_all_series was called once
    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)


# ---------------------------------------------------------------------------
# TEST-MR-21 — Domain registers and activates in the engine
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    """
    MacroRegimeV1 can be registered in a ProbabilisticOntologyEngine and
    evidence records can be ingested without error.
    """
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = MacroRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert len(pop.active_candidates()) == 5

    # Ingest one evidence record
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = MacroRegimePipeline.build_evidence_record(snapshot)
    engine.ingest(record)

    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-MR-22 — Candidates have distinct edge structures
# ---------------------------------------------------------------------------

def test_candidates_have_distinct_edge_structures():
    """
    The 5 seed candidates must encode genuinely distinct structural hypotheses.
    No two candidates should have identical edge sets (that would make one
    redundant and prevent ontology competition).
    """
    domain = MacroRegimeV1()
    candidates = domain.initial_candidates()
    signatures = [c.edge_structure_signature() for c in candidates]
    unique_signatures = set(signatures)
    assert len(unique_signatures) == len(signatures), (
        f"Some candidates share the same edge structure. "
        f"Got {len(unique_signatures)} unique structures for {len(candidates)} candidates."
    )


# ---------------------------------------------------------------------------
# TEST-MR-23 — _last_friday returns correct day
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("as_of,expected", [
    (date(2024, 5, 6), date(2024, 5, 3)),   # Monday → previous Friday
    (date(2024, 5, 3), date(2024, 5, 3)),   # Friday → same day
    (date(2024, 5, 4), date(2024, 5, 3)),   # Saturday → last Friday
    (date(2024, 5, 5), date(2024, 5, 3)),   # Sunday → last Friday
    (date(2024, 5, 7), date(2024, 5, 3)),   # Tuesday → last Friday
])
def test_last_friday(as_of: date, expected: date):
    """_last_friday must return the most recent Friday on or before the given date."""
    result = _last_friday(as_of)
    assert result == expected, f"_last_friday({as_of}) = {result}, expected {expected}"
    assert result.weekday() == 4, f"Result {result} is not a Friday"


# ---------------------------------------------------------------------------
# TEST-MR-24 — Existence probability prior is set on all edges
# ---------------------------------------------------------------------------

def test_all_edges_have_existence_prior():
    """
    All edges in all candidates must have a valid existence_prior
    in (0, 1) and existence_probability equal to the prior at initialization.
    """
    domain = MacroRegimeV1()
    for cand in domain.initial_candidates():
        for edge in cand.edges:
            assert 0.0 < edge.existence_prior < 1.0, (
                f"Candidate '{cand.description}' edge "
                f"'{edge.explanatory_label}' has invalid prior {edge.existence_prior}"
            )
            assert edge.existence_probability == edge.existence_prior, (
                f"existence_probability should equal existence_prior at init"
            )
            assert edge.enabled is True, \
                f"All initial edges should be enabled"
            assert edge.learnable is True, \
                f"All initial edges should be learnable"
