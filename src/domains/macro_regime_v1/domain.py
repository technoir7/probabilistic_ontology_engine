"""
macro-regime-v1 — Macroeconomic regime domain module.

Purpose
-------
Stress-tests ontology evolution under regime shifts, competing macroeconomic
narratives, noisy heterogeneous evidence, and changing causal relationships.
This domain is NOT a price-prediction engine; it is an evolving probabilistic
ontology over macro-financial regimes.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:
YieldCurveInverted
    high  = 10Y minus 2Y Treasury yield spread (T10Y2Y) is negative (inverted)
    low   = spread is positive (normal curve)
    Signal: structural monetary tightening / growth pessimism embedded in rates

InflationShock
    high  = CPI 12-month YoY rate exceeds 3.5% (materially above 2% target)
    low   = inflation at or near target
    Signal: supply-side or demand-side inflation pressure creating policy risk

LiquidityStress
    high  = Fed balance sheet (WALCL) contracting over 13 weeks (QT regime)
    low   = balance sheet stable or expanding (QE / neutral)
    Signal: active Fed liquidity withdrawal, distinct from rate policy

CreditSpreadStress
    high  = HY OAS spread (BAMLH0A0HYM2) is above its rolling 52-week z-score ≥ 1
    low   = HY spreads at or below historical mean
    Signal: credit market pricing elevated default risk / deleveraging pressure

VolatilityShock
    high  = VIX above its rolling 90-day 75th percentile (fear regime)
    low   = VIX in normal range
    Signal: equity-implied volatility elevated; systemic risk-off sentiment

DollarStrength
    high  = DEXUSEU (dollars per euro) below its 52-week mean: the dollar
            stronger than its recent trend
    low   = dollar at or weaker than its recent trend
    Signal: global capital flows favouring dollar; often accompanies risk-off

EquityRiskOn
    high  = UNRATE not rising vs its 12-month mean (labour market resilient)
    low   = unemployment trending higher (labour market deteriorating)
    Signal: real-economy demand channel; distinct from volatility and credit

AIRiskOn
    high  = NASDAQ Composite 13-week price return is above its historical mean
            by at least +0.5 standard deviations (tech/growth narrative dominant)
    low   = NASDAQ 13-week return is below-average or negative
    Signal: technology / AI narrative driving risk appetite; acts as distinct
            explanatory factor from broad credit/vol signals

FRED series used
----------------
T10Y2Y        (daily)   — YieldCurveInverted
CPIAUCSL      (monthly) — InflationShock
WALCL         (weekly)  — LiquidityStress
BAMLH0A0HYM2  (daily)   — CreditSpreadStress
VIXCLS        (daily)   — VolatilityShock
DEXUSEU       (daily)   — DollarStrength
UNRATE        (monthly) — EquityRiskOn
NASDAQCOM     (daily)   — AIRiskOn

Cadence: WEEKLY (every Monday at 09:00 UTC using prior week's data)
-------------------------------------------------------------------
Reasoning:
- WALCL publishes weekly (Thursday) — binding constraint
- CPIAUCSL and UNRATE are monthly but update slowly; weekly ingestion still
  reflects their latest readings
- Daily signals (T10Y2Y, VIX, credit spreads, FX) are aggregated to weekly
  medians — reducing noise and preventing high-frequency oversampling
- Macro regime changes operate on weeks-to-months timescales; daily cadence
  would inject noise without increasing informational value
- Weekly cadence produces ~52 evidence records/year — sufficient for the
  ontology learning cycle to detect genuine regime shifts
"""
from __future__ import annotations

from ..sources.grades import graded_variables
from ..sources.structure import with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)

# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------

_MODULE_ID = "macro-regime-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions — stable UUIDs via deterministic hashing.
# These IDs must never change; they identify variables across ingestion runs.
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "YieldCurveInverted",
    "InflationShock",
    "LiquidityStress",
    "CreditSpreadStress",
    "VolatilityShock",
    "DollarStrength",
    "EquityRiskOn",
    "AIRiskOn",
]

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(_MODULE_ID, _VAR_NAMES)
# Each signal and its value last week (REFACTOR_SPEC D19); candidates hold both.
_WITH_LAGS: dict[str, Variable] = with_lags(_MODULE_ID, _VARIABLE_DEFS)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for macro-regime-v1."""
    return _VARIABLE_DEFS


def get_variables_with_lags() -> dict[str, Variable]:
    """Every signal and its value last week, as the candidates hold them."""
    return _WITH_LAGS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class MacroRegimeV1:
    """
    Domain module for the macro regime ontology.

    Implements the domain module contract (engine/model/domain.py).
    """
    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def variables(self) -> list[Variable]:
        return list(_WITH_LAGS.values())

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        """
        Wider explore band than agriculture domains.

        Macro regime transitions are slow and noisy; we want the engine to
        maintain genuine uncertainty over edge existence for longer before
        committing. This produces richer ontology competition.
        """
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),  # wider band → more exploration
        )
