"""
What the engine requires of a domain module (REFACTOR_SPEC 4.1).

Only what the engine calls. SPEC §8 lists more methods (initial_entities,
variable_specs, ...); every domain returned [] from them and nothing read
them, so they are not part of the contract (decision D5).
"""
from __future__ import annotations

from typing import Protocol

from ..schemas import EdgeExistenceThresholdConfig, OntologyCandidate


class DomainModule(Protocol):
    def module_id(self) -> str: ...

    def initial_candidates(self) -> list[OntologyCandidate]:
        """Seed candidates; all must share one variable list with stable ids."""
        ...

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig: ...


# Every live domain uses these; a domain returns them unless it tunes its own.
DEFAULT_THRESHOLDS = EdgeExistenceThresholdConfig(
    prune_below=0.05, accept_above=0.90, explore_band=(0.25, 0.75)
)
