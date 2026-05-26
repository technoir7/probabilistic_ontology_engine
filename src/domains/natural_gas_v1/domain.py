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

Candidate structures:
    T*      — demand-chain: weather anomaly drives heating demand, which drives
              storage draws, which drives price:
                TempAnom → HeatingDem → StorageDraw → PriceUp

    T_alt   — temperature also has a direct path to storage draw (bypassing the
              explicit heating-demand signal, e.g. industrial/power-gen switching):
                TempAnom → HeatingDem
                TempAnom → StorageDraw
                StorageDraw → PriceUp

    Null    — only the storage-to-price link (ignores weather entirely):
                StorageDraw → PriceUp
"""
from __future__ import annotations

from uuid import uuid4

from ...engine.variable_identity import stable_variable_id
from ...engine.schemas import (
    CandidateStatus,
    DependencyEdge,
    DependencyKind,
    DomainType,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
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


def _var(name: str) -> Variable:
    return _VARIABLE_DEFS[name]


def _edge(pname: str, cname: str, prior: float = 0.6) -> DependencyEdge:
    return DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=_var(pname).variable_id,
        child_variable_id=_var(cname).variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
        existence_prior=prior,
        existence_probability=prior,
        learnable=True,
        enabled=True,
    )


def _var_list() -> list[Variable]:
    return list(_VARIABLE_DEFS.values())


# ---------------------------------------------------------------------------
# Candidate factories
# ---------------------------------------------------------------------------

def make_tstar_candidate(module_id: str = "natural-gas-v1") -> OntologyCandidate:
    """
    T*: TempAnom → HeatingDem → StorageDraw → PriceUp
    Prior reflects known gas-market demand chain.
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TempAnom",   "HeatingDem",  prior=0.75),
            _edge("HeatingDem", "StorageDraw", prior=0.70),
            _edge("StorageDraw","PriceUp",     prior=0.70),
        ],
        description="T*: demand-chain",
    )


def make_talt_candidate(module_id: str = "natural-gas-v1") -> OntologyCandidate:
    """
    T_alt: TempAnom → HeatingDem, TempAnom → StorageDraw, StorageDraw → PriceUp
    Temperature drives storage directly (power-gen / industrial switching).
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TempAnom",   "HeatingDem",  prior=0.75),
            _edge("TempAnom",   "StorageDraw", prior=0.55),
            _edge("StorageDraw","PriceUp",     prior=0.70),
        ],
        description="T_alt: temp-direct",
    )


def make_null_candidate(module_id: str = "natural-gas-v1") -> OntologyCandidate:
    """
    Null: StorageDraw → PriceUp only (weather-blind baseline).
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("StorageDraw", "PriceUp", prior=0.60),
        ],
        description="null: storage-only",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class NaturalGasV1:
    _MODULE_ID = "natural-gas-v1"

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_tstar_candidate(self._MODULE_ID),
            make_talt_candidate(self._MODULE_ID),
            make_null_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.3, 0.7),
        )

    def initial_entities(self) -> list:
        return []

    def initial_assertions(self) -> list:
        return []

    def variable_specs(self) -> list:
        return []

    def initial_parameterizations(self) -> list:
        return []
