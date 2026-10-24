"""
natural-gas-v1 — U.S. natural gas market domain module.

Variables (all BOOLEAN):
    TempAnom    True  = CONUS daily mean temperature is *above* its seasonal normal
                False = below seasonal normal (colder than expected; higher heating demand)

    HeatingDem  True  = heating demand is active (mean temp < 65°F / 18.33°C; HDD > 0)
                False = no meaningful heating demand

    StorageDraw True  = EIA weekly Lower-48 storage *decreased* week-over-week (a net draw)
                False = storage increased (a net build)

    PriceUp     True  = Henry Hub spot price is *above* its rolling 4-week median
                False = at or below median
"""
from __future__ import annotations

from ..sources.structure import with_lags
from ...engine.variable_identity import stable_variable_id
from ...engine.schemas import (
    DomainType,
    EdgeExistenceThresholdConfig,
    Variable,
)


# ---------------------------------------------------------------------------
# Canonical variable definitions — module-level singletons.
# UUIDs are fixed at import time and shared by all candidates and the pipeline.
# ---------------------------------------------------------------------------

_VARIABLE_DEFS: dict[str, Variable] = {
    name: Variable(
        variable_id=stable_variable_id("natural-gas-v1", name),
        name=name,
        domain_type=DomainType.BOOLEAN,
        support=[True, False],
    )
    for name in ["TempAnom", "HeatingDem", "StorageDraw", "PriceUp"]
}


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for natural-gas-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class NaturalGasV1:
    _MODULE_ID = "natural-gas-v1"

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
