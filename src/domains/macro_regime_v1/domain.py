"""
macro-regime-v1 — Macroeconomic regime domain module.

Purpose
-------
Stress-tests ontology evolution under regime shifts, competing macroeconomic
narratives, noisy heterogeneous evidence, and changing causal relationships.
This domain is NOT a price-prediction engine; it is an evolving probabilistic
ontology over macro-financial regimes.

Variables (all BOOLEAN)
-----------------------
YieldCurveInverted
    True  = 10Y minus 2Y Treasury yield spread (T10Y2Y) is negative (inverted)
    False = spread is positive (normal curve)
    Signal: structural monetary tightening / growth pessimism embedded in rates

InflationShock
    True  = CPI 12-month YoY rate exceeds 3.5% (materially above 2% target)
    False = inflation at or near target
    Signal: supply-side or demand-side inflation pressure creating policy risk

LiquidityStress
    True  = Fed balance sheet (WALCL) contracting over 13 weeks (QT regime)
    False = balance sheet stable or expanding (QE / neutral)
    Signal: active Fed liquidity withdrawal, distinct from rate policy

CreditSpreadStress
    True  = HY OAS spread (BAMLH0A0HYM2) is above its rolling 52-week z-score ≥ 1
    False = HY spreads at or below historical mean
    Signal: credit market pricing elevated default risk / deleveraging pressure

VolatilityShock
    True  = VIX above its rolling 90-day 75th percentile (fear regime)
    False = VIX in normal range
    Signal: equity-implied volatility elevated; systemic risk-off sentiment

DollarStrength
    True  = USD/EUR rate (DEXUSEU) above its 52-week mean by ≥ 0.5 z-score
    False = dollar below recent trend
    Signal: global capital flows favouring dollar; often accompanies risk-off

EquityRiskOn
    True  = UNRATE not rising vs its 12-month mean (labour market resilient)
    False = unemployment trending higher (labour market deteriorating)
    Signal: real-economy demand channel; distinct from volatility and credit

AIRiskOn
    True  = NASDAQ Composite 13-week price return is above its historical mean
            by at least +0.5 standard deviations (tech/growth narrative dominant)
    False = NASDAQ 13-week return is below-average or negative
    Signal: technology / AI narrative driving risk appetite; acts as distinct
            explanatory factor from broad credit/vol signals

Competing ontology templates (seed population)
----------------------------------------------
T_monetary   — monetary transmission chain: IS drives curve → liquidity → credit → equity
T_credit     — credit-first: credit spreads are the primary leading signal
T_ai_boom    — AI productivity narrative: tech momentum drives equity & dollar conditions
T_recession  — recessionary tightening cascade: inflation triggers a full tightening chain
T_null       — null/noise baseline: volatility is the only structural signal

FRED series used
----------------
T10Y2Y        (daily)   — YieldCurveInverted
CPIAUCSL      (monthly) — InflationShock
WALCL         (weekly)  — LiquidityStress
BAMLH0A0HYM2  (daily)   — CreditSpreadStress
VIXCLS        (daily)   — VolatilityShock
DEXUSEU       (daily)   — DollarStrength
UNRATE        (monthly) — EquityRiskOn
NASDAQCOM     (daily)   — AIRiskOn

Cadence: WEEKLY (every Monday at 09:00 UTC using prior week's data)
-------------------------------------------------------------------
Reasoning:
- WALCL publishes weekly (Thursday) — binding constraint
- CPIAUCSL and UNRATE are monthly but update slowly; weekly ingestion still
  reflects their latest readings
- Daily signals (T10Y2Y, VIX, credit spreads, FX) are aggregated to weekly
  medians — reducing noise and preventing high-frequency oversampling
- Macro regime changes operate on weeks-to-months timescales; daily cadence
  would inject noise without increasing informational value
- Weekly cadence produces ~52 evidence records/year — sufficient for the
  ontology learning cycle to detect genuine regime shifts
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

_MODULE_ID = "macro-regime-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions — stable UUIDs via deterministic hashing.
# These IDs must never change; they identify variables across ingestion runs.
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "YieldCurveInverted",
    "InflationShock",
    "LiquidityStress",
    "CreditSpreadStress",
    "VolatilityShock",
    "DollarStrength",
    "EquityRiskOn",
    "AIRiskOn",
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
    """Return the shared canonical variable set for macro-regime-v1."""
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

def make_monetary_chain_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_monetary — Standard monetary transmission chain.

    Hypothesis: Inflation is the root cause. It drives policy tightening
    (yield curve inversion), which drains liquidity, which stresses credit
    markets, which suppresses equity risk appetite.

        InflationShock → YieldCurveInverted
        InflationShock → LiquidityStress
        YieldCurveInverted → CreditSpreadStress
        LiquidityStress → CreditSpreadStress
        CreditSpreadStress → EquityRiskOn
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("InflationShock",      "YieldCurveInverted",  prior=0.70,
                  label="inflation → curve inversion"),
            _edge("InflationShock",      "LiquidityStress",     prior=0.60,
                  label="inflation → Fed tightening"),
            _edge("YieldCurveInverted",  "CreditSpreadStress",  prior=0.65,
                  label="curve inversion → credit stress"),
            _edge("LiquidityStress",     "CreditSpreadStress",  prior=0.65,
                  label="liquidity drain → credit stress"),
            _edge("CreditSpreadStress",  "EquityRiskOn",        prior=0.70,
                  label="credit stress → equity risk-off"),
        ],
        description="T_monetary: inflation-driven tightening chain",
    )


def make_credit_first_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_credit — Credit markets as the primary leading signal.

    Hypothesis: Credit spreads lead all other signals. Dollar strength
    squeezes leveraged finance, causing credit stress, which then propagates
    to volatility and equity risk appetite. Fed liquidity feeds directly into
    credit conditions.

        DollarStrength → CreditSpreadStress
        LiquidityStress → CreditSpreadStress
        CreditSpreadStress → VolatilityShock
        CreditSpreadStress → EquityRiskOn
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("DollarStrength",      "CreditSpreadStress",  prior=0.65,
                  label="dollar squeeze → credit stress"),
            _edge("LiquidityStress",     "CreditSpreadStress",  prior=0.70,
                  label="liquidity drain → credit stress"),
            _edge("CreditSpreadStress",  "VolatilityShock",     prior=0.70,
                  label="credit stress → equity vol"),
            _edge("CreditSpreadStress",  "EquityRiskOn",        prior=0.65,
                  label="credit stress → equity risk-off"),
        ],
        description="T_credit: credit-market-led regime",
    )


def make_ai_boom_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_ai_boom — AI/technology productivity boom narrative.

    Hypothesis: A technology productivity narrative (proxied by NASDAQ
    momentum) is an independent driver of equity risk appetite and capital
    flows. Tech dominance also attracts global capital → dollar strength.
    Strong risk appetite suppresses volatility.

        AIRiskOn → EquityRiskOn
        AIRiskOn → DollarStrength
        EquityRiskOn → VolatilityShock
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("AIRiskOn",       "EquityRiskOn",    prior=0.65,
                  label="tech boom → equity confidence"),
            _edge("AIRiskOn",       "DollarStrength",  prior=0.55,
                  label="tech capital inflows → dollar demand"),
            _edge("EquityRiskOn",   "VolatilityShock", prior=0.60,
                  label="equity appetite ↔ vol regime"),
        ],
        description="T_ai_boom: AI productivity narrative dominant",
    )


def make_recessionary_tightening_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_recession — Recessionary tightening cascade.

    Hypothesis: Persistent inflation causes the Fed to overtighten. This
    drains liquidity, inverts the yield curve, stresses credit, collapses
    equity risk appetite, and ultimately triggers a recessionary signal in
    unemployment. Dollar strengthens as capital seeks safety.

        InflationShock → LiquidityStress
        LiquidityStress → YieldCurveInverted
        YieldCurveInverted → CreditSpreadStress
        CreditSpreadStress → EquityRiskOn
        InflationShock → DollarStrength
        CreditSpreadStress → VolatilityShock
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("InflationShock",     "LiquidityStress",     prior=0.65,
                  label="inflation → Fed responds with QT"),
            _edge("LiquidityStress",    "YieldCurveInverted",  prior=0.60,
                  label="QT → short-end rate rise → inversion"),
            _edge("YieldCurveInverted", "CreditSpreadStress",  prior=0.65,
                  label="inversion → credit concern"),
            _edge("CreditSpreadStress", "EquityRiskOn",        prior=0.70,
                  label="credit stress → risk-off equity"),
            _edge("InflationShock",     "DollarStrength",      prior=0.55,
                  label="inflation premium → dollar demand"),
            _edge("CreditSpreadStress", "VolatilityShock",     prior=0.65,
                  label="credit stress → vol spike"),
        ],
        description="T_recession: recessionary tightening cascade",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Null/noise baseline.

    Hypothesis: Only volatility has a structural link to credit spreads;
    other relationships are noise. This candidate serves as the Bayesian
    null hypothesis and should be pruned if any richer structure is
    supported by evidence.

        VolatilityShock → CreditSpreadStress
        VolatilityShock → EquityRiskOn
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("VolatilityShock", "CreditSpreadStress", prior=0.55,
                  label="vol → credit widening"),
            _edge("VolatilityShock", "EquityRiskOn",       prior=0.55,
                  label="vol → equity risk-off"),
        ],
        description="T_null: volatility-only baseline",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class MacroRegimeV1:
    """
    Domain module for the macro regime ontology.

    Implements the domain module contract defined in SPEC.md §8.
    All five seed candidates encode competing explanatory narratives.
    """
    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_monetary_chain_candidate(self._MODULE_ID),
            make_credit_first_candidate(self._MODULE_ID),
            make_ai_boom_candidate(self._MODULE_ID),
            make_recessionary_tightening_candidate(self._MODULE_ID),
            make_null_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        """
        Wider explore band than agriculture domains.

        Macro regime transitions are slow and noisy; we want the engine to
        maintain genuine uncertainty over edge existence for longer before
        committing. This produces richer ontology competition.
        """
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),  # wider band → more exploration
        )

    def initial_entities(self) -> list:
        return []

    def initial_assertions(self) -> list:
        return []

    def variable_specs(self) -> list:
        return []

    def initial_parameterizations(self) -> list:
        return []
