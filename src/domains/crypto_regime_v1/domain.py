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

Cadence: WEEKLY
"""
from __future__ import annotations

from ..sources.structure import boolean_variables, with_lags
from ...engine.schemas import (
    EdgeExistenceThresholdConfig,
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

_VARIABLE_DEFS: dict[str, Variable] = boolean_variables(_MODULE_ID, _VAR_NAMES)


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for crypto-regime-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Domain module class
# ---------------------------------------------------------------------------

class CryptoRegimeV1:
    """Domain module for the crypto regime ontology."""

    _MODULE_ID = _MODULE_ID

    def module_id(self) -> str:
        return self._MODULE_ID

    def variables(self) -> list[Variable]:
        return list(with_lags(self._MODULE_ID, _VARIABLE_DEFS).values())

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.25, 0.75),
        )
