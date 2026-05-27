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

Seeds
-----
H1 tech_rebound: TechHiringAccelerating → StartupFormationRising → PermitActivityRising
H2 structural_decline: RetailClosureElevated → OfficeVacancyFalling → PopulationFlowPositive
H3 bifurcated_recovery: TechHiringAccelerating → FootTrafficRecovering → StartupFormationRising
H4 bottom_formation: PermitActivityRising → FootTrafficRecovering → RetailClosureElevated
T_null: TechHiringAccelerating → FootTrafficRecovering

Cadence: WEEKLY (uses monthly/quarterly data)
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

_VARIABLE_DEFS: dict[str, Variable] = {
    name: Variable(
        variable_id=stable_variable_id(_MODULE_ID, name),
        name=name,
        domain_type=DomainType.BOOLEAN,
        support=[True, False],
    )
    for name in _VAR_NAMES
}


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for sf-urban-v1."""
    return _VARIABLE_DEFS


def _var(name: str) -> Variable:
    return _VARIABLE_DEFS[name]


def _var_list() -> list[Variable]:
    return list(_VARIABLE_DEFS.values())


# ---------------------------------------------------------------------------
# Edge factory
# ---------------------------------------------------------------------------

def _edge(
    parent: str,
    child: str,
    prior: float = 0.60,
    label: str = "",
) -> DependencyEdge:
    return DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=_var(parent).variable_id,
        child_variable_id=_var(child).variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
        existence_prior=prior,
        existence_probability=prior,
        learnable=True,
        enabled=True,
        explanatory_label=label or f"{parent}→{child}",
    )


# ---------------------------------------------------------------------------
# Candidate factories
# ---------------------------------------------------------------------------

def make_tech_rebound_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: tech_rebound — Tech hiring drives startup formation and permits.

    Hypothesis: Renewed tech hiring creates wealth effects and talent pools
    that drive startup formation, which in turn generates demand for commercial
    permits as startups lease office space.

        TechHiringAccelerating → StartupFormationRising
        StartupFormationRising → PermitActivityRising
        FootTrafficRecovering → TechHiringAccelerating
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TechHiringAccelerating", "StartupFormationRising", prior=0.65,
                  label="tech hiring → talent pool for startups"),
            _edge("StartupFormationRising", "PermitActivityRising", prior=0.60,
                  label="startup formation → office/commercial permits"),
            _edge("FootTrafficRecovering", "TechHiringAccelerating", prior=0.60,
                  label="foot traffic recovery → local amenity → tech attraction"),
        ],
        description="H1: tech_rebound",
    )


def make_structural_decline_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: structural_decline — Retail closures signal and drive office vacancy.

    Hypothesis: Elevated retail closures reflect a structural shift in urban
    viability (remote work, crime, costs) that also drives office vacancy
    through shared causal pressures, ultimately depressing population flow.

        RetailClosureElevated → OfficeVacancyFalling
        OfficeVacancyFalling → PopulationFlowPositive
        CrimeIndexElevated → RetailClosureElevated
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("RetailClosureElevated", "OfficeVacancyFalling", prior=0.65,
                  label="retail closures → neighborhood decline → office exodus"),
            _edge("OfficeVacancyFalling", "PopulationFlowPositive", prior=0.60,
                  label="office recovery → population return"),
            _edge("CrimeIndexElevated", "RetailClosureElevated", prior=0.65,
                  label="elevated crime → retail business closure"),
        ],
        description="H2: structural_decline",
    )


def make_bifurcated_recovery_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: bifurcated_recovery — Tech sector recovers while urban core lags.

    Hypothesis: SF experiences a bifurcated recovery where tech hiring
    accelerates (remote/hybrid normalization) while foot traffic and
    startup formation recover only partially, driven by tech wealth effects.

        TechHiringAccelerating → FootTrafficRecovering
        FootTrafficRecovering → StartupFormationRising
        PermitActivityRising → TechHiringAccelerating
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TechHiringAccelerating", "FootTrafficRecovering", prior=0.60,
                  label="tech hiring → worker return → foot traffic"),
            _edge("FootTrafficRecovering", "StartupFormationRising", prior=0.60,
                  label="foot traffic → viable market → startup formation"),
            _edge("PermitActivityRising", "TechHiringAccelerating", prior=0.60,
                  label="permit activity → new office space → tech office demand"),
        ],
        description="H3: bifurcated_recovery",
    )


def make_bottom_formation_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: bottom_formation — Permit activity and foot traffic signal cyclical bottom.

    Hypothesis: Rising permit activity (developers betting on recovery)
    drives foot traffic improvements through new amenities and housing,
    which then reduces retail pressure as consumer spending returns.

        PermitActivityRising → FootTrafficRecovering
        FootTrafficRecovering → RetailClosureElevated
        StartupFormationRising → PermitActivityRising
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("PermitActivityRising", "FootTrafficRecovering", prior=0.60,
                  label="new construction → amenities → foot traffic recovery"),
            _edge("FootTrafficRecovering", "RetailClosureElevated", prior=0.60,
                  label="foot traffic recovery → retail viability improves"),
            _edge("StartupFormationRising", "PermitActivityRising", prior=0.60,
                  label="startup formation → office space demand → permits"),
        ],
        description="H4: bottom_formation",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct tech hiring → foot traffic linkage.

    Hypothesis: All SF urban signals are noise except the direct
    relationship between tech hiring and foot traffic recovery.

        TechHiringAccelerating → FootTrafficRecovering
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TechHiringAccelerating", "FootTrafficRecovering", prior=0.55,
                  label="tech hiring → foot traffic (baseline)"),
        ],
        description="T_null: tech-foottraffic baseline",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class SFUrbanV1:
    """Domain module for the SF urban economic health ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_tech_rebound_candidate(self._MODULE_ID),
            make_structural_decline_candidate(self._MODULE_ID),
            make_bifurcated_recovery_candidate(self._MODULE_ID),
            make_bottom_formation_candidate(self._MODULE_ID),
            make_null_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
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
