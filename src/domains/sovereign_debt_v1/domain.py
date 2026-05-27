"""
sovereign-debt-v1 — Sovereign debt stress and global liquidity domain.

Purpose
-------
Tracks evolving causal narratives around U.S. Treasury yields, sovereign
credit risk, dollar dominance dynamics, Fed balance-sheet policy, and
emerging-market stress.  Competing hypotheses represent distinct transmission
channels from fiscal/monetary policy to global credit conditions.

Variables (all BOOLEAN)
-----------------------
USYieldSpiking
    True  = DGS10 13-week z-score >= +1.0 (yields rising fast vs history)
    False = yields stable or falling
    Signal: rising long-end rates driven by term premium / fiscal concerns

SpreadWidening
    True  = BAMLH0A0HYM2 (HY OAS) z-score >= +1.0
    False = credit spreads at or below historical mean
    Signal: credit markets pricing elevated default/liquidity risk

DollarStrengthening
    True  = DEXUSEU below its 52-week mean (USD strengthening vs EUR)
    False = dollar stable or weakening
    Signal: capital flight to USD safety; often accompanies EM stress

FedBalanceSheetShrinking
    True  = WALCL 13-week change is negative (active QT)
    False = balance sheet stable or expanding
    Signal: Fed actively withdrawing liquidity from the financial system

EMStressElevated
    True  = DTWEXBGS (broad trade-weighted dollar) z-score >= +1.0
    False = broad dollar within historical range
    Signal: strong broad dollar → EM debt servicing pressure and capital outflows

FiscalDominanceRisk
    True  = GFDEBTN (federal debt) YoY growth rate above historical mean
    False = debt growth within historical norms
    Signal: fiscal pressure overwhelming monetary policy independence

CreditDefaultRisk
    True  = BAMLH0A0HYM2 level > 6.0% (absolute stress threshold)
    False = HY OAS below systemic stress level
    Signal: market pricing high corporate default probability

GlobalLiquidityContracting
    True  = WALCL 13w change + M2SL 3m change both negative (dual contraction)
    False = at least one liquidity measure stable or expanding
    Signal: simultaneous Fed and broad-money contraction → global tightening

Seed ontologies (4 competing hypotheses)
-----------------------------------------
H1: us_fiscal_stress
    USYieldSpiking → FiscalDominanceRisk → SpreadWidening

H2: dollar_dominance_erosion
    DollarStrengthening → EMStressElevated → SpreadWidening

H3: em_contagion
    EMStressElevated → CreditDefaultRisk → SpreadWidening

H4: global_liquidity_crunch
    GlobalLiquidityContracting → USYieldSpiking → FiscalDominanceRisk

FRED series used
----------------
DGS10         (daily)     — USYieldSpiking
BAMLH0A0HYM2  (daily)     — SpreadWidening, CreditDefaultRisk
DEXUSEU       (daily)     — DollarStrengthening
WALCL         (weekly)    — FedBalanceSheetShrinking, GlobalLiquidityContracting
DTWEXBGS      (weekly)    — EMStressElevated
GFDEBTN       (quarterly) — FiscalDominanceRisk
M2SL          (monthly)   — GlobalLiquidityContracting

Cadence: WEEKLY (every Monday at 09:00 UTC)
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

_MODULE_ID = "sovereign-debt-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "USYieldSpiking",
    "SpreadWidening",
    "DollarStrengthening",
    "FedBalanceSheetShrinking",
    "EMStressElevated",
    "FiscalDominanceRisk",
    "CreditDefaultRisk",
    "GlobalLiquidityContracting",
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
    """Return the shared canonical variable set for sovereign-debt-v1."""
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

def make_us_fiscal_stress_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: us_fiscal_stress — Fiscal deterioration drives yields and spreads.

    Hypothesis: Rising U.S. long-end yields signal fiscal dominance risk.
    Bond markets price in unsustainable debt trajectories, which then widens
    credit spreads as investors demand a premium for correlated sovereign risk.

        USYieldSpiking → FiscalDominanceRisk
        FiscalDominanceRisk → SpreadWidening
        FedBalanceSheetShrinking → USYieldSpiking
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("USYieldSpiking",        "FiscalDominanceRisk",      prior=0.70,
                  label="yield spike → fiscal dominance concern"),
            _edge("FiscalDominanceRisk",   "SpreadWidening",            prior=0.65,
                  label="fiscal risk → credit spread widening"),
            _edge("FedBalanceSheetShrinking", "USYieldSpiking",         prior=0.65,
                  label="QT → term premium → yield spike"),
        ],
        description="H1: us_fiscal_stress",
    )


def make_dollar_dominance_erosion_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: dollar_dominance_erosion — Dollar strength propagates to EM stress.

    Hypothesis: Dollar strengthening (capital flight to USD) creates EM
    debt-servicing pressure that eventually widens global credit spreads.
    A strengthening dollar is both cause and symptom of risk-off dynamics.

        DollarStrengthening → EMStressElevated
        EMStressElevated → SpreadWidening
        FedBalanceSheetShrinking → DollarStrengthening
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("DollarStrengthening",   "EMStressElevated",          prior=0.70,
                  label="strong USD → EM capital outflows"),
            _edge("EMStressElevated",      "SpreadWidening",             prior=0.65,
                  label="EM stress → global spread widening"),
            _edge("FedBalanceSheetShrinking", "DollarStrengthening",    prior=0.60,
                  label="QT → dollar appreciation"),
        ],
        description="H2: dollar_dominance_erosion",
    )


def make_em_contagion_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: em_contagion — EM stress transmits to DM credit markets.

    Hypothesis: Elevated EM stress (proxied by broad dollar index) feeds
    through to corporate default risk as global growth deteriorates and
    leveraged balance sheets come under pressure.

        EMStressElevated → CreditDefaultRisk
        CreditDefaultRisk → SpreadWidening
        USYieldSpiking → EMStressElevated
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("EMStressElevated",      "CreditDefaultRisk",          prior=0.65,
                  label="EM stress → corporate default risk"),
            _edge("CreditDefaultRisk",     "SpreadWidening",              prior=0.70,
                  label="default risk → HY spread widening"),
            _edge("USYieldSpiking",        "EMStressElevated",            prior=0.60,
                  label="UST yield spike → USD drain → EM stress"),
        ],
        description="H3: em_contagion",
    )


def make_global_liquidity_crunch_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: global_liquidity_crunch — Dual monetary contraction cascade.

    Hypothesis: Simultaneous Fed balance-sheet contraction and M2 deceleration
    represents a global liquidity crunch that forces UST yields up through
    reduced demand, heightening fiscal dominance risk.

        GlobalLiquidityContracting → USYieldSpiking
        USYieldSpiking → FiscalDominanceRisk
        GlobalLiquidityContracting → DollarStrengthening
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("GlobalLiquidityContracting", "USYieldSpiking",        prior=0.65,
                  label="global liquidity drain → UST yield pressure"),
            _edge("USYieldSpiking",              "FiscalDominanceRisk",   prior=0.60,
                  label="yield spike → fiscal dominance concern"),
            _edge("GlobalLiquidityContracting", "DollarStrengthening",   prior=0.60,
                  label="liquidity crunch → safe-haven dollar demand"),
        ],
        description="H4: global_liquidity_crunch",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct credit/spread linkage is structural.

    Hypothesis: All sovereign debt signals are noise except the direct
    relationship between credit default risk and spread widening.  Serves
    as the Bayesian null that should be displaced if richer structure is
    supported by evidence.

        CreditDefaultRisk → SpreadWidening
        USYieldSpiking → SpreadWidening
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("CreditDefaultRisk", "SpreadWidening", prior=0.55,
                  label="default risk → spread widening (baseline)"),
            _edge("USYieldSpiking",    "SpreadWidening", prior=0.55,
                  label="yield spike → spread widening (baseline)"),
        ],
        description="T_null: credit-spread baseline",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class SovereignDebtV1:
    """Domain module for the sovereign debt / global liquidity ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_us_fiscal_stress_candidate(self._MODULE_ID),
            make_dollar_dominance_erosion_candidate(self._MODULE_ID),
            make_em_contagion_candidate(self._MODULE_ID),
            make_global_liquidity_crunch_candidate(self._MODULE_ID),
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
