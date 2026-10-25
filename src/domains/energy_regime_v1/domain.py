"""
energy-regime-v1 — Energy market regime domain module.

Purpose
-------
Tracks evolving causal narratives in global energy markets: supply shocks,
demand-driven price surges, geopolitical risk premiums, and the structural
transition toward renewables.  All variables are regime indicators, read
as levels, derived from futures prices, ETF momentum, and macro data.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:
OilPriceSurge
    high  = CL=F (WTI crude) 13-week return z-score >= +1.0
    low   = crude prices stable or falling
    Signal: sustained oil price rally vs recent history

NatGasPriceSurge
    high  = NG=F 13-week return z-score >= +1.0
    low   = gas prices stable or falling
    Signal: sustained natural gas price rally

EnergyEquityMomentum
    high  = XLE 13-week return z-score >= +0.5 (energy sector outperforming)
    low   = energy equities lagging
    Signal: market expects sustained energy profitability

OPECSupplyConstraint
    high  = DCOILWTICO (WTI FRED) 13-week momentum is positive and above historical mean
    low   = oil prices not trending up (supply not constrained)
    Signal: supply-side constraint driving price momentum

RenewablesDisplacement
    high  = ICLN/XLE price ratio above its 52-week z-score (+1.0)
    low   = traditional energy outperforming renewables
    Signal: clean energy momentum relative to fossil fuel sector

EnergyInflationPersistent
    high  = CPIENGSL (energy CPI) 12-month YoY > 5%
    low   = energy price inflation contained
    Signal: energy prices driving CPI volatility

GeopoliticalRiskElevated
    high  = DCOILWTICO 90-day return volatility above historical 75th percentile
    low   = oil price volatility within normal range
    Signal: geopolitical uncertainty driving oil price swings

DemandDestructionRisk
    high  = INDPRO 3-month change is negative AND UNRATE is rising
    low   = industrial production stable or unemployment not rising
    Signal: economic slowdown reducing energy demand

Data sources
------------
yfinance: CL=F, NG=F, XLE, ICLN (daily close prices)
FRED:     DCOILWTICO (daily), CPIENGSL (monthly), INDPRO (monthly), UNRATE (monthly)

Cadence: WEEKLY (every Monday at 09:00 UTC)
"""
from __future__ import annotations

from ..sources.grades import graded_variables
from ..sources.structure import with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)

_MODULE_ID = "energy-regime-v1"

_VAR_NAMES = [
    "OilPriceSurge",
    "NatGasPriceSurge",
    "EnergyEquityMomentum",
    "OPECSupplyConstraint",
    "RenewablesDisplacement",
    "EnergyInflationPersistent",
    "GeopoliticalRiskElevated",
    "DemandDestructionRisk",
]

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    return _VARIABLE_DEFS


class EnergyRegimeV1:
    """Domain module for the energy regime ontology."""

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
