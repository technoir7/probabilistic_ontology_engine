"""
CryptoRegimePipeline — CoinGecko + yfinance + FRED observations → EvidenceRecords.

Variable calibrations (all SOFT_OBSERVED, sigmoid-based)
----------------------------------------------------------
BTCMomentumPositive
    Signal  : BTC 13-week return z-score vs rolling year
    P(True) : sigmoid(z_score)

AltcoinSeasonActive
    Signal  : -(btc_dominance - 52.0) / 5.0  (or ETH/BTC ratio z-score)
    P(True) : sigmoid(signal)  [low dominance = alts winning]

OnChainActivityElevated
    Signal  : BTC 30-day avg volume z-score vs full year
    P(True) : sigmoid(z_score)

StablecoinFlowPositive
    Signal  : (usdt+usdc mcap[-1]) / (usdt+usdc mcap[-28]) - 1, z-scored
    P(True) : sigmoid(z_score)

CryptoVolatilityShock
    Signal  : BTC log-return 28-day std z-scored vs full year
    P(True) : sigmoid(z_score)

RiskAssetCorrelation
    Signal  : BTC-USD / QQQ 91-day return correlation z-score
    P(True) : sigmoid(z_score)

NarrativeMomentum
    Signal  : ETH/BTC price ratio z-score over 365 days
    P(True) : sigmoid(z_score)

DollarDebasementNarrative
    Signal  : (-DEXUSEU_zscore + GLD_13w_return_zscore) / 2
    P(True) : sigmoid(composite)
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import numpy as np

from ....engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)
from ..domain import get_variables
from .coingecko_client import CoinGeckoClient, CGObs, CGGlobal
from .yfinance_client import CryptoYFinanceClient, CryptoYFObs
from .fred_client import FREDClient, FREDObservation

logger = logging.getLogger(__name__)

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99


@dataclass
class CryptoRegimeSnapshot:
    """Derived signals and soft probabilities for one evidence week."""

    # Soft probabilities
    p_btc_momentum_positive: float = 0.5
    p_altcoin_season_active: float = 0.5
    p_onchain_activity_elevated: float = 0.5
    p_stablecoin_flow_positive: float = 0.5
    p_crypto_volatility_shock: float = 0.5
    p_risk_asset_correlation: float = 0.5
    p_narrative_momentum: float = 0.5
    p_dollar_debasement_narrative: float = 0.5

    # Hard MAP booleans
    btc_momentum_positive: bool = False
    altcoin_season_active: bool = False
    onchain_activity_elevated: bool = False
    stablecoin_flow_positive: bool = False
    crypto_volatility_shock: bool = False
    risk_asset_correlation: bool = False
    narrative_momentum: bool = False
    dollar_debasement_narrative: bool = False

    # Data confidence per variable
    confidence: dict[str, float] = field(default_factory=dict)

    target_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _soft_bool(signal: float) -> float:
    return max(_CLAMP_LO, min(_CLAMP_HI, _sigmoid(signal)))


def _zscore(current: float, values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    arr = np.array(values, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    if sigma < 1e-9:
        return 0.0
    return (current - mu) / sigma


# ---------------------------------------------------------------------------
# Per-variable signal computation
# ---------------------------------------------------------------------------

def _compute_btc_momentum(btc_obs: list[CGObs]) -> tuple[Optional[float], float]:
    """BTC 13-week return z-score vs rolling year of 13w returns."""
    prices = [o.price_usd for o in btc_obs]
    if len(prices) < 91:
        return None, 0.5

    # Compute rolling 13w returns for z-score
    returns: list[float] = []
    for i in range(len(prices) - 90):
        if prices[i + 90] > 0:
            r = prices[i] / prices[i + 90] - 1.0
            returns.append(r)

    if not returns:
        return None, 0.5

    current_return = returns[0]
    return _zscore(current_return, returns), 1.0


def _compute_altcoin_season(
    global_data: Optional[CGGlobal],
    eth_obs: list[CGObs],
    btc_obs: list[CGObs],
) -> tuple[Optional[float], float]:
    """
    AltcoinSeasonActive: low BTC dominance → alts winning.

    Primary: -(btc_dominance - 52.0) / 5.0 from /global endpoint.
    Fallback: ETH/BTC price ratio z-score.
    """
    if global_data is not None:
        # Direct dominance signal (52% is historical mean, 5% is approx std)
        signal = -(global_data.btc_dominance_pct - 52.0) / 5.0
        return signal, 1.0

    # Fallback: ETH/BTC ratio
    eth_prices = [o.price_usd for o in eth_obs]
    btc_prices = [o.price_usd for o in btc_obs]
    min_len = min(len(eth_prices), len(btc_prices))
    if min_len < 10:
        return None, 0.5

    ratios = [
        eth_prices[i] / btc_prices[i]
        for i in range(min_len)
        if btc_prices[i] > 0
    ]
    if len(ratios) < 10:
        return None, 0.5

    current_ratio = ratios[0]
    return _zscore(current_ratio, ratios), 0.7


def _compute_onchain_activity(btc_obs: list[CGObs]) -> tuple[Optional[float], float]:
    """BTC 30-day avg volume z-score vs full year."""
    if len(btc_obs) < 30:
        return None, 0.5

    volumes = [o.volume_usd for o in btc_obs]
    recent_30 = volumes[:30]
    full_year = volumes

    if not any(v > 0 for v in recent_30):
        return None, 0.5

    # Compute monthly averages in windows to have a distribution for z-scoring
    monthly_avgs: list[float] = []
    step = 30
    for i in range(0, len(full_year) - step + 1, step):
        window = full_year[i:i + step]
        if window:
            monthly_avgs.append(float(np.mean(window)))

    if len(monthly_avgs) < 2:
        # Simple threshold: current 30d avg vs full avg
        current_avg = float(np.mean(recent_30))
        full_avg = float(np.mean(full_year))
        if full_avg > 0:
            signal = (current_avg / full_avg - 1.0) * 3.0
            return signal, 0.7
        return None, 0.5

    current_avg = float(np.mean(recent_30))
    return _zscore(current_avg, monthly_avgs), 1.0


def _compute_stablecoin_flow(
    usdt_obs: list[CGObs],
    usdc_obs: list[CGObs],
) -> tuple[Optional[float], float]:
    """(USDT+USDC mcap) 4-week growth z-scored vs history of monthly changes."""
    # Align by date
    usdt_by_date = {o.obs_date: o.market_cap_usd for o in usdt_obs}
    usdc_by_date = {o.obs_date: o.market_cap_usd for o in usdc_obs}

    all_dates = sorted(set(usdt_by_date) | set(usdc_by_date), reverse=True)
    if len(all_dates) < 28:
        return None, 0.5

    combined: list[float] = []
    for d in all_dates:
        usdt_val = usdt_by_date.get(d, 0.0)
        usdc_val = usdc_by_date.get(d, 0.0)
        combined.append(usdt_val + usdc_val)

    if len(combined) < 28:
        return None, 0.5

    # 4-week change
    recent = combined[0]
    four_weeks_ago = combined[min(27, len(combined) - 1)]
    if four_weeks_ago <= 0:
        return None, 0.5

    # Compute historical monthly changes for z-score
    monthly_changes: list[float] = []
    for i in range(len(combined) - 28):
        if combined[i + 28] > 0:
            ch = combined[i] / combined[i + 28] - 1.0
            monthly_changes.append(ch)

    current_change = recent / four_weeks_ago - 1.0

    if len(monthly_changes) < 2:
        return current_change * 10.0, 0.7

    return _zscore(current_change, monthly_changes), 1.0


def _compute_crypto_volatility(btc_obs: list[CGObs]) -> tuple[Optional[float], float]:
    """BTC 28-day log-return std z-scored vs full year distribution."""
    prices = [o.price_usd for o in btc_obs]
    if len(prices) < 30:
        return None, 0.5

    # Daily log returns
    log_rets: list[float] = []
    for i in range(len(prices) - 1):
        if prices[i] > 0 and prices[i + 1] > 0:
            log_rets.append(math.log(prices[i] / prices[i + 1]))

    if len(log_rets) < 28:
        return None, 0.5

    # Rolling 28-day volatility windows
    vol_windows: list[float] = []
    for i in range(len(log_rets) - 27):
        window = log_rets[i:i + 28]
        if len(window) >= 2:
            vol_windows.append(float(np.std(window, ddof=1)))

    if len(vol_windows) < 2:
        return None, 0.5

    current_vol = vol_windows[0]
    return _zscore(current_vol, vol_windows), 1.0


def _compute_risk_asset_correlation(
    btc_yf: list[CryptoYFObs],
    qqq_yf: list[CryptoYFObs],
) -> tuple[Optional[float], float]:
    """Pearson correlation of BTC-USD and QQQ 91-day returns, z-scored vs rolling year."""
    if len(btc_yf) < 91 or len(qqq_yf) < 91:
        return None, 0.5

    # Align by date
    btc_by_date = {o.obs_date: o.close_price for o in btc_yf}
    qqq_by_date = {o.obs_date: o.close_price for o in qqq_yf}
    common_dates = sorted(set(btc_by_date) & set(qqq_by_date), reverse=True)

    if len(common_dates) < 91:
        return None, 0.5

    # BTC and QQQ daily returns aligned
    btc_prices = [btc_by_date[d] for d in common_dates]
    qqq_prices = [qqq_by_date[d] for d in common_dates]

    def _daily_returns(prices: list[float]) -> list[float]:
        return [
            prices[i] / prices[i + 1] - 1.0
            for i in range(len(prices) - 1)
            if prices[i + 1] > 0
        ]

    btc_rets = _daily_returns(btc_prices)
    qqq_rets = _daily_returns(qqq_prices)
    min_len = min(len(btc_rets), len(qqq_rets))

    if min_len < 90:
        return None, 0.5

    # Rolling 91-day correlations
    correlations: list[float] = []
    for i in range(min_len - 90):
        b = np.array(btc_rets[i:i + 91])
        q = np.array(qqq_rets[i:i + 91])
        if len(b) >= 2 and np.std(b) > 1e-9 and np.std(q) > 1e-9:
            corr = float(np.corrcoef(b, q)[0, 1])
            if not math.isnan(corr):
                correlations.append(corr)

    if len(correlations) < 2:
        return None, 0.5

    current_corr = correlations[0]
    return _zscore(current_corr, correlations), 1.0


def _compute_narrative_momentum(
    eth_obs: list[CGObs],
    btc_obs: list[CGObs],
) -> tuple[Optional[float], float]:
    """ETH/BTC price ratio z-score over 365 days."""
    eth_prices = [o.price_usd for o in eth_obs]
    btc_prices = [o.price_usd for o in btc_obs]
    min_len = min(len(eth_prices), len(btc_prices))

    if min_len < 30:
        return None, 0.5

    ratios = [
        eth_prices[i] / btc_prices[i]
        for i in range(min_len)
        if btc_prices[i] > 0
    ]

    if len(ratios) < 30:
        return None, 0.5

    current_ratio = ratios[0]
    return _zscore(current_ratio, ratios), 1.0


def _compute_dollar_debasement(
    fred_data: dict,
    gld_yf: list[CryptoYFObs],
) -> tuple[Optional[float], float]:
    """(-DEXUSEU_zscore + GLD_13w_return_zscore) / 2 composite."""
    dexuseu_obs = fred_data.get("DEXUSEU", [])

    dex_signal = 0.0
    dex_conf = 0.0
    if len(dexuseu_obs) >= 52:
        current = dexuseu_obs[0].value
        values = [o.value for o in dexuseu_obs[:260]]
        z = _zscore(current, values)
        dex_signal = -z  # inverted: falling USD → positive signal
        dex_conf = 1.0

    gld_signal = 0.0
    gld_conf = 0.0
    gld_prices = [o.close_price for o in gld_yf]
    if len(gld_prices) >= 91:
        # GLD 13-week return z-score
        gld_rets: list[float] = []
        for i in range(len(gld_prices) - 90):
            if gld_prices[i + 90] > 0:
                r = gld_prices[i] / gld_prices[i + 90] - 1.0
                gld_rets.append(r)
        if len(gld_rets) >= 2:
            gld_signal = _zscore(gld_rets[0], gld_rets)
            gld_conf = 1.0

    if dex_conf == 0.0 and gld_conf == 0.0:
        return None, 0.5

    weights = dex_conf + gld_conf
    if weights == 0:
        return None, 0.5

    composite = (dex_signal * dex_conf + gld_signal * gld_conf) / weights
    conf = max(dex_conf, gld_conf)
    return composite, conf


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def compute_snapshot(
    cg_data: dict,
    yf_data: dict,
    fred_data: dict,
    target_date: date,
) -> CryptoRegimeSnapshot:
    snap = CryptoRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    btc_obs = cg_data.get("btc", [])
    eth_obs = cg_data.get("eth", [])
    global_data = cg_data.get("global")
    usdt_obs = cg_data.get("usdt", [])
    usdc_obs = cg_data.get("usdc", [])
    btc_yf = yf_data.get("BTC-USD", [])
    qqq_yf = yf_data.get("QQQ", [])
    gld_yf = yf_data.get("GLD", [])

    # BTCMomentumPositive
    sig, conf = _compute_btc_momentum(btc_obs)
    _apply("BTCMomentumPositive", sig, conf, "p_btc_momentum_positive", "btc_momentum_positive")

    # AltcoinSeasonActive
    sig, conf = _compute_altcoin_season(global_data, eth_obs, btc_obs)
    _apply("AltcoinSeasonActive", sig, conf, "p_altcoin_season_active", "altcoin_season_active")

    # OnChainActivityElevated
    sig, conf = _compute_onchain_activity(btc_obs)
    _apply("OnChainActivityElevated", sig, conf, "p_onchain_activity_elevated", "onchain_activity_elevated")

    # StablecoinFlowPositive
    sig, conf = _compute_stablecoin_flow(usdt_obs, usdc_obs)
    _apply("StablecoinFlowPositive", sig, conf, "p_stablecoin_flow_positive", "stablecoin_flow_positive")

    # CryptoVolatilityShock
    sig, conf = _compute_crypto_volatility(btc_obs)
    _apply("CryptoVolatilityShock", sig, conf, "p_crypto_volatility_shock", "crypto_volatility_shock")

    # RiskAssetCorrelation
    sig, conf = _compute_risk_asset_correlation(btc_yf, qqq_yf)
    _apply("RiskAssetCorrelation", sig, conf, "p_risk_asset_correlation", "risk_asset_correlation")

    # NarrativeMomentum
    sig, conf = _compute_narrative_momentum(eth_obs, btc_obs)
    _apply("NarrativeMomentum", sig, conf, "p_narrative_momentum", "narrative_momentum")

    # DollarDebasementNarrative
    sig, conf = _compute_dollar_debasement(fred_data, gld_yf)
    _apply("DollarDebasementNarrative", sig, conf, "p_dollar_debasement_narrative", "dollar_debasement_narrative")

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class CryptoRegimePipeline:
    """Fetches CoinGecko + yfinance + FRED and builds EvidenceRecords for crypto-regime-v1."""

    def __init__(
        self,
        cg: CoinGeckoClient,
        yf: CryptoYFinanceClient,
        fred: FREDClient,
    ) -> None:
        self._cg = cg
        self._yf = yf
        self._fred = fred

    async def fetch_evidence(
        self,
        target_date: Optional[date] = None,
    ) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()

        import asyncio
        cg_data, yf_data, fred_data = await asyncio.gather(
            self._cg.fetch_all(end_date=target_date),
            self._yf.fetch_all(end_date=target_date),
            self._fred.fetch_all_series(end_date=target_date),
        )

        snapshot = compute_snapshot(cg_data, yf_data, fred_data, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: CryptoRegimeSnapshot) -> EvidenceRecord:
        variables = get_variables()
        conf = snapshot.confidence

        def _assignment(var_name: str, observed_value: bool, p_true: float) -> ObservedAssignment:
            c = conf.get(var_name, 1.0)
            return ObservedAssignment(
                variable_id=variables[var_name].variable_id,
                observed_value=observed_value,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=c,
                probabilities={True: p_true, False: 1.0 - p_true},
            )

        assignments = [
            _assignment("BTCMomentumPositive",      snapshot.btc_momentum_positive,      snapshot.p_btc_momentum_positive),
            _assignment("AltcoinSeasonActive",       snapshot.altcoin_season_active,       snapshot.p_altcoin_season_active),
            _assignment("OnChainActivityElevated",   snapshot.onchain_activity_elevated,   snapshot.p_onchain_activity_elevated),
            _assignment("StablecoinFlowPositive",    snapshot.stablecoin_flow_positive,    snapshot.p_stablecoin_flow_positive),
            _assignment("CryptoVolatilityShock",     snapshot.crypto_volatility_shock,     snapshot.p_crypto_volatility_shock),
            _assignment("RiskAssetCorrelation",      snapshot.risk_asset_correlation,      snapshot.p_risk_asset_correlation),
            _assignment("NarrativeMomentum",         snapshot.narrative_momentum,          snapshot.p_narrative_momentum),
            _assignment("DollarDebasementNarrative", snapshot.dollar_debasement_narrative, snapshot.p_dollar_debasement_narrative),
        ]

        target_date = snapshot.target_date or datetime.now(timezone.utc).date()
        ts = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
        overall_conf = float(sum(conf.values()) / len(conf)) if conf else 1.0

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=ts,
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                "CoinGecko:BTC+ETH+USDT+USDC"
                "|yfinance:BTC-USD+QQQ+GLD"
                f"|FRED:DEXUSEU@week-ending-{target_date}"
            ),
            confidence=overall_conf,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_friday(as_of: Optional[date] = None) -> date:
    today = as_of or datetime.now(timezone.utc).date()
    days_since_friday = (today.weekday() - 4) % 7
    return today - timedelta(days=days_since_friday)


def _weekly_backfill_dates(backfill_weeks: int, today: date) -> list[date]:
    fridays: set[date] = set()
    for delta in range(backfill_weeks * 7, 0, -1):
        d = today - timedelta(days=delta)
        if d.weekday() == 4:
            fridays.add(d)
    return sorted(fridays)
