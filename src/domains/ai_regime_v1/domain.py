"""
ai-regime-v1 — AI investment cycle interpretive ontology domain.

Purpose
-------
Track which causal story best explains the current AI investment cycle.
This is an interpretive analysis domain, not a prediction engine.
The engine forms its own hypotheses about how these signals connect.

Variables (all BOOLEAN)
-----------------------
SemiconductorMomentum
    True  = SOX index 13-week return z-score > 0.5 (sustained chip demand)
    False = SOX momentum at or below trend
    Signal: semiconductor sector as the physical infrastructure signal

MarketConcentrationExtreme
    True  = QQQ/RSP (equal-weight S&P) ratio 13-week z-score > 0.5
            (tech outperforming broad market on a concentration basis)
    False = market breadth normal; gains are distributed
    Signal: capital concentration in AI/tech names

HyperscalerCapexAccelerating
    True  = Average YoY capex growth for MSFT/GOOGL/AMZN/META > 20%
    False = capex growth below 20% threshold
    Signal: actual dollars being deployed in AI infrastructure; observable
            from SEC EDGAR 10-Q filings

TechValuationDetached
    True  = QQQ price z-score vs 3-year history > 1.0
            (proxy for elevated P/E vs recent history)
    False = tech valuations within 1σ of recent 3-year range
    Signal: narrative premium; markets pricing in future AI gains that
            have not yet materialised in earnings

IPInvestmentRising
    True  = FRED Y033RC1Q027SBEA 4-quarter growth rate > historical median
    False = IP investment growth below historical median
    Signal: business investment in intellectual property (software, R&D,
            database assets); the productive deployment channel

LaborProductivityImproving
    True  = FRED PRS85006092 (nonfarm business labor productivity) YoY > 2.0%
    False = productivity growth at or below threshold
    Signal: whether AI is actually showing up in measured economic productivity

BroadEconomicLift
    True  = FRED A191RL1Q225SBEA (real GDP growth, annualized) > 2.5%
    False = GDP growth at or below threshold
    Signal: whether the AI cycle is lifting the broad economy

AIRiskPremiumCompressed
    True  = VIX level z-score (inverted) signals VIX below historical average
    False = VIX elevated; risk premium not compressed
    Signal: market-implied risk appetite; compressed risk premium is a
            necessary (not sufficient) condition for sustained AI narrative

Data sources
------------
yfinance:
    ^SOX      — SemiconductorMomentum (SOX 13-week return z-score)
    QQQ, RSP  — MarketConcentrationExtreme (QQQ/RSP ratio z-score)
    QQQ       — TechValuationDetached (QQQ price z-score vs 3-year history)
    ^VIX      — AIRiskPremiumCompressed (VIX z-score, inverted)

SEC EDGAR (no key required):
    MSFT (CIK 0000789019)  — HyperscalerCapexAccelerating
    GOOGL (CIK 0001652044) — HyperscalerCapexAccelerating
    AMZN (CIK 0001018724)  — HyperscalerCapexAccelerating
    META (CIK 0001326801)  — HyperscalerCapexAccelerating
    Concept: us-gaap/PaymentsToAcquirePropertyPlantAndEquipment

FRED:
    Y033RC1Q027SBEA  (quarterly) — IPInvestmentRising
    PRS85006092      (quarterly) — LaborProductivityImproving
    A191RL1Q225SBEA  (quarterly) — BroadEconomicLift

Cadence: WEEKLY (every Monday at 09:00 UTC using prior week's data)
-------------------------------------------------------------------
Reasoning:
    - yfinance prices update daily; weekly aggregation reduces noise
    - FRED quarterly series update only quarterly but weekly runs capture
      revisions promptly
    - EDGAR 10-Q filings publish quarterly; EDGAR data is cached 6h
    - AI regime transitions operate on months-to-quarters timescales;
      weekly cadence provides ~52 evidence points/year—sufficient for
      the learning cycle to detect genuine structural shifts
    - Consistent with macro_regime_v1 cadence for cross-domain comparison
"""
from __future__ import annotations

from ..sources.structure import boolean_variables, with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)

# ---------------------------------------------------------------------------
# Module identity
# ---------------------------------------------------------------------------

_MODULE_ID = "ai-regime-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions — stable UUIDs via deterministic hashing.
# These IDs must never change; they identify variables across ingestion runs.
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "SemiconductorMomentum",
    "MarketConcentrationExtreme",
    "HyperscalerCapexAccelerating",
    "TechValuationDetached",
    "IPInvestmentRising",
    "LaborProductivityImproving",
    "BroadEconomicLift",
    "AIRiskPremiumCompressed",
]

_VARIABLE_DEFS: dict[str, Variable] = boolean_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for ai-regime-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class AIRegimeV1:
    """
    Domain module for the AI investment cycle interpretive ontology.

    Implements the domain module contract (engine/model/domain.py).

    Explore band: 0.25–0.75 (same as macro_regime_v1).
    Rationale: interpretive macro-financial domains require the engine to
    maintain genuine uncertainty longer before committing; this produces
    richer ontology competition and avoids premature convergence on a
    single narrative before sufficient evidence accumulates.
    """

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def variables(self) -> list[Variable]:
        return list(with_lags(self._MODULE_ID, _VARIABLE_DEFS).values())

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        """
        Wider explore band than agriculture domains.

        AI regime transitions are structural and slow; we want the engine
        to maintain genuine uncertainty over edge existence for longer
        before committing.  Same rationale as macro_regime_v1.
        """
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),
        )
