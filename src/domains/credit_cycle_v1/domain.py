"""
credit-cycle-v1 — Corporate credit cycle domain module.

Purpose
-------
Tracks the evolution of competing causal narratives in the corporate credit
cycle: monetary tightening transmission, default cycle inception, liquidity
withdrawal, and credit normalization.  Variables span HY/IG spreads,
bank lending standards, credit impulse, and refinancing stress.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:
HYSpreadElevated
    high  = BAMLH0A0HYM2 z-score >= +1.0 (HY spreads above historical trend)
    low   = spreads within normal range

LeveragedLoanStress
    high  = DRTSCILM z-score >= +1.0 (bank credit tightening / delinquency elevated)
    low   = lending conditions normal

CorporateDefaultRisk
    high  = BAMLH0A0HYM2 level > 5.5% (absolute stress threshold)
    low   = HY OAS below systemic stress level

CreditImpulseNegative
    high  = TOTCI 3-month growth rate is negative (credit contracting)
    low   = credit expanding or stable

BankLendingTightening
    high  = DRTSCILM z-score >= +0.5 (tightening above neutral)
    low   = lending standards normal

InvestmentGradeSpread
    high  = BAMLC0A0CM z-score >= +1.0 (IG spreads elevated)
    low   = IG spreads within historical range

HighYieldIssuanceFalling
    high  = BAMLH0A0HYM2 3-month momentum is positive (spreads widening = issuance deterred)
    low   = spreads tightening or stable (issuance conditions improving)

RefinancingStress
    high  = DGS5 + BAMLH0A0HYM2 composite elevated (refinancing cost above threshold)
    low   = refinancing environment manageable

FRED series used
----------------
BAMLH0A0HYM2  (daily)   — HYSpreadElevated, CorporateDefaultRisk, HighYieldIssuanceFalling
DRTSCILM      (quarterly)— LeveragedLoanStress, BankLendingTightening
TOTCI         (weekly)   — CreditImpulseNegative
BAMLC0A0CM    (daily)    — InvestmentGradeSpread
DGS5          (daily)    — RefinancingStress (composite with BAMLH0A0HYM2)

Cadence: WEEKLY (every Monday at 09:00 UTC)
"""
from __future__ import annotations

from ..sources.grades import graded_variables
from ..sources.structure import with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)

_MODULE_ID = "credit-cycle-v1"

_VAR_NAMES = [
    "HYSpreadElevated",
    "LeveragedLoanStress",
    "CorporateDefaultRisk",
    "CreditImpulseNegative",
    "BankLendingTightening",
    "InvestmentGradeSpread",
    "HighYieldIssuanceFalling",
    "RefinancingStress",
]

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    return _VARIABLE_DEFS


class CreditCycleV1:
    """Domain module for the credit cycle ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def variables(self) -> list[Variable]:
        return list(with_lags(self._MODULE_ID, _VARIABLE_DEFS).values())

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),
        )
