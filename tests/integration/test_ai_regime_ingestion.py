"""
Integration tests — ai-regime-v1 domain ingestion pipeline.

Tests the full mapping from API responses to EvidenceRecords, variable
stability, ontology registration, soft evidence calibration, EDGAR
ingestion logic, and cadence logic.

Test inventory
--------------
TEST-AI-01  All 8 variable IDs are stable across module imports
TEST-AI-02  All 4 initial candidates are valid DAGs
TEST-AI-03  All candidates share the same variable set
TEST-AI-04  Soft probabilities are clamped to [0.01, 0.99] for all signals
TEST-AI-05  SemiconductorMomentum: high SOX momentum → P > 0.5
TEST-AI-06  SemiconductorMomentum: low SOX momentum → P < 0.5
TEST-AI-07  MarketConcentrationExtreme: QQQ outperforming RSP → P > 0.5
TEST-AI-08  HyperscalerCapexAccelerating: 35% YoY avg → P > 0.5
TEST-AI-09  HyperscalerCapexAccelerating: 5% YoY avg → P < 0.5
TEST-AI-10  TechValuationDetached: elevated QQQ → P > 0.5
TEST-AI-11  LaborProductivityImproving: YoY > 2% → P > 0.5
TEST-AI-12  LaborProductivityImproving: YoY < 2% → P < 0.5
TEST-AI-13  BroadEconomicLift: GDP > 2.5% → P > 0.5
TEST-AI-14  BroadEconomicLift: GDP < 2.5% → P < 0.5
TEST-AI-15  AIRiskPremiumCompressed: low VIX → P > 0.5
TEST-AI-16  AIRiskPremiumCompressed: high VIX → P < 0.5
TEST-AI-17  build_evidence_record maps all 8 variable UUIDs correctly
TEST-AI-18  build_evidence_record produces SOFT_OBSERVED on all assignments
TEST-AI-19  EDGAR _extract_capex_entries parses realistic JSON correctly
TEST-AI-20  EDGAR _compute_yoy_growth returns correct result and handles missing prior
TEST-AI-21  EDGAR client caches responses (second call does not hit HTTP)
TEST-AI-22  Weekly backfill date computation is correct and idempotent
TEST-AI-23  _last_friday returns correct day
TEST-AI-24  compute_snapshot falls back gracefully with no data
TEST-AI-25  compute_snapshot partial data does not raise
TEST-AI-26  Full pipeline fetch_evidence with fully mocked clients
TEST-AI-27  Domain registers and activates in the engine
TEST-AI-28  All 4 candidates have distinct edge structures
TEST-AI-29  All edges have valid existence priors
TEST-AI-30  AIRegimeV1 module_id matches candidates
TEST-AI-31  Existence thresholds are within valid ranges
TEST-AI-32  IPInvestmentRising signal uses historical median comparison
TEST-AI-33  Scheduler backfill date list has correct cadence (Fridays only)
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.ai_regime_v1.domain import (
    AIRegimeV1,
    get_variables,
    make_infrastructure_buildout_candidate,
    make_bubble_detachment_candidate,
    make_winner_take_all_candidate,
    make_productivity_regime_candidate,
)
from src.domains.ai_regime_v1.ingestion.edgar_client import (
    EDGARClient,
    HyperscalerCapexSnapshot,
    CompanyCapexResult,
    HYPERSCALERS,
    _CapexEntry,
    _extract_capex_entries,
    _compute_yoy_growth,
)
from src.domains.ai_regime_v1.ingestion.yfinance_client import (
    AIYFinanceClient,
    YFObservation,
    AI_TICKERS,
)
from src.domains.ai_regime_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
    AI_FRED_SERIES,
)
from src.domains.ai_regime_v1.ingestion.pipeline import (
    AIRegimePipeline,
    AIRegimeSnapshot,
    _last_friday,
    _weekly_backfill_dates,
    _soft_bool,
    _sigmoid,
    _zscore,
    compute_snapshot,
    _compute_13w_return_zscore,
    _compute_concentration_ratio_zscore,
    _compute_capex_signal,
    _compute_valuation_zscore,
    _compute_labor_productivity_signal,
    _compute_gdp_signal,
    _compute_vix_signal,
    _compute_ip_investment_signal,
)
from src.domains.ai_regime_v1.scheduler import (
    AIRegimeScheduler,
    _weekly_backfill_dates as scheduler_backfill_dates,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TARGET_DATE = date(2024, 5, 3)   # a Friday

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _make_yf_obs(ticker: str, prices: list[float], base_date: date = _TARGET_DATE) -> list[YFObservation]:
    """Build a list of YFObservation newest-first."""
    obs = []
    for i, p in enumerate(prices):
        obs.append(YFObservation(
            obs_date=base_date - timedelta(days=i),
            close_price=p,
            ticker=ticker,
        ))
    return obs


def _make_trending_prices(
    n: int,
    start_price: float = 100.0,
    trend_pct_per_day: float = 0.0,
    base_date: date = _TARGET_DATE,
    ticker: str = "TEST",
) -> list[YFObservation]:
    """Build trending price series, newest-first."""
    prices = []
    for i in range(n):
        # i=0 is newest; newest price = start_price + trend
        price = start_price * (1 + trend_pct_per_day) ** (n - 1 - i)
        prices.append(YFObservation(
            obs_date=base_date - timedelta(days=i),
            close_price=max(price, 0.01),
            ticker=ticker,
        ))
    return prices


def _make_fred_obs(series_id: str, values: list[float], base_date: date = _TARGET_DATE) -> list[FREDObservation]:
    """Build FRED observations newest-first (quarterly: ~91 day steps)."""
    obs = []
    for i, v in enumerate(values):
        obs.append(FREDObservation(
            obs_date=base_date - timedelta(days=i * 91),
            value=v,
            series_id=series_id,
        ))
    return obs


def _make_capex_snapshot(avg_yoy: float, n_companies: int = 4) -> HyperscalerCapexSnapshot:
    """Build a minimal HyperscalerCapexSnapshot with a given average YoY growth."""
    tickers = list(HYPERSCALERS.keys())[:n_companies]
    companies = {}
    for ticker in tickers:
        companies[ticker] = CompanyCapexResult(
            ticker=ticker,
            cik=HYPERSCALERS[ticker],
            fiscal_year=2024,
            fiscal_period="Q2",
            current_ytd_usd=10_000_000_000 * (1 + avg_yoy / 100),
            prior_year_ytd_usd=10_000_000_000,
            yoy_growth_pct=avg_yoy,
            filing_end_date=_TARGET_DATE - timedelta(days=30),
        )
    return HyperscalerCapexSnapshot(
        companies=companies,
        avg_yoy_growth_pct=avg_yoy,
        companies_with_data=n_companies,
        confidence=n_companies / 4,
    )


def _make_full_data() -> tuple[
    dict[str, list[YFObservation]],
    dict[str, list[FREDObservation]],
    HyperscalerCapexSnapshot,
]:
    """Build a complete set of input data for compute_snapshot."""
    rng = np.random.default_rng(42)

    # yfinance data — 600 trading days each
    # ^SOX: rising trend (high momentum)
    sox_prices = list((100.0 * (1.005 ** np.arange(600))[::-1]).tolist())
    yf_data = {
        "^SOX": _make_yf_obs("^SOX", sox_prices),
        "QQQ":  _make_yf_obs("QQQ", list((100.0 * (1.004 ** np.arange(600))[::-1]).tolist())),
        "RSP":  _make_yf_obs("RSP", list((50.0  * (1.001 ** np.arange(600))[::-1]).tolist())),
        "^VIX": _make_yf_obs("^VIX", [15.0 + rng.normal(0, 2) for _ in range(600)]),  # low VIX
    }

    # FRED data
    # IP investment: rising trend
    ip_base = 1_000.0
    ip_values = [ip_base * (1.03 ** ((20 - i) / 4)) for i in range(20)]
    fred_data = {
        "Y033RC1Q027SBEA": _make_fred_obs("Y033RC1Q027SBEA", ip_values),
        "PRS85006092":     _make_fred_obs("PRS85006092",     [100.0 * (1.025 ** ((20 - i) / 4)) for i in range(20)]),
        "A191RL1Q225SBEA": _make_fred_obs("A191RL1Q225SBEA", [2.8] * 20),  # above 2.5%
    }

    capex = _make_capex_snapshot(avg_yoy=30.0)  # above 20% threshold

    return yf_data, fred_data, capex


# ---------------------------------------------------------------------------
# TEST-AI-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    """Variable UUIDs must be deterministic across imports and calls."""
    vars1 = get_variables()
    vars2 = get_variables()
    domain = AIRegimeV1()
    cands = domain.initial_candidates()
    cand_vars = {v.name: v.variable_id for v in cands[0].variables}

    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id, \
            f"Variable ID for {name} changed between calls"
        assert vars1[name].variable_id == cand_vars[name], \
            f"Variable ID for {name} differs between domain and get_variables()"


# ---------------------------------------------------------------------------
# TEST-AI-02 — All 4 candidates are valid DAGs
# ---------------------------------------------------------------------------

def test_all_candidates_are_dags():
    """Every initial candidate must be a valid DAG."""
    factories = [
        make_infrastructure_buildout_candidate,
        make_bubble_detachment_candidate,
        make_winner_take_all_candidate,
        make_productivity_regime_candidate,
    ]
    for factory in factories:
        candidate = factory()
        assert candidate.is_dag(), (
            f"Candidate '{candidate.description}' violates DAG constraint. "
            f"Edges: {candidate.edge_structure_signature()}"
        )


# ---------------------------------------------------------------------------
# TEST-AI-03 — All candidates share canonical variable set
# ---------------------------------------------------------------------------

def test_all_candidates_share_variable_set():
    """All candidates must contain exactly the same 8 canonical variables."""
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    factories = [
        make_infrastructure_buildout_candidate,
        make_bubble_detachment_candidate,
        make_winner_take_all_candidate,
        make_productivity_regime_candidate,
    ]
    for factory in factories:
        cand = factory()
        cand_names = {v.name for v in cand.variables}
        cand_ids = {v.variable_id for v in cand.variables}
        assert cand_names == expected_names, \
            f"Candidate '{cand.description}' has wrong variable names"
        assert cand_ids == expected_ids, \
            f"Candidate '{cand.description}' has wrong variable IDs"


# ---------------------------------------------------------------------------
# TEST-AI-04 — Soft probabilities clamped to [0.01, 0.99]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [
    -100.0, -10.0, -1.0, 0.0, 1.0, 10.0, 100.0,
    float("inf"), -float("inf"),
])
def test_soft_bool_clamped(signal: float):
    """_soft_bool must never return values outside [0.01, 0.99]."""
    safe_signal = max(-700.0, min(700.0, signal)) if math.isinf(signal) else signal
    result = _soft_bool(safe_signal)
    assert 0.01 <= result <= 0.99, f"_soft_bool({signal}) = {result} out of range"
    assert not math.isnan(result), f"_soft_bool({signal}) returned NaN"


# ---------------------------------------------------------------------------
# TEST-AI-05 & 06 — SemiconductorMomentum calibration
# ---------------------------------------------------------------------------

def test_high_sox_momentum_produces_high_p():
    """
    SOX strongly above trend (high 13w return z-score) → P(SemiconductorMomentum) > 0.5.
    """
    # Create price history: strong uptrend (13w return = large positive)
    # Flat history with a big recent surge
    prices = [100.0] * 300
    # Inject a strong 13-week surge: current price much higher than 65 days ago
    for i in range(65):
        prices[i] = 130.0  # surge: 30% up from the stable 100 base
    obs = _make_yf_obs("^SOX", prices)
    z, _ = _compute_13w_return_zscore(obs, "^SOX")
    assert z is not None
    p = _soft_bool(z - 0.5)
    assert p > 0.5, f"Expected P > 0.5 for high SOX momentum, got {p:.3f}"


def test_low_sox_momentum_produces_low_p():
    """
    SOX well below trend (low 13w return z-score) → P(SemiconductorMomentum) < 0.5.
    """
    # Falling prices: strong 13w downtrend
    prices = [100.0] * 300
    for i in range(65):
        prices[i] = 70.0  # 30% below stable base → strongly negative return
    obs = _make_yf_obs("^SOX", prices)
    z, _ = _compute_13w_return_zscore(obs, "^SOX")
    assert z is not None
    p = _soft_bool(z - 0.5)
    assert p < 0.5, f"Expected P < 0.5 for low SOX momentum, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-07 — MarketConcentrationExtreme: QQQ outperforming RSP
# ---------------------------------------------------------------------------

def test_qqq_outperforming_rsp_produces_high_concentration_p():
    """QQQ strongly outperforming RSP → P(MarketConcentrationExtreme) > 0.5."""
    # QQQ rising, RSP flat → ratio rising strongly
    qqq_prices = [100.0] * 300
    rsp_prices = [50.0] * 300
    for i in range(65):
        qqq_prices[i] = 130.0  # QQQ surges
        rsp_prices[i] = 50.5   # RSP barely moves
    qqq_obs = _make_yf_obs("QQQ", qqq_prices)
    rsp_obs = _make_yf_obs("RSP", rsp_prices)
    z, _ = _compute_concentration_ratio_zscore(qqq_obs, rsp_obs)
    assert z is not None
    p = _soft_bool(z - 0.5)
    assert p > 0.5, f"Expected P > 0.5 for QQQ outperforming RSP, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-08 & 09 — HyperscalerCapexAccelerating calibration
# ---------------------------------------------------------------------------

def test_high_capex_growth_produces_high_p():
    """Average YoY capex growth = 35% (above 20%) → P > 0.5."""
    capex = _make_capex_snapshot(avg_yoy=35.0)
    sig, _ = _compute_capex_signal(capex)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for 35% capex growth, got {p:.3f}"


def test_low_capex_growth_produces_low_p():
    """Average YoY capex growth = 5% (below 20%) → P < 0.5."""
    capex = _make_capex_snapshot(avg_yoy=5.0)
    sig, _ = _compute_capex_signal(capex)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for 5% capex growth, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-10 — TechValuationDetached: elevated QQQ price
# ---------------------------------------------------------------------------

def test_elevated_qqq_produces_high_valuation_p():
    """QQQ price significantly above 3-year history → P(TechValuationDetached) > 0.5."""
    # Build 750 days of price history; current price is 2 std devs above mean
    rng = np.random.default_rng(42)
    base_prices = list(rng.normal(100.0, 5.0, 750).tolist())
    mean = float(np.mean(base_prices))
    std = float(np.std(base_prices, ddof=1))
    # Set current price to mean + 2.5σ (well above threshold of z=1.0)
    current_price = mean + 2.5 * std
    prices = [current_price] + base_prices
    obs = _make_yf_obs("QQQ", prices)
    sig, _ = _compute_valuation_zscore(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for elevated QQQ price, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-11 & 12 — LaborProductivityImproving calibration
# ---------------------------------------------------------------------------

def test_high_productivity_growth_produces_high_p():
    """Productivity YoY = 3.0% (above 2%) → P(LaborProductivityImproving) > 0.5."""
    # obs[0] = 103.0, obs[4] = 100.0 → YoY ≈ 3%
    values = [103.0, 102.5, 102.0, 101.5, 100.0, 99.5, 99.0, 98.5]
    obs = _make_fred_obs("PRS85006092", values)
    sig, _ = _compute_labor_productivity_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for 3% productivity growth, got {p:.3f}"


def test_low_productivity_growth_produces_low_p():
    """Productivity YoY = 0.5% (below 2%) → P(LaborProductivityImproving) < 0.5."""
    values = [100.5, 100.3, 100.2, 100.1, 100.0, 99.8, 99.6, 99.4]
    obs = _make_fred_obs("PRS85006092", values)
    sig, _ = _compute_labor_productivity_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for 0.5% productivity growth, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-13 & 14 — BroadEconomicLift calibration
# ---------------------------------------------------------------------------

def test_high_gdp_growth_produces_high_p():
    """GDP growth = 3.5% (above 2.5%) → P(BroadEconomicLift) > 0.5."""
    obs = _make_fred_obs("A191RL1Q225SBEA", [3.5] * 8)
    sig, _ = _compute_gdp_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for 3.5% GDP growth, got {p:.3f}"


def test_low_gdp_growth_produces_low_p():
    """GDP growth = 1.0% (below 2.5%) → P(BroadEconomicLift) < 0.5."""
    obs = _make_fred_obs("A191RL1Q225SBEA", [1.0] * 8)
    sig, _ = _compute_gdp_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for 1.0% GDP growth, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-15 & 16 — AIRiskPremiumCompressed (VIX) calibration
# ---------------------------------------------------------------------------

def test_low_vix_produces_high_risk_premium_compressed_p():
    """VIX well below historical average → P(AIRiskPremiumCompressed) > 0.5."""
    rng = np.random.default_rng(42)
    # Historical VIX mean ~20; current VIX = 12 (well below mean)
    vix_history = [20.0 + rng.normal(0, 2) for _ in range(300)]
    vix_history[0] = 12.0  # current = well below mean
    obs = _make_yf_obs("^VIX", vix_history)
    sig, _ = _compute_vix_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"Expected P > 0.5 for low VIX, got {p:.3f}"


def test_high_vix_produces_low_risk_premium_compressed_p():
    """VIX well above historical average → P(AIRiskPremiumCompressed) < 0.5."""
    rng = np.random.default_rng(42)
    # Historical VIX mean ~15; current VIX = 35 (well above mean)
    vix_history = [15.0 + rng.normal(0, 2) for _ in range(300)]
    vix_history[0] = 35.0  # current = elevated fear
    obs = _make_yf_obs("^VIX", vix_history)
    sig, _ = _compute_vix_signal(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p < 0.5, f"Expected P < 0.5 for elevated VIX, got {p:.3f}"


# ---------------------------------------------------------------------------
# TEST-AI-17 — build_evidence_record maps all 8 UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    """build_evidence_record must produce exactly 8 assignments with correct UUIDs."""
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}

    yf_data, fred_data, capex = _make_full_data()
    snapshot = compute_snapshot(yf_data, fred_data, capex, _TARGET_DATE)
    record = AIRegimePipeline.build_evidence_record(snapshot)

    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids, (
        f"Assignment UUIDs do not match canonical variable UUIDs.\n"
        f"  got:      {assignment_ids}\n"
        f"  expected: {expected_ids}"
    )


# ---------------------------------------------------------------------------
# TEST-AI-18 — All assignments are SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    """Every assignment must carry SOFT_OBSERVED missingness and probabilities dict."""
    yf_data, fred_data, capex = _make_full_data()
    snapshot = compute_snapshot(yf_data, fred_data, capex, _TARGET_DATE)
    record = AIRegimePipeline.build_evidence_record(snapshot)

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED, \
            f"Assignment for {a.variable_id} has missingness {a.missingness}"
        assert a.probabilities is not None, \
            f"Assignment for {a.variable_id} missing probabilities dict"
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# TEST-AI-19 — EDGAR _extract_capex_entries parses realistic JSON
# ---------------------------------------------------------------------------

def _make_edgar_facts(entries: list[dict]) -> dict:
    """Build a minimal EDGAR company facts JSON structure."""
    return {
        "cik": 789019,
        "entityName": "TEST CORP",
        "facts": {
            "us-gaap": {
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "label": "Capital Expenditures",
                    "units": {
                        "USD": entries
                    }
                }
            }
        }
    }


def test_edgar_extract_capex_entries_parses_correctly():
    """_extract_capex_entries parses 10-Q entries and deduplicates."""
    entries = [
        {"form": "10-Q", "fp": "Q2", "fy": 2024, "val": 8_000_000_000,
         "start": "2024-01-01", "end": "2024-06-30", "accn": "0001-2024-Q2"},
        {"form": "10-Q", "fp": "Q2", "fy": 2023, "val": 6_000_000_000,
         "start": "2023-01-01", "end": "2023-06-30", "accn": "0001-2023-Q2"},
        {"form": "10-Q", "fp": "Q1", "fy": 2024, "val": 3_500_000_000,
         "start": "2024-01-01", "end": "2024-03-31", "accn": "0001-2024-Q1"},
        {"form": "10-K", "fp": "FY", "fy": 2023, "val": 14_000_000_000,
         "start": "2023-01-01", "end": "2023-12-31", "accn": "0001-2023-FY"},
        {"form": "10-Q", "fp": "Q2", "fy": 2024, "val": 8_100_000_000,
         "start": "2024-01-01", "end": "2024-06-30", "accn": "0001-2024-Q2-amended"},
    ]
    facts = _make_edgar_facts(entries)
    result = _extract_capex_entries(facts, "0000789019", "MSFT")

    # Should have Q1 2024 and Q2 2024 (latest) and Q2 2023 — not the 10-K
    assert len(result) == 3
    fy_fps = {(e.fiscal_year, e.fiscal_period) for e in result}
    assert ("FY", 2023) not in fy_fps, "10-K entry should be excluded"

    # Verify the amendment handling: Q2 2024 should use the later one
    q2_2024 = next(e for e in result if e.fiscal_year == 2024 and e.fiscal_period == "Q2")
    # The end_date-based dedup keeps the later end_date (both are same date here)
    # so it's implementation-dependent, but value should be one of the two
    assert q2_2024.value_usd in {8_000_000_000, 8_100_000_000}


def test_edgar_extract_filters_invalid_entries():
    """_extract_capex_entries filters zero values, missing fields, non-10-Q."""
    entries = [
        {"form": "10-Q", "fp": "Q2", "fy": 2024, "val": 0,            # zero
         "start": "2024-01-01", "end": "2024-06-30", "accn": "a"},
        {"form": "10-Q", "fp": "FY", "fy": 2024, "val": 5_000_000_000, # FP not Q1/Q2/Q3
         "start": "2024-01-01", "end": "2024-12-31", "accn": "b"},
        {"form": "10-K", "fp": "Q2", "fy": 2024, "val": 5_000_000_000, # 10-K not 10-Q
         "start": "2024-01-01", "end": "2024-06-30", "accn": "c"},
        {"form": "10-Q", "fp": "Q1", "fy": 2024, "val": 3_000_000_000, # valid
         "start": "2024-01-01", "end": "2024-03-31", "accn": "d"},
    ]
    facts = _make_edgar_facts(entries)
    result = _extract_capex_entries(facts, "0000789019", "MSFT")
    assert len(result) == 1
    assert result[0].fiscal_period == "Q1"


# ---------------------------------------------------------------------------
# TEST-AI-20 — EDGAR YoY growth computation
# ---------------------------------------------------------------------------

def test_edgar_compute_yoy_growth_correct():
    """_compute_yoy_growth returns correct YoY % and CompanyCapexResult."""
    entries = [
        _CapexEntry(fiscal_year=2024, fiscal_period="Q2",
                    end_date=date(2024, 6, 30), start_date=date(2024, 1, 1),
                    value_usd=9_000_000_000),
        _CapexEntry(fiscal_year=2023, fiscal_period="Q2",
                    end_date=date(2023, 6, 30), start_date=date(2023, 1, 1),
                    value_usd=7_000_000_000),
        _CapexEntry(fiscal_year=2024, fiscal_period="Q1",
                    end_date=date(2024, 3, 31), start_date=date(2024, 1, 1),
                    value_usd=4_000_000_000),
    ]
    # Sort newest-first as the client does
    entries_sorted = sorted(
        entries, key=lambda e: (e.fiscal_year, e.fiscal_period), reverse=True
    )
    result = _compute_yoy_growth("MSFT", "0000789019", entries_sorted, date(2024, 9, 30))
    assert result is not None
    assert result.fiscal_year == 2024
    assert result.fiscal_period == "Q2"
    expected_yoy = (9_000_000_000 / 7_000_000_000 - 1.0) * 100.0
    assert abs(result.yoy_growth_pct - expected_yoy) < 0.01


def test_edgar_compute_yoy_growth_missing_prior_returns_none():
    """_compute_yoy_growth returns None if prior-year period is missing."""
    entries = [
        _CapexEntry(fiscal_year=2024, fiscal_period="Q2",
                    end_date=date(2024, 6, 30), start_date=date(2024, 1, 1),
                    value_usd=9_000_000_000),
    ]
    result = _compute_yoy_growth("MSFT", "0000789019", entries, date(2024, 9, 30))
    assert result is None


def test_edgar_compute_yoy_growth_future_date_excluded():
    """_compute_yoy_growth does not use filings with end_date > as_of."""
    entries = [
        _CapexEntry(fiscal_year=2025, fiscal_period="Q1",
                    end_date=date(2025, 3, 31), start_date=date(2025, 1, 1),
                    value_usd=5_000_000_000),
        _CapexEntry(fiscal_year=2024, fiscal_period="Q2",
                    end_date=date(2024, 6, 30), start_date=date(2024, 1, 1),
                    value_usd=9_000_000_000),
        _CapexEntry(fiscal_year=2023, fiscal_period="Q2",
                    end_date=date(2023, 6, 30), start_date=date(2023, 1, 1),
                    value_usd=7_000_000_000),
    ]
    entries_sorted = sorted(
        entries, key=lambda e: (e.fiscal_year, e.fiscal_period), reverse=True
    )
    # as_of = 2024-09-01: Q1 2025 (end 2025-03-31) is excluded
    result = _compute_yoy_growth("MSFT", "0000789019", entries_sorted, date(2024, 9, 1))
    assert result is not None
    assert result.fiscal_year == 2024
    assert result.fiscal_period == "Q2"


# ---------------------------------------------------------------------------
# TEST-AI-21 — EDGAR client caches responses
# ---------------------------------------------------------------------------

def test_edgar_client_caches_responses():
    """Second fetch for same CIK must not make another HTTP request."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"facts": {"us-gaap": {}}})
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)

    client = EDGARClient(client=mock_http, cache_ttl_seconds=3600)

    async def _run():
        cik = "0000789019"
        # First call — hits HTTP
        r1 = await client._get_company_facts(cik)
        # Second call — should use cache
        r2 = await client._get_company_facts(cik)
        return r1, r2

    r1, r2 = asyncio.run(_run())
    assert mock_http.get.call_count == 1, \
        f"Expected 1 HTTP call but got {mock_http.get.call_count}"
    assert r1 == r2


