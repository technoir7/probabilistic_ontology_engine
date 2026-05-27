"""
energy-regime-v1 — Energy market regime domain module.

Purpose
-------
Tracks evolving causal narratives in global energy markets: supply shocks,
demand-driven price surges, geopolitical risk premiums, and the structural
transition toward renewables.  All variables are Boolean regime indicators
derived from futures prices, ETF momentum, and macro data.

Variables (all BOOLEAN)
-----------------------
OilPriceSurge
    True  = CL=F (WTI crude) 13-week return z-score >= +1.0
    False = crude prices stable or falling
    Signal: sustained oil price rally vs recent history

NatGasPriceSurge
    True  = NG=F 13-week return z-score >= +1.0
    False = gas prices stable or falling
    Signal: sustained natural gas price rally

EnergyEquityMomentum
    True  = XLE 13-week return z-score >= +0.5 (energy sector outperforming)
    False = energy equities lagging
    Signal: market expects sustained energy profitability

OPECSupplyConstraint
    True  = DCOILWTICO (WTI FRED) 13-week momentum is positive and above historical mean
    False = oil prices not trending up (supply not constrained)
    Signal: supply-side constraint driving price momentum

RenewablesDisplacement
    True  = ICLN/XLE price ratio above its 52-week z-score (+1.0)
    False = traditional energy outperforming renewables
    Signal: clean energy momentum relative to fossil fuel sector

EnergyInflationPersistent
    True  = CPIENGSL (energy CPI) 12-month YoY > 5%
    False = energy price inflation contained
    Signal: energy prices driving CPI volatility

GeopoliticalRiskElevated
    True  = DCOILWTICO 90-day return volatility above historical 75th percentile
    False = oil price volatility within normal range
    Signal: geopolitical uncertainty driving oil price swings

DemandDestructionRisk
    True  = INDPRO 3-month change is negative AND UNRATE is rising
    False = industrial production stable or unemployment not rising
    Signal: economic slowdown reducing energy demand

Seed ontologies (4 competing hypotheses)
-----------------------------------------
H1: supply_shock
    OPECSupplyConstraint → OilPriceSurge → EnergyInflationPersistent

H2: demand_driven
    DemandDestructionRisk (inverted) → OilPriceSurge → EnergyEquityMomentum

H3: geopolitical_premium
    GeopoliticalRiskElevated → OilPriceSurge → NatGasPriceSurge

H4: renewables_transition
    RenewablesDisplacement → EnergyEquityMomentum → OilPriceSurge (weak, inverted)

Data sources
------------
yfinance: CL=F, NG=F, XLE, ICLN (daily close prices)
FRED:     DCOILWTICO (daily), CPIENGSL (monthly), INDPRO (monthly), UNRATE (monthly)

Cadence: WEEKLY (every Monday at 09:00 UTC)
"""
from __future__ import annotations

from uuid import uuid4

from ...engine.variable_identity import stable_variable_id
from ...engine.schemas import (
    DependencyEdge,
    DependencyKind,
    DomainType,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
    Variable,
)

_MODULE_ID = "energy-regime-v1"

_VAR_NAMES = [
    "OilPriceSurge",
    "NatGasPriceSurge",
    "EnergyEquityMomentum",
    "OPECSupplyConstraint",
    "RenewablesDisplacement",
    "EnergyInflationPersistent",
    "GeopoliticalRiskElevated",
    "DemandDestructionRisk",
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
    return _VARIABLE_DEFS


def _var(name: str) -> Variable:
    return _VARIABLE_DEFS[name]


def _var_list() -> list[Variable]:
    return list(_VARIABLE_DEFS.values())


def _edge(parent: str, child: str, prior: float = 0.60, label: str = "") -> DependencyEdge:
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


def make_supply_shock_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: supply_shock — OPEC-driven supply constraint cascade.

    Hypothesis: OPEC+ supply cuts create a sustained oil price rally
    which feeds through to energy inflation and pulls natural gas prices
    higher as fuel switching increases demand.

        OPECSupplyConstraint → OilPriceSurge
        OilPriceSurge → EnergyInflationPersistent
        OilPriceSurge → NatGasPriceSurge
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("OPECSupplyConstraint",     "OilPriceSurge",             prior=0.70,
                  label="OPEC supply cut → oil price surge"),
            _edge("OilPriceSurge",             "EnergyInflationPersistent", prior=0.65,
                  label="oil rally → energy CPI elevated"),
            _edge("OilPriceSurge",             "NatGasPriceSurge",          prior=0.60,
                  label="oil surge → fuel switching → gas demand"),
        ],
        description="H1: supply_shock",
    )


