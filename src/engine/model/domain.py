"""
What the engine requires of a domain module (REFACTOR_SPEC 4.1).

Only what the engine calls. SPEC §8 lists more methods (initial_entities,
variable_specs, ...); every domain returned [] from them and nothing read
them, so they are not part of the contract (decision D5).
"""
from __future__ import annotations

from typing import Protocol

from ..schemas import EdgeExistenceThresholdConfig, Variable


class DomainModule(Protocol):
    def module_id(self) -> str: ...

    def variables(self) -> list[Variable]:
        """The domain's concepts, with ids stable across restarts. A domain
        gives no hypotheses about how they connect: the engine begins with
        none and forms its own from the evidence (REFACTOR_SPEC D24)."""
        ...

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig: ...


# Every live domain uses these; a domain returns them unless it tunes its own.
DEFAULT_THRESHOLDS = EdgeExistenceThresholdConfig(
    prune_below=0.05, accept_above=0.90, explore_band=(0.25, 0.75)
)