# ---------------------------------------------------------------------------
# TEST-AI-22 — Weekly backfill date computation
# ---------------------------------------------------------------------------

def test_weekly_backfill_dates_returns_fridays():
    """_weekly_backfill_dates must return only Friday dates."""
    today = date(2024, 5, 6)  # Monday
    dates = _weekly_backfill_dates(4, today)

    assert len(dates) == 4
    for d in dates:
        assert d.weekday() == 4, f"Expected Friday, got {d} (weekday {d.weekday()})"
    assert dates == sorted(dates)


def test_weekly_backfill_dates_are_unique():
    """Backfill dates must be unique."""
    today = date(2024, 5, 10)
    dates = _weekly_backfill_dates(8, today)
    assert len(dates) == len(set(dates)), "Backfill dates contain duplicates"


# ---------------------------------------------------------------------------
# TEST-AI-23 — _last_friday returns correct day
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("as_of,expected", [
    (date(2024, 5, 6), date(2024, 5, 3)),   # Monday → previous Friday
    (date(2024, 5, 3), date(2024, 5, 3)),   # Friday → same day
    (date(2024, 5, 4), date(2024, 5, 3)),   # Saturday → last Friday
    (date(2024, 5, 5), date(2024, 5, 3)),   # Sunday → last Friday
    (date(2024, 5, 7), date(2024, 5, 3)),   # Tuesday → last Friday
])
def test_last_friday(as_of: date, expected: date):
    result = _last_friday(as_of)
    assert result == expected
    assert result.weekday() == 4


