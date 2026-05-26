"""
ai-regime-v1 — AI investment cycle interpretive ontology domain.

Purpose
-------
Track which causal story best explains the current AI investment cycle.
This is an interpretive analysis domain, not a prediction engine.
The engine discovers its own causal structures; seed ontologies are
scaffolding expected to be displaced by data-driven structures over time.

Variables (all BOOLEAN)
-----------------------
SemiconductorMomentum
    True  = SOX index 13-week return z-score > 0.5 (sustained chip demand)
    False = SOX momentum at or below trend
    Signal: semiconductor sector as the physical infrastructure signal

MarketConcentrationExtreme
    True  = QQQ/RSP (equal-weight S&P) ratio 13-week z-score > 0.5
            (tech outperforming broad market on a concentration basis)
    False = market breadth normal; gains are distributed
    Signal: capital concentration in AI/tech names

HyperscalerCapexAccelerating
    True  = Average YoY capex growth for MSFT/GOOGL/AMZN/META > 20%
    False = capex growth below 20% threshold
    Signal: actual dollars being deployed in AI infrastructure; observable
            from SEC EDGAR 10-Q filings

TechValuationDetached
    True  = QQQ price z-score vs 3-year history > 1.0
            (proxy for elevated P/E vs recent history)
    False = tech valuations within 1σ of recent 3-year range
    Signal: narrative premium; markets pricing in future AI gains that
            have not yet materialised in earnings

IPInvestmentRising
    True  = FRED Y033RC1Q027SBEA 4-quarter growth rate > historical median
    False = IP investment growth below historical median
    Signal: business investment in intellectual property (software, R&D,
            database assets); the productive deployment channel

LaborProductivityImproving
    True  = FRED PRS85006092 (nonfarm business labor productivity) YoY > 2.0%
    False = productivity growth at or below threshold
    Signal: whether AI is actually showing up in measured economic productivity

BroadEconomicLift
    True  = FRED A191RL1Q225SBEA (real GDP growth, annualized) > 2.5%
    False = GDP growth at or below threshold
    Signal: whether the AI cycle is lifting the broad economy

AIRiskPremiumCompressed
    True  = VIX level z-score (inverted) signals VIX below historical average
    False = VIX elevated; risk premium not compressed
    Signal: market-implied risk appetite; compressed risk premium is a
            necessary (not sufficient) condition for sustained AI narrative

Competing ontology templates (seed population — expected to evolve)
--------------------------------------------------------------------
H1: infrastructure_buildout
    Semiconductor demand drives hyperscaler capex → IP investment →
    labour productivity gains.
    Interpretation: rational buildout with real economic grounding.

H2: bubble_detachment
    Valuation detachment leads to concentration, which compresses risk
    premium and detaches price from fundamentals.
    Interpretation: narrative driven, fundamentals not yet delivered.

H3: winner_take_all
    Concentration drives hyperscaler capex, which further lifts valuations.
    Interpretation: concentration is the primary structural dynamic.

H4: productivity_regime
    IP investment → productivity → GDP lift.  Compressed risk premium
    enables further concentration.
    Interpretation: AI gains are already in the real economy.

Data sources
------------
yfinance:
    ^SOX      — SemiconductorMomentum (SOX 13-week return z-score)
    QQQ, RSP  — MarketConcentrationExtreme (QQQ/RSP ratio z-score)
    QQQ       — TechValuationDetached (QQQ price z-score vs 3-year history)
    ^VIX      — AIRiskPremiumCompressed (VIX z-score, inverted)

SEC EDGAR (no key required):
    MSFT (CIK 0000789019)  — HyperscalerCapexAccelerating
    GOOGL (CIK 0001652044) — HyperscalerCapexAccelerating
    AMZN (CIK 0001018724)  — HyperscalerCapexAccelerating
    META (CIK 0001326801)  — HyperscalerCapexAccelerating
    Concept: us-gaap/PaymentsToAcquirePropertyPlantAndEquipment

FRED:
    Y033RC1Q027SBEA  (quarterly) — IPInvestmentRising
    PRS85006092      (quarterly) — LaborProductivityImproving
    A191RL1Q225SBEA  (quarterly) — BroadEconomicLift

Cadence: WEEKLY (every Monday at 09:00 UTC using prior week's data)
-------------------------------------------------------------------
Reasoning:
    - yfinance prices update daily; weekly aggregation reduces noise
    - FRED quarterly series update only quarterly but weekly runs capture
      revisions promptly
    - EDGAR 10-Q filings publish quarterly; EDGAR data is cached 6h
    - AI regime transitions operate on months-to-quarters timescales;
      weekly cadence provides ~52 evidence points/year—sufficient for
      the learning cycle to detect genuine structural shifts
    - Consistent with macro_regime_v1 cadence for cross-domain comparison
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

_MODULE_ID = "ai-regime-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions — stable UUIDs via deterministic hashing.
# These IDs must never change; they identify variables across ingestion runs.
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "SemiconductorMomentum",
    "MarketConcentrationExtreme",
    "HyperscalerCapexAccelerating",
    "TechValuationDetached",
    "IPInvestmentRising",
    "LaborProductivityImproving",
    "BroadEconomicLift",
    "AIRiskPremiumCompressed",
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
    """Return the shared canonical variable set for ai-regime-v1."""
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

def make_infrastructure_buildout_candidate(
    module_id: str = _MODULE_ID,
) -> OntologyCandidate:
    """
    H1 — infrastructure_buildout: rational capex-driven productivity chain.

    Semiconductor momentum is the leading indicator of sustained AI
    infrastructure demand.  It drives hyperscaler capex decisions, which
    flow into measured IP investment, and eventually manifest in labour
    productivity gains.

        SemiconductorMomentum → HyperscalerCapexAccelerating
        HyperscalerCapexAccelerating → IPInvestmentRising
        IPInvestmentRising → LaborProductivityImproving
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge(
                "SemiconductorMomentum",
                "HyperscalerCapexAccelerating",
                prior=0.65,
                label="chip demand → hyperscaler capex",
            ),
            _edge(
                "HyperscalerCapexAccelerating",
                "IPInvestmentRising",
                prior=0.60,
                label="capex → measured IP investment",
            ),
            _edge(
                "IPInvestmentRising",
                "LaborProductivityImproving",
                prior=0.60,
                label="IP investment → labour productivity",
            ),
        ],
        description="H1: infrastructure_buildout — rational capex → productivity chain",
    )


