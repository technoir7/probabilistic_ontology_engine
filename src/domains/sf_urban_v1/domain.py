"""
sf-urban-v1 — San Francisco urban economic health domain.

Purpose
-------
Tracks evolving causal narratives around SF's urban economic trajectory:
tech hiring, office vacancy, retail closures, permit activity, crime,
startup formation, foot traffic, and population flow.

Variables (all BOOLEAN)
-----------------------
TechHiringAccelerating
    True  = FRED SF info employment YoY change z-score elevated
    Signal: tech sector expanding in SF-Oakland metro

OfficeVacancyFalling
    True  = SF building permits commercial/office fraction falling (inverted)
    Signal: commercial space demand recovering

RetailClosureElevated
    True  = SF business license expirations count z-score elevated
    Signal: retail businesses closing at elevated rate

PermitActivityRising
    True  = SF total building permits count z-score elevated
    Signal: construction/development activity increasing

CrimeIndexElevated
    True  = SF police incidents count z-score elevated
    Signal: crime deterring foot traffic and business activity

StartupFormationRising
    True  = SF new business registrations count z-score elevated
    Signal: entrepreneurial activity recovering

FootTrafficRecovering
    True  = FRED SF leisure/hospitality employment YoY change z-score elevated
    Signal: consumer-facing economy recovering

PopulationFlowPositive
    True  = FRED SF total employment YoY change z-score elevated
    Signal: population returning / net inflow

Cadence: WEEKLY (uses monthly/quarterly data)
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

_MODULE_ID = "sf-urban-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "TechHiringAccelerating",
    "OfficeVacancyFalling",
    "RetailClosureElevated",
    "PermitActivityRising",
    "CrimeIndexElevated",
    "StartupFormationRising",
    "FootTrafficRecovering",
    "PopulationFlowPositive",
]

_VARIABLE_DEFS: dict[str, Variable] = boolean_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for sf-urban-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class SFUrbanV1:
    """Domain module for the SF urban economic health ontology."""

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