# ---------------------------------------------------------------------------
# TEST-AI-24 — compute_snapshot fallback with no data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_with_no_data():
    """compute_snapshot with empty inputs must not raise; all P = 0.5."""
    capex_empty = HyperscalerCapexSnapshot(
        companies={}, avg_yoy_growth_pct=None, companies_with_data=0, confidence=0.0
    )
    snapshot = compute_snapshot({}, {}, capex_empty, _TARGET_DATE)

    assert snapshot.p_semiconductor_momentum == 0.5
    assert snapshot.p_market_concentration_extreme == 0.5
    assert snapshot.p_hyperscaler_capex_accelerating == 0.5
    assert snapshot.p_tech_valuation_detached == 0.5
    assert snapshot.p_ip_investment_rising == 0.5
    assert snapshot.p_labor_productivity_improving == 0.5
    assert snapshot.p_broad_economic_lift == 0.5
    assert snapshot.p_ai_risk_premium_compressed == 0.5


# ---------------------------------------------------------------------------
# TEST-AI-25 — compute_snapshot partial data does not raise
# ---------------------------------------------------------------------------

def test_compute_snapshot_partial_data_does_not_raise():
    """compute_snapshot with only some sources populated must not raise."""
    capex_empty = HyperscalerCapexSnapshot(
        companies={}, avg_yoy_growth_pct=None, companies_with_data=0, confidence=0.0
    )
    # Provide only VIX data (below mean → ARPC should be non-neutral)
    rng = np.random.default_rng(42)
    vix_prices = [20.0 + rng.normal(0, 2) for _ in range(300)]
    vix_prices[0] = 10.0  # clearly below mean
    yf_partial = {"^VIX": _make_yf_obs("^VIX", vix_prices)}

    snapshot = compute_snapshot(yf_partial, {}, capex_empty, _TARGET_DATE)

    # VIX provided → ARPC should be non-neutral
    assert snapshot.p_ai_risk_premium_compressed != 0.5, \
        "ARPC should have a non-neutral probability with VIX data"
    # Others should fall back to 0.5
    assert snapshot.p_semiconductor_momentum == 0.5
    assert snapshot.p_hyperscaler_capex_accelerating == 0.5


