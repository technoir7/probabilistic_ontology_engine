"""
sovereign-debt-v1 — Sovereign debt stress and global liquidity domain.

Purpose
-------
Tracks evolving causal narratives around U.S. Treasury yields, sovereign
credit risk, dollar dominance dynamics, Fed balance-sheet policy, and
emerging-market stress.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:
USYieldSpiking
    high  = DGS10 13-week z-score >= +1.0 (yields rising fast vs history)
    low   = yields stable or falling
    Signal: rising long-end rates driven by term premium / fiscal concerns

SpreadWidening
    high  = BAMLH0A0HYM2 (HY OAS) z-score >= +1.0
    low   = credit spreads at or below historical mean
    Signal: credit markets pricing elevated default/liquidity risk

DollarStrengthening
    high  = DEXUSEU below its 52-week mean (USD strengthening vs EUR)
    low   = dollar stable or weakening
    Signal: capital flight to USD safety; often accompanies EM stress

FedBalanceSheetShrinking
    high  = WALCL 13-week change is negative (active QT)
    low   = balance sheet stable or expanding
    Signal: Fed actively withdrawing liquidity from the financial system

EMStressElevated
    high  = DTWEXBGS (broad trade-weighted dollar) z-score >= +1.0
    low   = broad dollar within historical range
    Signal: strong broad dollar → EM debt servicing pressure and capital outflows

FiscalDominanceRisk
    high  = GFDEBTN (federal debt) YoY growth rate above historical mean
    low   = debt growth within historical norms
    Signal: fiscal pressure overwhelming monetary policy independence

CreditDefaultRisk
    high  = BAMLH0A0HYM2 level > 6.0% (absolute stress threshold)
    low   = HY OAS below systemic stress level
    Signal: market pricing high corporate default probability

GlobalLiquidityContracting
    high  = WALCL 13w change + M2SL 3m change both negative (dual contraction)
    low   = at least one liquidity measure stable or expanding
    Signal: simultaneous Fed and broad-money contraction → global tightening

FRED series used
----------------
DGS10         (daily)     — USYieldSpiking
BAMLH0A0HYM2  (daily)     — SpreadWidening, CreditDefaultRisk
DEXUSEU       (daily)     — DollarStrengthening
WALCL         (weekly)    — FedBalanceSheetShrinking, GlobalLiquidityContracting
DTWEXBGS      (weekly)    — EMStressElevated
GFDEBTN       (quarterly) — FiscalDominanceRisk
M2SL          (monthly)   — GlobalLiquidityContracting

Cadence: WEEKLY (every Monday at 09:00 UTC)
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

_MODULE_ID = "sovereign-debt-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "USYieldSpiking",
    "SpreadWidening",
    "DollarStrengthening",
    "FedBalanceSheetShrinking",
    "EMStressElevated",
    "FiscalDominanceRisk",
    "CreditDefaultRisk",
    "GlobalLiquidityContracting",
]

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for sovereign-debt-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class SovereignDebtV1:
    """Domain module for the sovereign debt / global liquidity ontology."""

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
