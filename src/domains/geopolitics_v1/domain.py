"""
geopolitics-v1 — Geopolitical risk and global stability domain.

Purpose
-------
Tracks evolving causal narratives around geopolitical risk transmission:
conflict intensity, trade disruption, sanctions pressure, diplomatic tension,
supply chain stress, currency war dynamics, energy weaponization, and
global trade volume.

Variables (all BOOLEAN)
-----------------------
ConflictIntensityElevated
    True  = GDELT "conflict war" article volume 4-week avg z-score elevated
    Signal: media coverage of military conflicts rising

TradeDisruptionRisk
    True  = DCOILWTICO z-score elevated (rising oil = trade disruption risk)
    Signal: commodity price pressure indicating supply disruption

SanctionsPressureElevated
    True  = GDELT "sanctions" article volume 4-week avg z-score elevated
    Signal: economic sanctions activity in news coverage

DiplomaticTensionHigh
    True  = GDELT "diplomatic tension" article volume 4-week avg z-score elevated
    Signal: diplomatic fallout and rising international tensions

SupplyChainStress
    True  = DCOILWTICO + PPIACO composite z-score elevated
    Signal: dual cost-push from oil and producer prices

CurrencyWarSignal
    True  = DTWEXBGS rolling 4-week volatility z-score elevated
    Signal: dollar volatility indicating competitive devaluations

EnergyWeaponizationRisk
    True  = GDELT "energy sanctions" + DCOILWTICO momentum composite elevated
    Signal: energy being used as geopolitical leverage

GlobalTradeVolumeWeak
    True  = INDPRO 3-month change inverted z-score elevated (weak production)
    Signal: declining industrial production as trade proxy

Seeds
-----
H1 great_power_competition: DiplomaticTensionHigh → SanctionsPressureElevated → TradeDisruptionRisk
H2 resource_conflict: EnergyWeaponizationRisk → SupplyChainStress → TradeDisruptionRisk
H3 deglobalization: GlobalTradeVolumeWeak → SupplyChainStress → CurrencyWarSignal
H4 regional_instability: ConflictIntensityElevated → TradeDisruptionRisk → SupplyChainStress
T_null: ConflictIntensityElevated → TradeDisruptionRisk

Cadence: WEEKLY
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
    """Return the shared canonical variable set for geopolitics-v1."""
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

def make_great_power_competition_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: great_power_competition — Diplomatic tensions escalate to economic coercion.

    Hypothesis: Rising diplomatic friction between major powers leads to
    sanctions deployment, which then creates trade disruption as supply
    chains reconfigure around geopolitical blocs.

        DiplomaticTensionHigh → SanctionsPressureElevated
        SanctionsPressureElevated → TradeDisruptionRisk
        CurrencyWarSignal → DiplomaticTensionHigh
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("DiplomaticTensionHigh", "SanctionsPressureElevated", prior=0.65,
                  label="diplomatic tension → sanctions deployment"),
            _edge("SanctionsPressureElevated", "TradeDisruptionRisk", prior=0.65,
                  label="sanctions pressure → trade route disruption"),
            _edge("CurrencyWarSignal", "DiplomaticTensionHigh", prior=0.60,
                  label="currency volatility → diplomatic friction"),
        ],
        description="H1: great_power_competition",
    )


def make_resource_conflict_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: resource_conflict — Energy weaponization cascades to supply chain stress.

    Hypothesis: The weaponization of energy resources creates upstream supply
    chain stress through oil price shocks and producer cost inflation,
    which then manifests as trade disruption as countries restructure
    energy-dependent supply chains.

        EnergyWeaponizationRisk → SupplyChainStress
        SupplyChainStress → TradeDisruptionRisk
        ConflictIntensityElevated → EnergyWeaponizationRisk
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("EnergyWeaponizationRisk", "SupplyChainStress", prior=0.65,
                  label="energy weaponization → supply cost shock"),
            _edge("SupplyChainStress", "TradeDisruptionRisk", prior=0.65,
                  label="supply chain stress → trade disruption"),
            _edge("ConflictIntensityElevated", "EnergyWeaponizationRisk", prior=0.60,
                  label="armed conflict → energy infrastructure targeting"),
        ],
        description="H2: resource_conflict",
    )


def make_deglobalization_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: deglobalization — Weak trade volume drives supply fragmentation and currency wars.

    Hypothesis: Structural decline in global trade volumes reflects deglobalization
    pressures that create supply chain fragmentation, which then triggers
    competitive currency devaluations as nations try to boost exports.

        GlobalTradeVolumeWeak → SupplyChainStress
        SupplyChainStress → CurrencyWarSignal
        SanctionsPressureElevated → GlobalTradeVolumeWeak
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("GlobalTradeVolumeWeak", "SupplyChainStress", prior=0.65,
                  label="trade volume decline → supply fragmentation"),
            _edge("SupplyChainStress", "CurrencyWarSignal", prior=0.60,
                  label="supply stress → competitive devaluation pressure"),
            _edge("SanctionsPressureElevated", "GlobalTradeVolumeWeak", prior=0.60,
                  label="sanctions → trade route contraction"),
        ],
        description="H3: deglobalization",
    )


def make_regional_instability_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: regional_instability — Armed conflict directly disrupts trade and supply chains.

    Hypothesis: Regional armed conflict directly disrupts trade routes and
    shipping lanes, creating immediate supply chain stress through logistics
    disruption and insurance cost spikes.

        ConflictIntensityElevated → TradeDisruptionRisk
        TradeDisruptionRisk → SupplyChainStress
        DiplomaticTensionHigh → ConflictIntensityElevated
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("ConflictIntensityElevated", "TradeDisruptionRisk", prior=0.65,
                  label="armed conflict → trade route disruption"),
            _edge("TradeDisruptionRisk", "SupplyChainStress", prior=0.65,
                  label="trade disruption → supply chain cost shock"),
            _edge("DiplomaticTensionHigh", "ConflictIntensityElevated", prior=0.60,
                  label="diplomatic breakdown → conflict escalation"),
        ],
        description="H4: regional_instability",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct conflict → trade disruption linkage.

    Hypothesis: All geopolitical signals are noise except the direct
    relationship between conflict intensity and trade disruption risk.

        ConflictIntensityElevated → TradeDisruptionRisk
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("ConflictIntensityElevated", "TradeDisruptionRisk", prior=0.55,
                  label="conflict → trade disruption (baseline)"),
        ],
        description="T_null: conflict-trade baseline",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class GeopoliticsV1:
    """Domain module for the geopolitics / global stability ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_great_power_competition_candidate(self._MODULE_ID),
            make_resource_conflict_candidate(self._MODULE_ID),
            make_deglobalization_candidate(self._MODULE_ID),
            make_regional_instability_candidate(self._MODULE_ID),
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