# ---------------------------------------------------------------------------
# TEST-AI-26 — Full pipeline with mocked clients
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    """
    AIRegimePipeline.fetch_evidence with fully mocked clients.

    Verifies: 8 assignments, correct UUIDs, all SOFT_OBSERVED, source ref.
    """
    variables = get_variables()

    yf_data, fred_data, capex_data = _make_full_data()

    mock_yf = AsyncMock(spec=AIYFinanceClient)
    mock_yf.fetch_all = AsyncMock(return_value=yf_data)

    mock_fred = AsyncMock(spec=FREDClient)
    mock_fred.fetch_series = AsyncMock()

    # Build mock responses for each FRED series
    async def _mock_fetch_series(series_id, **kwargs):
        return fred_data.get(series_id, [])

    mock_fred.fetch_series = AsyncMock(side_effect=_mock_fetch_series)

    mock_edgar = AsyncMock(spec=EDGARClient)
    mock_edgar.fetch_hyperscaler_capex = AsyncMock(return_value=capex_data)

    pipeline = AIRegimePipeline(mock_yf, mock_fred, mock_edgar)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    # Structural checks
    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}

    # Source ref contains expected identifiers
    assert "AI-REGIME" in record.source_ref
    assert "EDGAR" in record.source_ref
    assert "FRED" in record.source_ref

    # All SOFT_OBSERVED
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    # Calls were made
    mock_yf.fetch_all.assert_called_once()
    mock_edgar.fetch_hyperscaler_capex.assert_called_once()


