"""
geopolitics-v1 — Geopolitical risk and global stability domain.

Purpose
-------
Tracks evolving causal narratives around geopolitical risk transmission:
conflict intensity, trade disruption, sanctions pressure, diplomatic tension,
supply chain stress, currency war dynamics, energy weaponization, and
global trade volume.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:
ConflictIntensityElevated
    high  = GDELT "conflict war" article volume 4-week avg z-score elevated
    Signal: media coverage of military conflicts rising

TradeDisruptionRisk
    high  = DCOILWTICO z-score elevated (rising oil = trade disruption risk)
    Signal: commodity price pressure indicating supply disruption

SanctionsPressureElevated
    high  = GDELT "sanctions" article volume 4-week avg z-score elevated
    Signal: economic sanctions activity in news coverage

DiplomaticTensionHigh
    high  = GDELT "diplomatic tension" article volume 4-week avg z-score elevated
    Signal: diplomatic fallout and rising international tensions

SupplyChainStress
    high  = DCOILWTICO + PPIACO composite z-score elevated
    Signal: dual cost-push from oil and producer prices

CurrencyWarSignal
    high  = DTWEXBGS rolling 4-week volatility z-score elevated
    Signal: dollar volatility indicating competitive devaluations

EnergyWeaponizationRisk
    high  = GDELT "energy sanctions" + DCOILWTICO momentum composite elevated
    Signal: energy being used as geopolitical leverage

GlobalTradeVolumeWeak
    high  = INDPRO 3-month change inverted z-score elevated (weak production)
    Signal: declining industrial production as trade proxy

Cadence: WEEKLY
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

_MODULE_ID = "geopolitics-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "ConflictIntensityElevated",
    "TradeDisruptionRisk",
    "SanctionsPressureElevated",
    "DiplomaticTensionHigh",
    "SupplyChainStress",
    "CurrencyWarSignal",
    "EnergyWeaponizationRisk",
    "GlobalTradeVolumeWeak",
]

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for geopolitics-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class GeopoliticsV1:
    """Domain module for the geopolitics / global stability ontology."""

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
