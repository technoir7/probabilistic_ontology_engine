"""
soybean-v1 — U.S. soybean (ZS) market domain module.

Variables (all BOOLEAN):
    PlantingDelayed     True  = current soybean planting progress is more than 5 percentage
                                points behind the 5-year average for the same calendar week
                        False = on-pace or ahead of schedule

    DroughtIndex        True  = USDA NASS crop condition ratings show less than 55%
                                of the crop rated GOOD or EXCELLENT — a proxy for
                                the growing-season stress that often accompanies drought
                        False = conditions adequate (≥55% good/excellent)

    YieldForecastDown   True  = the most recent USDA NASS/WASDE soybean yield forecast
                                (BU/AC) is below the prior crop year's final yield
                        False = current forecast matches or exceeds prior year

    SoyPriceUp          True  = ZS front-month futures settlement price is above the
                                20-day rolling average
                        False = at or below the rolling average

Candidate structures:
    W*   — weather-dominant: planting delays and drought stress reduce yield,
             which drives price up:
               PlantingDelayed → YieldForecastDown
               DroughtIndex    → YieldForecastDown
               YieldForecastDown → SoyPriceUp

    D*   — demand-dominant: yield effects are the primary price driver:
               YieldForecastDown  → SoyPriceUp

    Null — minimal structure: only the obvious supply/price link:
               YieldForecastDown → SoyPriceUp
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
        variable_id=stable_variable_id("soybean-v1", name),
        name=name,
        domain_type=DomainType.BOOLEAN,
        support=[True, False],
    )
    for name in [
        "PlantingDelayed",
        "DroughtIndex",
        "YieldForecastDown",
        "SoyPriceUp",
    ]
}


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for soybean-v1."""
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

def make_weather_dominant_candidate(module_id: str = "soybean-v1") -> OntologyCandidate:
    """
    W*: PlantingDelayed → YieldForecastDown ← DroughtIndex → YieldForecastDown → SoyPriceUp

    Weather conditions (planting delays and drought stress) are the primary
    drivers of yield shortfalls, which drive soybean price higher.
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("PlantingDelayed",   "YieldForecastDown", prior=0.70),
            _edge("DroughtIndex",      "YieldForecastDown", prior=0.75),
            _edge("YieldForecastDown", "SoyPriceUp",        prior=0.65),
        ],
        description="W*: weather-dominant (planting + drought → yield → price)",
    )


def make_demand_dominant_candidate(module_id: str = "soybean-v1") -> OntologyCandidate:
    """
    D*: YieldForecastDown → SoyPriceUp

    Yield signals drive soybean price. Weather effects are assumed already
    priced in; no planting/drought edges.
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("YieldForecastDown", "SoyPriceUp", prior=0.60),
        ],
        description="D*: demand-dominant (yield → price)",
    )


def make_null_candidate(module_id: str = "soybean-v1") -> OntologyCandidate:
    """
    Null: YieldForecastDown → SoyPriceUp only.

    Minimal structure — supply/price link only, ignoring weather and demand.
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("YieldForecastDown", "SoyPriceUp", prior=0.55),
        ],
        description="null: supply-only (yield → price)",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class SoybeanV1:
    _MODULE_ID = "soybean-v1"

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_weather_dominant_candidate(self._MODULE_ID),
            make_demand_dominant_candidate(self._MODULE_ID),
            make_null_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        # Seed ontologies are scaffolding. Expected to be displaced by
        # data-driven structures as evidence accumulates.
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),
        )

    def initial_entities(self) -> list:
        return []

    def initial_assertions(self) -> list:
        return []

    def variable_specs(self) -> list:
        return []

    def initial_parameterizations(self) -> list:
        return []