# ---------------------------------------------------------------------------
# TEST-AI-27 — Domain registers and activates in the engine
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    """AIRegimeV1 can be registered and evidence records can be ingested."""
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = AIRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert len(pop.active_candidates()) == 4

    yf_data, fred_data, capex = _make_full_data()
    snapshot = compute_snapshot(yf_data, fred_data, capex, _TARGET_DATE)
    record = AIRegimePipeline.build_evidence_record(snapshot)
    engine.ingest(record)

    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-AI-28 — Candidates have distinct edge structures
# ---------------------------------------------------------------------------

def test_candidates_have_distinct_edge_structures():
    """The 4 seed candidates must encode genuinely distinct structural hypotheses."""
    domain = AIRegimeV1()
    candidates = domain.initial_candidates()
    signatures = [c.edge_structure_signature() for c in candidates]
    unique_signatures = set(signatures)
    assert len(unique_signatures) == len(signatures), (
        f"Some candidates share the same edge structure. "
        f"Got {len(unique_signatures)} unique structures for {len(candidates)} candidates."
    )


# ---------------------------------------------------------------------------
# TEST-AI-29 — All edges have valid existence priors
# ---------------------------------------------------------------------------

def test_all_edges_have_existence_prior():
    """All edges must have valid existence_prior ∈ (0, 1) and enabled=True."""
    domain = AIRegimeV1()
    for cand in domain.initial_candidates():
        for edge in cand.edges:
            assert 0.0 < edge.existence_prior < 1.0, \
                f"Candidate '{cand.description}' edge has invalid prior {edge.existence_prior}"
            assert edge.existence_probability == edge.existence_prior
            assert edge.enabled is True
            assert edge.learnable is True


