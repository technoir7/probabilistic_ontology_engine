"""
labor-market-v1 — Labor market regime domain module.

Purpose
-------
Tracks evolving causal narratives in the U.S. labor market: labor market
tightening cycles, layoff cycle inception, structural labor force shifts, and
wage-price spiral dynamics.  Variables bridge labor market conditions with
inflation and productivity outcomes.

Variables (all BOOLEAN)
-----------------------
UnemploymentRising
    True  = UNRATE z-score vs 12-month mean is positive (unemployment rising)
    False = unemployment stable or falling

WageInflationPersistent
    True  = CES0500000003 YoY growth rate above historical mean
    False = wage growth at or below trend
    Signal: labor market pricing power flowing to workers

JobOpeningsFalling
    True  = JTSJOL z-score is negative (job openings declining vs history)
    False = job openings at or above historical level
    Signal: falling openings = demand for labor weakening (inverted z-score)

LayoffCycleBeginning
    True  = ICSA (initial claims) z-score >= +1.0 (claims rising)
    False = initial claims within normal range
    Signal: rising layoffs = early recessionary labor signal

LaborProductivityWeak
    True  = PRS85006092 (nonfarm business real output/hour) YoY < historical mean
    False = productivity growing at or above trend
    Signal: weak productivity = wage growth not matched by output

ParticipationRateFalling
    True  = CIVPART z-score is negative (participation declining)
    False = participation stable or rising
    Signal: structural exit from labor force (inverted z-score)

RealWageGrowthPositive
    True  = CES0500000003 YoY minus CPIAUCSL YoY is positive
    False = real wages flat or falling
    Signal: workers gaining purchasing power in real terms

TightLaborMarket
    True  = UNRATE inverted z-score + JTSJOL z-score composite is positive
    False = labor market conditions loosening
    Signal: dual confirmation of labor market tightness

FRED series used
----------------
UNRATE          (monthly)   — UnemploymentRising, TightLaborMarket
CES0500000003   (monthly)   — WageInflationPersistent, RealWageGrowthPositive
JTSJOL          (monthly)   — JobOpeningsFalling, TightLaborMarket
ICSA            (weekly)    — LayoffCycleBeginning
PRS85006092     (quarterly) — LaborProductivityWeak
CIVPART         (monthly)   — ParticipationRateFalling
CPIAUCSL        (monthly)   — RealWageGrowthPositive (for real wage computation)

Cadence: WEEKLY (every Monday at 09:00 UTC; monthly/quarterly series
         read at latest published value per week)
"""
from __future__ import annotations

from ..sources.structure import boolean_variables, with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)

_MODULE_ID = "labor-market-v1"

_VAR_NAMES = [
    "UnemploymentRising",
    "WageInflationPersistent",
    "JobOpeningsFalling",
    "LayoffCycleBeginning",
    "LaborProductivityWeak",
    "ParticipationRateFalling",
    "RealWageGrowthPositive",
    "TightLaborMarket",
]

_VARIABLE_DEFS: dict[str, Variable] = boolean_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    return _VARIABLE_DEFS


class LaborMarketV1:
    """Domain module for the labor market regime ontology."""

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
