"""
crypto-regime-v1 — Crypto market regime domain.

Purpose
-------
Tracks evolving causal narratives around cryptocurrency market regimes:
BTC momentum, altcoin season dynamics, on-chain activity, stablecoin flows,
volatility shocks, risk asset correlation, narrative momentum, and dollar
debasement themes.

Variables (all BOOLEAN)
-----------------------
BTCMomentumPositive
    True  = CoinGecko BTC 13-week return z-score > 0
    Signal: rising BTC driven by liquidity/demand

AltcoinSeasonActive
    True  = BTC dominance low (alts outperforming) or ETH/BTC ratio rising
    Signal: capital rotating from BTC to altcoins

OnChainActivityElevated
    True  = BTC 30-day volume z-score > historical mean
    Signal: rising on-chain engagement

StablecoinFlowPositive
    True  = USDT+USDC market cap 4-week growth positive z-score
    Signal: new fiat entering crypto ecosystem

CryptoVolatilityShock
    True  = BTC 4-week realized vol z-score elevated
    Signal: abnormal volatility event

RiskAssetCorrelation
    True  = BTC-USD / QQQ return correlation elevated z-score
    Signal: crypto moving with risk-on equities

NarrativeMomentum
    True  = ETH/BTC ratio rising (positive z-score)
    Signal: speculative/DeFi narratives gaining traction

DollarDebasementNarrative
    True  = USD weakening + gold rising composite z-score positive
    Signal: macro macro-driven crypto demand narrative

Seeds
-----
H1 liquidity_overflow: RiskAssetCorrelation → BTCMomentumPositive → AltcoinSeasonActive
H2 digital_gold: DollarDebasementNarrative → BTCMomentumPositive → StablecoinFlowPositive
H3 speculative_mania: CryptoVolatilityShock → AltcoinSeasonActive → NarrativeMomentum
H4 utility_adoption: OnChainActivityElevated → NarrativeMomentum → AltcoinSeasonActive
T_null: BTCMomentumPositive → AltcoinSeasonActive

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

_MODULE_ID = "crypto-regime-v1"

# ---------------------------------------------------------------------------
# Canonical variable definitions
# ---------------------------------------------------------------------------

_VAR_NAMES = [
    "BTCMomentumPositive",
    "AltcoinSeasonActive",
    "OnChainActivityElevated",
    "StablecoinFlowPositive",
    "CryptoVolatilityShock",
    "RiskAssetCorrelation",
    "NarrativeMomentum",
    "DollarDebasementNarrative",
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
    """Return the shared canonical variable set for crypto-regime-v1."""
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

def make_liquidity_overflow_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H1: liquidity_overflow — Risk-on liquidity spills into crypto.

    Hypothesis: When risk assets (equities) are correlated with BTC and rising,
    excess liquidity overflows into crypto, driving BTC momentum which then
    triggers altcoin rotation.

        RiskAssetCorrelation → BTCMomentumPositive
        BTCMomentumPositive → AltcoinSeasonActive
        StablecoinFlowPositive → BTCMomentumPositive
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("RiskAssetCorrelation", "BTCMomentumPositive", prior=0.65,
                  label="risk-on correlation → BTC momentum"),
            _edge("BTCMomentumPositive", "AltcoinSeasonActive", prior=0.60,
                  label="BTC momentum → altcoin rotation"),
            _edge("StablecoinFlowPositive", "BTCMomentumPositive", prior=0.60,
                  label="stablecoin inflows → BTC momentum"),
        ],
        description="H1: liquidity_overflow",
    )


def make_digital_gold_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H2: digital_gold — Dollar debasement drives BTC as store of value.

    Hypothesis: USD weakening and gold appreciation create a macro narrative
    that drives BTC demand as a store of value, which then attracts stablecoin
    inflows as capital de-risks within crypto.

        DollarDebasementNarrative → BTCMomentumPositive
        BTCMomentumPositive → StablecoinFlowPositive
        DollarDebasementNarrative → RiskAssetCorrelation
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("DollarDebasementNarrative", "BTCMomentumPositive", prior=0.65,
                  label="USD weak + gold up → BTC store-of-value demand"),
            _edge("BTCMomentumPositive", "StablecoinFlowPositive", prior=0.60,
                  label="BTC momentum → stablecoin inflows for dry powder"),
            _edge("DollarDebasementNarrative", "RiskAssetCorrelation", prior=0.60,
                  label="macro debasement → risk-on correlation"),
        ],
        description="H2: digital_gold",
    )


def make_speculative_mania_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H3: speculative_mania — Volatility shock triggers narrative-driven altcoin season.

    Hypothesis: A volatility shock (positive or negative) triggers fear/greed
    cycles that feed speculative narratives, which then drive altcoin season
    as retail capital chases high-beta assets.

        CryptoVolatilityShock → AltcoinSeasonActive
        AltcoinSeasonActive → NarrativeMomentum
        OnChainActivityElevated → CryptoVolatilityShock
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("CryptoVolatilityShock", "AltcoinSeasonActive", prior=0.65,
                  label="volatility shock → speculative altcoin rotation"),
            _edge("AltcoinSeasonActive", "NarrativeMomentum", prior=0.65,
                  label="altcoin season → ETH/DeFi narrative momentum"),
            _edge("OnChainActivityElevated", "CryptoVolatilityShock", prior=0.60,
                  label="elevated on-chain activity → volatility"),
        ],
        description="H3: speculative_mania",
    )


def make_utility_adoption_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    H4: utility_adoption — On-chain activity drives narrative and altcoin uptake.

    Hypothesis: Growing on-chain activity represents real utility adoption,
    which drives ETH/DeFi narratives and subsequently pulls capital into
    altcoins as users discover the broader ecosystem.

        OnChainActivityElevated → NarrativeMomentum
        NarrativeMomentum → AltcoinSeasonActive
        StablecoinFlowPositive → OnChainActivityElevated
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("OnChainActivityElevated", "NarrativeMomentum", prior=0.65,
                  label="on-chain activity → DeFi/ETH narrative momentum"),
            _edge("NarrativeMomentum", "AltcoinSeasonActive", prior=0.65,
                  label="narrative momentum → altcoin season"),
            _edge("StablecoinFlowPositive", "OnChainActivityElevated", prior=0.60,
                  label="stablecoin inflows → on-chain activity"),
        ],
        description="H4: utility_adoption",
    )


def make_null_candidate(module_id: str = _MODULE_ID) -> OntologyCandidate:
    """
    T_null — Baseline: only direct BTC→altcoin linkage is structural.

    Hypothesis: All crypto signals are noise except the direct relationship
    between BTC momentum and altcoin season.

        BTCMomentumPositive → AltcoinSeasonActive
    """
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=_var_list(),
        edges=[
            _edge("BTCMomentumPositive", "AltcoinSeasonActive", prior=0.55,
                  label="BTC momentum → altcoin season (baseline)"),
        ],
        description="T_null: btc-altcoin baseline",
    )


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class CryptoRegimeV1:
    """Domain module for the crypto regime ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_liquidity_overflow_candidate(self._MODULE_ID),
            make_digital_gold_candidate(self._MODULE_ID),
            make_speculative_mania_candidate(self._MODULE_ID),
            make_utility_adoption_candidate(self._MODULE_ID),
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