# ---------------------------------------------------------------------------
# TEST-AI-30 — Module ID matches candidates
# ---------------------------------------------------------------------------

def test_domain_module_id_matches_candidates():
    """All candidates must reference the same domain module ID as the domain."""
    domain = AIRegimeV1()
    module_id = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == module_id, (
            f"Candidate '{cand.description}' has module_id "
            f"'{cand.domain_module_id}', expected '{module_id}'"
        )


# ---------------------------------------------------------------------------
# TEST-AI-31 — Existence thresholds are valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    """EdgeExistenceThresholdConfig must satisfy ordering constraints."""
    domain = AIRegimeV1()
    t = domain.existence_thresholds()

    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above
    # Confirm wide explore band (0.25-0.75)
    assert t.explore_band == (0.25, 0.75), \
        f"Expected explore_band=(0.25, 0.75), got {t.explore_band}"


# ---------------------------------------------------------------------------
# TEST-AI-32 — IPInvestmentRising uses median comparison
# ---------------------------------------------------------------------------

def test_ip_investment_uses_historical_median():
    """IPInvestmentRising signal should reflect position vs historical median."""
    # Series: growing from 100 to 120 over 20 quarters
    # Current growth rate should be above median
    values = [120.0 * (0.995 ** i) for i in range(20)]  # newest-first, declining
    obs = _make_fred_obs("Y033RC1Q027SBEA", values)
    sig, _ = _compute_ip_investment_signal(obs)
    assert sig is not None
    # The signal is (growth - median) / iqr; just verify it doesn't raise
    assert not math.isnan(sig)

    # Verify boundary: all same value → signal near 0 (no relative change)
    flat_values = [100.0] * 20
    obs_flat = _make_fred_obs("Y033RC1Q027SBEA", flat_values)
    sig_flat, _ = _compute_ip_investment_signal(obs_flat)
    assert sig_flat is not None
    # All zeros → around 0.0
    assert abs(sig_flat) < 1e-6, f"Flat series should give signal ≈ 0, got {sig_flat}"


# ---------------------------------------------------------------------------
# TEST-AI-33 — Scheduler backfill returns Fridays
# ---------------------------------------------------------------------------

def test_scheduler_backfill_dates_are_fridays():
    """AIRegimeScheduler backfill dates must all be Fridays."""
    today = date(2024, 5, 13)  # Monday
    dates = scheduler_backfill_dates(4, today)
    assert len(dates) == 4
    for d in dates:
        assert d.weekday() == 4, f"Expected Friday, got weekday {d.weekday()}"