def make_demand_driven_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: demand_driven — Strong demand driving energy price surge.

    Hypothesis: Absence of demand destruction (DemandDestructionRisk=False)
    supports sustained energy demand, driving oil prices higher which lifts
    energy equity valuations.

        DemandDestructionRisk → OilPriceSurge (negative: no destruction → price up)
        OilPriceSurge → EnergyEquityMomentum
        OilPriceSurge → EnergyInflationPersistent
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("DemandDestructionRisk",    "OilPriceSurge",             prior=0.60,
                  label="demand resilience → oil price support"),
            _edge("OilPriceSurge",             "EnergyEquityMomentum",      prior=0.70,
                  label="oil surge → energy equity outperformance"),
            _edge("OilPriceSurge",             "EnergyInflationPersistent", prior=0.60,
                  label="oil price → energy inflation"),
        ],
        description="H2: demand_driven",
    )


def make_geopolitical_premium_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: geopolitical_premium — Geopolitical risk driving cross-commodity surge.

    Hypothesis: Elevated geopolitical risk drives oil price volatility and
    a persistent risk premium that also spills into natural gas markets
    (common supply infrastructure and fuel switching).

        GeopoliticalRiskElevated → OilPriceSurge
        OilPriceSurge → NatGasPriceSurge
        GeopoliticalRiskElevated → EnergyInflationPersistent
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("GeopoliticalRiskElevated", "OilPriceSurge",             prior=0.70,
                  label="geopolitical risk → oil risk premium"),
            _edge("OilPriceSurge",             "NatGasPriceSurge",          prior=0.65,
                  label="oil → gas cross-commodity linkage"),
            _edge("GeopoliticalRiskElevated", "EnergyInflationPersistent", prior=0.60,
                  label="geopolitical supply risk → energy inflation"),
        ],
        description="H3: geopolitical_premium",
    )


def make_renewables_transition_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: renewables_transition — Clean energy displacement narrative.

    Hypothesis: Renewable energy momentum (ICLN outperforming XLE) drives
    energy equity market leadership and weakens the long-run demand signal
    for fossil fuel prices.

        RenewablesDisplacement → EnergyEquityMomentum
        EnergyEquityMomentum → OilPriceSurge
        RenewablesDisplacement → OPECSupplyConstraint
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("RenewablesDisplacement", "EnergyEquityMomentum", prior=0.60,
                  label="clean energy momentum → energy sector rerating"),
            _edge("EnergyEquityMomentum",   "OilPriceSurge",         prior=0.55,
                  label="energy equity momentum → oil demand expectation"),
            _edge("RenewablesDisplacement", "OPECSupplyConstraint",  prior=0.55,
                  label="renewables pressure → OPEC defends price"),
        ],
        description="H4: renewables_transition",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct geopolitical → oil linkage is structural.

        GeopoliticalRiskElevated → OilPriceSurge
        OPECSupplyConstraint → OilPriceSurge
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("GeopoliticalRiskElevated", "OilPriceSurge",        prior=0.55,
                  label="geopolitical → oil (baseline)"),
            _edge("OPECSupplyConstraint",      "OilPriceSurge",        prior=0.55,
                  label="OPEC → oil (baseline)"),
        ],
        description="T_null: direct supply-geopolitical baseline",
    )


class EnergyRegimeV1:
    """Domain module for the energy regime ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_supply_shock_candidate(self._MODULE_ID),
            make_demand_driven_candidate(self._MODULE_ID),
            make_geopolitical_premium_candidate(self._MODULE_ID),
            make_renewables_transition_candidate(self._MODULE_ID),
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
