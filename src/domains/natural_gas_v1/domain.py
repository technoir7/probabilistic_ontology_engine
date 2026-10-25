"""
natural-gas-v1 — U.S. natural gas market domain module.

Variables (levels: low, mid, high; REFACTOR_SPEC D25)
-----------------------------------------------------
Each is read as how far its signal lies from the line below (high: well
above it, mid: near it, low: well below). The lines:

    TempAnom    high = CONUS daily mean temperature well *above* its seasonal normal
                low  = well below it (colder than expected; higher heating demand)

    HeatingDem  high = strong heating demand (HDD well above 5)
                low  = little or none (HDD near 0)

    StorageDraw high = EIA weekly Lower-48 storage fell week-over-week (a net draw)
                low  = storage rose (a net build)

    PriceUp     high = Henry Hub spot price well *above* its rolling 4-week median
                low  = well below it
"""
from __future__ import annotations

from ..sources.grades import graded_variables
from ..sources.structure import with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
    Variable,
)


# ---------------------------------------------------------------------------
# Canonical variable definitions — module-level singletons.
# UUIDs are fixed at import time and shared by all candidates and the pipeline.
# ---------------------------------------------------------------------------

_VARIABLE_DEFS: dict[str, Variable] = graded_variables(
    "natural-gas-v1", ["TempAnom", "HeatingDem", "StorageDraw", "PriceUp"]
)


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