def make_bubble_detachment_candidate(
    module_id: str = _MODULE_ID,
) -> OntologyCandidate:
    """
    H2 — bubble_detachment: narrative driven, fundamentals not yet delivered.

    Semiconductor momentum inflates tech valuations.  Detached valuations
    attract concentrated capital flows into tech, which further compresses
    the risk premium as investors chase narrative returns.  This hypothesis
    is the bearish structural counter-narrative.

        SemiconductorMomentum → TechValuationDetached
        TechValuationDetached → MarketConcentrationExtreme
        MarketConcentrationExtreme → AIRiskPremiumCompressed
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge(
                "SemiconductorMomentum",
                "TechValuationDetached",
                prior=0.65,
                label="chip momentum → valuation expansion",
            ),
            _edge(
                "TechValuationDetached",
                "MarketConcentrationExtreme",
                prior=0.70,
                label="stretched valuations → concentrated flows",
            ),
            _edge(
                "MarketConcentrationExtreme",
                "AIRiskPremiumCompressed",
                prior=0.65,
                label="concentration → compressed risk premium",
            ),
        ],
        description="H2: bubble_detachment — narrative detached from fundamentals",
    )


def make_winner_take_all_candidate(
    module_id: str = _MODULE_ID,
) -> OntologyCandidate:
    """
    H3 — winner_take_all: concentration is the dominant structural dynamic.

    Market concentration in AI names drives hyperscaler capex, as the
    dominant platforms use cheap capital to maintain competitive moats.
    Accelerating capex further validates tech valuations, closing the loop.

        MarketConcentrationExtreme → HyperscalerCapexAccelerating
        HyperscalerCapexAccelerating → TechValuationDetached
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge(
                "MarketConcentrationExtreme",
                "HyperscalerCapexAccelerating",
                prior=0.65,
                label="capital concentration → capex acceleration",
            ),
            _edge(
                "HyperscalerCapexAccelerating",
                "TechValuationDetached",
                prior=0.60,
                label="capex acceleration → valuation premium",
            ),
        ],
        description="H3: winner_take_all — concentration drives capex and valuation",
    )


def make_productivity_regime_candidate(
    module_id: str = _MODULE_ID,
) -> OntologyCandidate:
    """
    H4 — productivity_regime: AI gains visible in the real economy.

    IP investment drives labour productivity, which lifts broad GDP growth.
    A compressed risk premium enables further capital concentration into
    AI sectors.  This hypothesis is the optimistic structural narrative.

        IPInvestmentRising → LaborProductivityImproving
        LaborProductivityImproving → BroadEconomicLift
        AIRiskPremiumCompressed → MarketConcentrationExtreme
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge(
                "IPInvestmentRising",
                "LaborProductivityImproving",
                prior=0.65,
                label="IP investment → productivity gains",
            ),
            _edge(
                "LaborProductivityImproving",
                "BroadEconomicLift",
                prior=0.65,
                label="productivity → GDP lift",
            ),
            _edge(
                "AIRiskPremiumCompressed",
                "MarketConcentrationExtreme",
                prior=0.60,
                label="risk appetite → tech concentration",
            ),
        ],
        description="H4: productivity_regime — AI gains showing up in real economy",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class AIRegimeV1:
    """
    Domain module for the AI investment cycle interpretive ontology.

    Implements the domain module contract defined in SPEC.md §8.
    Four seed candidates encode competing explanatory narratives for
    the current AI investment cycle.

    Explore band: 0.25–0.75 (same as macro_regime_v1).
    Rationale: interpretive macro-financial domains require the engine to
    maintain genuine uncertainty longer before committing; this produces
    richer ontology competition and avoids premature convergence on a
    single narrative before sufficient evidence accumulates.
    """

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_infrastructure_buildout_candidate(self._MODULE_ID),
            make_bubble_detachment_candidate(self._MODULE_ID),
            make_winner_take_all_candidate(self._MODULE_ID),
            make_productivity_regime_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        """
        Wider explore band than agriculture domains.

        AI regime transitions are structural and slow; we want the engine
        to maintain genuine uncertainty over edge existence for longer
        before committing.  Same rationale as macro_regime_v1.
        """
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
