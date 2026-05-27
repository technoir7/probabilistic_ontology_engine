"""
credit-cycle-v1 — Corporate credit cycle domain module.

Purpose
-------
Tracks the evolution of competing causal narratives in the corporate credit
cycle: monetary tightening transmission, default cycle inception, liquidity
withdrawal, and credit normalization.  Variables span HY/IG spreads,
bank lending standards, credit impulse, and refinancing stress.

Variables (all BOOLEAN)
-----------------------
HYSpreadElevated
    True  = BAMLH0A0HYM2 z-score >= +1.0 (HY spreads above historical trend)
    False = spreads within normal range

LeveragedLoanStress
    True  = DRTSCILM z-score >= +1.0 (bank credit tightening / delinquency elevated)
    False = lending conditions normal

CorporateDefaultRisk
    True  = BAMLH0A0HYM2 level > 5.5% (absolute stress threshold)
    False = HY OAS below systemic stress level

CreditImpulseNegative
    True  = TOTCI 3-month growth rate is negative (credit contracting)
    False = credit expanding or stable

BankLendingTightening
    True  = DRTSCILM z-score >= +0.5 (tightening above neutral)
    False = lending standards normal

InvestmentGradeSpread
    True  = BAMLC0A0CM z-score >= +1.0 (IG spreads elevated)
    False = IG spreads within historical range

HighYieldIssuanceFalling
    True  = BAMLH0A0HYM2 3-month momentum is positive (spreads widening = issuance deterred)
    False = spreads tightening or stable (issuance conditions improving)

RefinancingStress
    True  = DGS5 + BAMLH0A0HYM2 composite elevated (refinancing cost above threshold)
    False = refinancing environment manageable

Seed ontologies (4 competing hypotheses)
-----------------------------------------
H1: monetary_tightening_transmission
    BankLendingTightening → LeveragedLoanStress → HYSpreadElevated

H2: default_cycle_beginning
    CorporateDefaultRisk → HYSpreadElevated → InvestmentGradeSpread

H3: liquidity_withdrawal
    CreditImpulseNegative → HYSpreadElevated → RefinancingStress

H4: credit_normalization
    InvestmentGradeSpread → HYSpreadElevated  (weak; spread compression)

FRED series used
----------------
BAMLH0A0HYM2  (daily)   — HYSpreadElevated, CorporateDefaultRisk, HighYieldIssuanceFalling
DRTSCILM      (quarterly)— LeveragedLoanStress, BankLendingTightening
TOTCI         (monthly)  — CreditImpulseNegative
BAMLC0A0CM    (daily)    — InvestmentGradeSpread
DGS5          (daily)    — RefinancingStress (composite with BAMLH0A0HYM2)

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

_MODULE_ID = "credit-cycle-v1"

_VAR_NAMES = [
    "HYSpreadElevated",
    "LeveragedLoanStress",
    "CorporateDefaultRisk",
    "CreditImpulseNegative",
    "BankLendingTightening",
    "InvestmentGradeSpread",
    "HighYieldIssuanceFalling",
    "RefinancingStress",
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


def make_monetary_tightening_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: monetary_tightening_transmission.

    Hypothesis: Bank lending standards tighten first (leading signal), which
    stresses leveraged loan markets, which widens HY spreads.  Tighter
    standards also raise refinancing costs directly.

        BankLendingTightening → LeveragedLoanStress
        LeveragedLoanStress → HYSpreadElevated
        BankLendingTightening → RefinancingStress
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("BankLendingTightening", "LeveragedLoanStress", prior=0.70,
                  label="bank tightening → leveraged loan stress"),
            _edge("LeveragedLoanStress",   "HYSpreadElevated",    prior=0.70,
                  label="leveraged loan stress → HY spread widening"),
            _edge("BankLendingTightening", "RefinancingStress",   prior=0.60,
                  label="bank tightening → higher refinancing cost"),
        ],
        description="H1: monetary_tightening_transmission",
    )


def make_default_cycle_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: default_cycle_beginning.

    Hypothesis: Absolute default risk (HY OAS above systemic threshold)
    drives spread widening which then propagates to investment-grade markets
    as contagion reprices all credit risk.

        CorporateDefaultRisk → HYSpreadElevated
        HYSpreadElevated → InvestmentGradeSpread
        LeveragedLoanStress → CorporateDefaultRisk
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("CorporateDefaultRisk", "HYSpreadElevated",     prior=0.70,
                  label="default risk elevated → HY spreads widen"),
            _edge("HYSpreadElevated",     "InvestmentGradeSpread", prior=0.65,
                  label="HY widening → IG contagion"),
            _edge("LeveragedLoanStress",  "CorporateDefaultRisk",  prior=0.60,
                  label="loan stress → default risk rising"),
        ],
        description="H2: default_cycle_beginning",
    )


def make_liquidity_withdrawal_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: liquidity_withdrawal.

    Hypothesis: Credit impulse (total credit growth) turning negative is the
    primary driver — it widens HY spreads which makes high-yield issuance
    prohibitive and creates refinancing stress for existing borrowers.

        CreditImpulseNegative → HYSpreadElevated
        HYSpreadElevated → HighYieldIssuanceFalling
        HYSpreadElevated → RefinancingStress
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("CreditImpulseNegative",   "HYSpreadElevated",        prior=0.65,
                  label="credit contraction → HY spread widening"),
            _edge("HYSpreadElevated",         "HighYieldIssuanceFalling", prior=0.65,
                  label="high HY spreads → issuance deterred"),
            _edge("HYSpreadElevated",         "RefinancingStress",        prior=0.65,
                  label="HY spread spike → refinancing cost surge"),
        ],
        description="H3: liquidity_withdrawal",
    )


def make_credit_normalization_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: credit_normalization.

    Hypothesis: IG spread movements lead HY as institutional rebalancing
    and risk repricing flows down the quality spectrum.  Weak credit impulse
    is the underlying driver of compression.

        InvestmentGradeSpread → HYSpreadElevated
        CreditImpulseNegative → InvestmentGradeSpread
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("InvestmentGradeSpread", "HYSpreadElevated",     prior=0.55,
                  label="IG widening → HY spread compression reversal"),
            _edge("CreditImpulseNegative", "InvestmentGradeSpread", prior=0.55,
                  label="credit contraction → IG spread widening"),
        ],
        description="H4: credit_normalization",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct default risk → HY spread link is structural.

        CorporateDefaultRisk → HYSpreadElevated
        BankLendingTightening → HYSpreadElevated
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("CorporateDefaultRisk", "HYSpreadElevated",     prior=0.55,
                  label="default risk → HY (baseline)"),
            _edge("BankLendingTightening", "HYSpreadElevated",    prior=0.55,
                  label="bank tightening → HY (baseline)"),
        ],
        description="T_null: direct default-spread baseline",
    )


class CreditCycleV1:
    """Domain module for the credit cycle ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_monetary_tightening_candidate(self._MODULE_ID),
            make_default_cycle_candidate(self._MODULE_ID),
            make_liquidity_withdrawal_candidate(self._MODULE_ID),
            make_credit_normalization_candidate(self._MODULE_ID),
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
