"""
labor-market-v1 — Labor market regime domain module.

Purpose
-------
Tracks evolving causal narratives in the U.S. labor market: labor market
tightening cycles, layoff cycle inception, structural labor force shifts, and
wage-price spiral dynamics.  Variables bridge labor market conditions with
inflation and productivity outcomes.

Variables (all BOOLEAN)
-----------------------
UnemploymentRising
    True  = UNRATE z-score vs 12-month mean is positive (unemployment rising)
    False = unemployment stable or falling

WageInflationPersistent
    True  = CES0500000003 YoY growth rate above historical mean
    False = wage growth at or below trend
    Signal: labor market pricing power flowing to workers

JobOpeningsFalling
    True  = JTSJOL z-score is negative (job openings declining vs history)
    False = job openings at or above historical level
    Signal: falling openings = demand for labor weakening (inverted z-score)

LayoffCycleBeginning
    True  = ICSA (initial claims) z-score >= +1.0 (claims rising)
    False = initial claims within normal range
    Signal: rising layoffs = early recessionary labor signal

LaborProductivityWeak
    True  = PRS85006092 (nonfarm business real output/hour) YoY < historical mean
    False = productivity growing at or above trend
    Signal: weak productivity = wage growth not matched by output

ParticipationRateFalling
    True  = CIVPART z-score is negative (participation declining)
    False = participation stable or rising
    Signal: structural exit from labor force (inverted z-score)

RealWageGrowthPositive
    True  = CES0500000003 YoY minus CPIAUCSL YoY is positive
    False = real wages flat or falling
    Signal: workers gaining purchasing power in real terms

TightLaborMarket
    True  = UNRATE inverted z-score + JTSJOL z-score composite is positive
    False = labor market conditions loosening
    Signal: dual confirmation of labor market tightness

Seed ontologies (4 competing hypotheses)
-----------------------------------------
H1: labor_tightening
    TightLaborMarket → WageInflationPersistent → RealWageGrowthPositive

H2: layoff_cycle
    LayoffCycleBeginning → UnemploymentRising → LaborProductivityWeak

H3: structural_shift
    ParticipationRateFalling → TightLaborMarket → WageInflationPersistent

H4: wage_price_spiral
    WageInflationPersistent → RealWageGrowthPositive → TightLaborMarket

FRED series used
----------------
UNRATE          (monthly)   — UnemploymentRising, TightLaborMarket
CES0500000003   (monthly)   — WageInflationPersistent, RealWageGrowthPositive
JTSJOL          (monthly)   — JobOpeningsFalling, TightLaborMarket
ICSA            (weekly)    — LayoffCycleBeginning
PRS85006092     (quarterly) — LaborProductivityWeak
CIVPART         (monthly)   — ParticipationRateFalling
CPIAUCSL        (monthly)   — RealWageGrowthPositive (for real wage computation)

Cadence: WEEKLY (every Monday at 09:00 UTC; monthly/quarterly series
         read at latest published value per week)
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

_MODULE_ID = "labor-market-v1"

_VAR_NAMES = [
    "UnemploymentRising",
    "WageInflationPersistent",
    "JobOpeningsFalling",
    "LayoffCycleBeginning",
    "LaborProductivityWeak",
    "ParticipationRateFalling",
    "RealWageGrowthPositive",
    "TightLaborMarket",
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


def make_labor_tightening_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: labor_tightening — Tight labor market drives wage and real wage dynamics.

    Hypothesis: A tight labor market (low unemployment, high openings) gives
    workers bargaining power that drives wage inflation, which eventually
    translates to positive real wage growth.

        TightLaborMarket → WageInflationPersistent
        WageInflationPersistent → RealWageGrowthPositive
        JobOpeningsFalling → TightLaborMarket (negative: fewer openings = loosening)
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("TightLaborMarket",        "WageInflationPersistent",  prior=0.70,
                  label="tight labor → wage pressure"),
            _edge("WageInflationPersistent",  "RealWageGrowthPositive",   prior=0.65,
                  label="wage growth → real wage gains"),
            _edge("JobOpeningsFalling",       "TightLaborMarket",          prior=0.60,
                  label="falling openings → loosening market"),
        ],
        description="H1: labor_tightening",
    )


def make_layoff_cycle_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: layoff_cycle — Initial claims spike leads to unemployment rise and
    productivity weakness.

    Hypothesis: Rising layoffs (initial claims) are the first signal of a
    labor market deterioration that leads to rising unemployment, which
    weakens aggregate productivity as human capital is underutilized.

        LayoffCycleBeginning → UnemploymentRising
        UnemploymentRising → LaborProductivityWeak
        LayoffCycleBeginning → JobOpeningsFalling
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("LayoffCycleBeginning", "UnemploymentRising",    prior=0.70,
                  label="layoffs → unemployment rising"),
            _edge("UnemploymentRising",   "LaborProductivityWeak", prior=0.65,
                  label="rising unemployment → productivity weakness"),
            _edge("LayoffCycleBeginning", "JobOpeningsFalling",    prior=0.60,
                  label="layoffs → demand for new hires falls"),
        ],
        description="H2: layoff_cycle",
    )


def make_structural_shift_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: structural_shift — Participation rate decline creates artificial tightness.

    Hypothesis: Workers exiting the labor force (participation falling) mechanically
    tightens the measured labor market without genuine demand strength, creating
    wage pressure from structural rather than cyclical forces.

        ParticipationRateFalling → TightLaborMarket
        TightLaborMarket → WageInflationPersistent
        ParticipationRateFalling → LaborProductivityWeak
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("ParticipationRateFalling", "TightLaborMarket",        prior=0.65,
                  label="supply shrinkage → artificial tightness"),
            _edge("TightLaborMarket",          "WageInflationPersistent", prior=0.65,
                  label="tight market → wage pressure"),
            _edge("ParticipationRateFalling", "LaborProductivityWeak",   prior=0.55,
                  label="workforce shrinkage → aggregate productivity drag"),
        ],
        description="H3: structural_shift",
    )


def make_wage_price_spiral_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: wage_price_spiral — Wages and real wages reinforce labor tightness.

    Hypothesis: Once wage inflation is established, it self-reinforces: higher
    nominal wages reduce real wage benefits (if CPI rises too), and workers
    seek further nominal raises, maintaining tight labor conditions.

        WageInflationPersistent → RealWageGrowthPositive
        RealWageGrowthPositive → TightLaborMarket
        WageInflationPersistent → LaborProductivityWeak
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("WageInflationPersistent", "RealWageGrowthPositive",  prior=0.60,
                  label="wage growth → real purchasing power gains"),
            _edge("RealWageGrowthPositive",  "TightLaborMarket",         prior=0.60,
                  label="real wage gains → workers stay employed"),
            _edge("WageInflationPersistent", "LaborProductivityWeak",   prior=0.55,
                  label="wage cost pressure → firms cut investment"),
        ],
        description="H4: wage_price_spiral",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct layoff → unemployment linkage is structural.

        LayoffCycleBeginning → UnemploymentRising
        TightLaborMarket → WageInflationPersistent
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("LayoffCycleBeginning",    "UnemploymentRising",      prior=0.55,
                  label="layoffs → unemployment (baseline)"),
            _edge("TightLaborMarket",         "WageInflationPersistent", prior=0.55,
                  label="tight market → wages (baseline)"),
        ],
        description="T_null: layoff-unemployment baseline",
    )


class LaborMarketV1:
    """Domain module for the labor market regime ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_labor_tightening_candidate(self._MODULE_ID),
            make_layoff_cycle_candidate(self._MODULE_ID),
            make_structural_shift_candidate(self._MODULE_ID),
            make_wage_price_spiral_candidate(self._MODULE_ID),
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
