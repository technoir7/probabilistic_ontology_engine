"""
AIRegimePipeline — combines yfinance, FRED, and SEC EDGAR observations
into EvidenceRecords for the ai-regime-v1 domain.

This pipeline owns the mapping from raw API data to domain variable UUIDs.
All three sources are fetched concurrently (yfinance and FRED) or
sequentially with cache (EDGAR).  One EvidenceRecord is produced per
weekly call.

Variable mapping and soft-evidence calibration
----------------------------------------------
All eight Boolean assignments are emitted as SOFT_OBSERVED with
sigmoid-calibrated probability distributions.  The boolean MAP value
is preserved in observed_value for compatibility with upstream callers.

SemiconductorMomentum
    Source  : yfinance ^SOX
    Signal  : z-score of current 13-week (91-day) price return vs
              historical distribution of 13-week returns (2-year window)
    P(True) : sigmoid(z_score − 0.5)
              True threshold at z = 0.5; at z=0.5 P ≈ 0.50 (boundary)
              at z=1.5 P ≈ 0.73; at z=2.5 P ≈ 0.88

MarketConcentrationExtreme
    Source  : yfinance QQQ and RSP
    Signal  : z-score of current 13-week return of QQQ/RSP price ratio
              vs historical distribution of 13-week ratio returns
    P(True) : sigmoid(z_score − 0.5)
              True when tech-cap ETF meaningfully outperforms equal-weight

HyperscalerCapexAccelerating
    Source  : SEC EDGAR (MSFT, GOOGL, AMZN, META)
    Signal  : (avg_yoy_growth_pct − 20.0) / 10.0
              Scale: 10pp around 20% threshold
    P(True) : sigmoid(signal)
              At 20%: P ≈ 0.50; at 30%: P ≈ 0.73; at 10%: P ≈ 0.27

TechValuationDetached
    Source  : yfinance QQQ
    Signal  : z-score of current QQQ price vs 3-year (750-day) price
              history, minus 1.0 (threshold at z = 1.0)
    P(True) : sigmoid(z_score − 1.0)
              At z=1.0: P ≈ 0.50; at z=2.0: P ≈ 0.73; at z=0: P ≈ 0.27
    Rationale: QQQ price elevation vs own 3-year trend is a reasonable
               proxy for stretched P/E, since aggregate earnings grow
               more smoothly than price.

IPInvestmentRising
    Source  : FRED Y033RC1Q027SBEA (quarterly)
    Signal  : (current_4q_growth − median_4q_growth) / max(iqr, 0.5)
              4-quarter growth = (latest / 4q_ago − 1) * 100
    P(True) : sigmoid(signal)
              True when current growth exceeds historical median

LaborProductivityImproving
    Source  : FRED PRS85006092 (quarterly)
    Signal  : (yoy_pct − 2.0) / 0.5
    P(True) : sigmoid(signal)
              At 2.0%: P ≈ 0.50; at 3.0%: P ≈ 0.88; at 1.0%: P ≈ 0.12

BroadEconomicLift
    Source  : FRED A191RL1Q225SBEA (quarterly, already annualised %)
    Signal  : (growth_pct − 2.5) / 0.5
    P(True) : sigmoid(signal)
              At 2.5%: P ≈ 0.50; at 3.5%: P ≈ 0.88; at 1.5%: P ≈ 0.12

AIRiskPremiumCompressed
    Source  : yfinance ^VIX
    Signal  : − z_score of current VIX vs 2-year rolling distribution
              (inverted: low VIX → positive signal → compressed premium)
    P(True) : sigmoid(−z_score)
              At z=0 (VIX at mean): P ≈ 0.50
              At z=−1 (VIX below mean): P ≈ 0.73
              At z=+1 (VIX above mean): P ≈ 0.27

All P(True) values are clamped to [0.01, 0.99].

Cadence
-------
Weekly cadence.  Invoked once per week (Monday 09:00 UTC) using data
from the prior week (observation_end = previous Friday).

EDGAR data is cached 6 hours.  yfinance and FRED calls happen on each run.

Missing data handling
---------------------
If any source returns insufficient data, the affected signal defaults
to 0.0 (→ P = 0.50, maximum uncertainty) and the assignment confidence
is degraded to 0.5.  This prevents hard failures during data outages
while signalling genuine uncertainty to the ontology.
"""
from __future__ import annotations

import asyncio
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
from .edgar_client import EDGARClient, HyperscalerCapexSnapshot
from .fred_client import (
    AI_FETCH_LOOKBACK_DAYS,
    AI_MIN_OBS,
    FREDClient,
    FREDObservation,
)
from .yfinance_client import AIYFinanceClient, YFObservation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Calibration constants
# ---------------------------------------------------------------------------

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99


# ---------------------------------------------------------------------------
# Snapshot dataclass — carries all derived signals
# ---------------------------------------------------------------------------

@dataclass
class AIRegimeSnapshot:
    """
    Derived signals and soft-probability calibrations for one evidence week.

    Each *_signal field is the pre-sigmoid score fed into _soft_bool().
    Each *_p_true field is the calibrated P(True) ∈ [0.01, 0.99].
    Each *_bool field is the hard MAP boolean (observed_value).
    Each *_confidence field reflects data availability (1.0 if complete).
    """

    # Raw signals for diagnostics / logging
    sox_return_zscore: Optional[float] = None
    concentration_ratio_zscore: Optional[float] = None
    capex_avg_yoy_pct: Optional[float] = None
    qqq_valuation_zscore: Optional[float] = None
    ip_investment_signal: Optional[float] = None     # (growth - median) / iqr
    labor_prod_yoy_pct: Optional[float] = None
    gdp_growth_pct: Optional[float] = None
    vix_zscore: Optional[float] = None

    # Derived soft probabilities
    p_semiconductor_momentum: float = 0.5
    p_market_concentration_extreme: float = 0.5
    p_hyperscaler_capex_accelerating: float = 0.5
    p_tech_valuation_detached: float = 0.5
    p_ip_investment_rising: float = 0.5
    p_labor_productivity_improving: float = 0.5
    p_broad_economic_lift: float = 0.5
    p_ai_risk_premium_compressed: float = 0.5

    # Hard MAP booleans
    semiconductor_momentum: bool = False
    market_concentration_extreme: bool = False
    hyperscaler_capex_accelerating: bool = False
    tech_valuation_detached: bool = False
    ip_investment_rising: bool = False
    labor_productivity_improving: bool = False
    broad_economic_lift: bool = False
    ai_risk_premium_compressed: bool = False

    # Data confidence per variable (1.0 = full data, 0.5 = degraded/fallback)
    confidence: dict[str, float] = field(default_factory=dict)

    # Target date for this evidence record
    target_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Sigmoid and soft-bool helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _soft_bool(signal: float) -> float:
    """Convert a signed signal to P(True) via sigmoid, clamped to [0.01, 0.99]."""
    return max(_CLAMP_LO, min(_CLAMP_HI, _sigmoid(signal)))


def _zscore(current: float, values: list[float]) -> float:
    """Rolling z-score: (current − mean) / std.  Returns 0.0 if std ≈ 0."""
    if len(values) < 2:
        return 0.0
    arr = np.array(values, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    if sigma < 1e-9:
        return 0.0
    return (current - mu) / sigma


def _values_from_obs(obs: list[FREDObservation]) -> list[float]:
    return [o.value for o in obs]


def _values_from_yf(obs: list[YFObservation]) -> list[float]:
    return [o.close_price for o in obs]


# ---------------------------------------------------------------------------
# Per-variable signal computation (pure functions, no I/O)
# ---------------------------------------------------------------------------

def _compute_13w_return_zscore(
    obs: list[YFObservation],
    ticker: str,
) -> tuple[Optional[float], float]:
    """
    Compute the z-score of the 13-week (91-day) price return for a ticker.

    Uses 2 years of history to build the return distribution.

    Returns (z_score, confidence).
    """
    if len(obs) < 100:  # need at least 13 weeks + some history
        return None, 0.5

    current_price = obs[0].close_price
    # 13-week lookback ≈ 65 trading days; use 91 calendar days index
    idx_13w = min(65, len(obs) - 1)  # ~65 trading days ≈ 13 calendar weeks
    price_13w_ago = obs[idx_13w].close_price
    if price_13w_ago <= 0:
        return None, 0.5

    current_return = (current_price / price_13w_ago - 1.0) * 100.0

    # Build historical 13-week returns (step weekly ≈ every 5 trading days)
    historical_returns: list[float] = []
    step = 5  # weekly steps in trading days
    max_steps = min(len(obs) - idx_13w - 1, 400)
    for i in range(0, max_steps, step):
        p_now = obs[i].close_price
        p_13w = obs[min(i + idx_13w, len(obs) - 1)].close_price
        if p_13w > 0:
            historical_returns.append((p_now / p_13w - 1.0) * 100.0)

    if len(historical_returns) < 8:
        # Minimal history: rough signal from current return
        signal = current_return / 10.0
        return signal, 0.6

    z = _zscore(current_return, historical_returns)
    confidence = 1.0 if len(historical_returns) >= 20 else 0.8
    return z, confidence


def _compute_concentration_ratio_zscore(
    qqq_obs: list[YFObservation],
    rsp_obs: list[YFObservation],
) -> tuple[Optional[float], float]:
    """
    Compute the z-score of the 13-week return of the QQQ/RSP price ratio.

    High positive z-score = tech is meaningfully outperforming equal-weight.

    Returns (z_score, confidence).
    """
    if len(qqq_obs) < 80 or len(rsp_obs) < 80:
        return None, 0.5

    # Align by date: build date → price dicts and find intersection
    qqq_by_date = {o.obs_date: o.close_price for o in qqq_obs}
    rsp_by_date = {o.obs_date: o.close_price for o in rsp_obs}
    common_dates = sorted(
        set(qqq_by_date.keys()) & set(rsp_by_date.keys()),
        reverse=True,
    )

    if len(common_dates) < 80:
        return None, 0.5

    # Build aligned ratio series (newest first)
    ratios: list[tuple[date, float]] = []
    for d in common_dates:
        rsp_price = rsp_by_date[d]
        if rsp_price <= 0:
            continue
        ratios.append((d, qqq_by_date[d] / rsp_price))

    if len(ratios) < 80:
        return None, 0.5

    # Compute 13-week returns of the ratio
    idx_13w = min(65, len(ratios) - 1)
    current_ratio = ratios[0][1]
    ratio_13w_ago = ratios[idx_13w][1]
    if ratio_13w_ago <= 0:
        return None, 0.5

    current_ratio_return = (current_ratio / ratio_13w_ago - 1.0) * 100.0

    # Historical distribution
    ratio_values = [r for _, r in ratios]
    historical_returns: list[float] = []
    step = 5
    max_steps = min(len(ratios) - idx_13w - 1, 400)
    for i in range(0, max_steps, step):
        r_now = ratio_values[i]
        r_13w = ratio_values[min(i + idx_13w, len(ratio_values) - 1)]
        if r_13w > 0:
            historical_returns.append((r_now / r_13w - 1.0) * 100.0)

    if len(historical_returns) < 8:
        signal = current_ratio_return / 10.0
        return signal, 0.6

    z = _zscore(current_ratio_return, historical_returns)
    confidence = 1.0 if len(historical_returns) >= 20 else 0.8
    return z, confidence


def _compute_capex_signal(
    capex: HyperscalerCapexSnapshot,
) -> tuple[Optional[float], float]:
    """
    Compute HyperscalerCapexAccelerating signal from EDGAR snapshot.

    Signal: (avg_yoy_growth_pct − 20.0) / 10.0
    At 20%: signal = 0.0 → P ≈ 0.50
    At 30%: signal = 1.0 → P ≈ 0.73
    At 10%: signal = −1.0 → P ≈ 0.27

    Returns (signal, confidence).
    """
    if capex.avg_yoy_growth_pct is None:
        return None, 0.5

    signal = (capex.avg_yoy_growth_pct - 20.0) / 10.0
    return signal, capex.confidence


def _compute_valuation_zscore(
    qqq_obs: list[YFObservation],
) -> tuple[Optional[float], float]:
    """
    Compute TechValuationDetached signal from QQQ price z-score.

    Uses the z-score of the current QQQ price vs its 3-year (up to 750
    trading-day) history.  This serves as a proxy for P/E elevation:
    when QQQ price is significantly above its 3-year rolling mean, it
    implies elevated valuation multiples.

    Signal: z_score − 1.0 (threshold: z = 1.0)
    At z=1.0: signal = 0 → P ≈ 0.50
    At z=2.0: signal = 1 → P ≈ 0.73
    At z=0:   signal = −1 → P ≈ 0.27

    Returns (signal, confidence).
    """
    if len(qqq_obs) < 100:
        return None, 0.5

    prices = _values_from_yf(qqq_obs)
    current_price = prices[0]
    # Use up to 750 most recent trading days (~3 years) for history
    history = prices[:750]

    z = _zscore(current_price, history)
    # Deduct threshold of 1.0 so boundary = z=1.0
    signal = z - 1.0
    confidence = 1.0 if len(history) >= 250 else 0.8
    return signal, confidence


def _compute_ip_investment_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute IPInvestmentRising signal from Y033RC1Q027SBEA.

    4-quarter growth rate = (latest / 4q_ago − 1) × 100.
    Signal: (current_4q_growth − median_historical_4q_growth) /
             max(iqr_4q_growth, 0.5)

    True when current 4q growth exceeds historical median.

    Returns (signal, confidence).
    """
    if len(obs) < AI_MIN_OBS["Y033RC1Q027SBEA"]:
        return None, 0.5

    # 4-quarter growth: latest vs 4 quarters (≈5th entry in newest-first list)
    latest = obs[0].value
    # Quarterly obs: step of 4 to go back 1 year
    if len(obs) < 5:
        return None, 0.5
    val_4q_ago = obs[4].value
    if val_4q_ago <= 0:
        return None, 0.5

    current_growth = (latest / val_4q_ago - 1.0) * 100.0

    # Build historical distribution of 4q growth rates
    # (slide window: step 1 quarter = 1 obs)
    historical_growths: list[float] = []
    for i in range(0, len(obs) - 5):
        v_now = obs[i].value
        v_4q = obs[i + 4].value
        if v_4q > 0:
            historical_growths.append((v_now / v_4q - 1.0) * 100.0)

    if len(historical_growths) < 4:
        # Insufficient history: compare to zero (positive growth = True)
        signal = current_growth / 2.0
        return signal, 0.6

    arr = np.array(historical_growths, dtype=float)
    median = float(np.median(arr))
    iqr = max(float(np.percentile(arr, 75) - np.percentile(arr, 25)), 0.5)
    signal = (current_growth - median) / iqr
    return signal, 1.0


def _compute_labor_productivity_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute LaborProductivityImproving signal from PRS85006092.

    YoY change: (latest / prior_year − 1) × 100 (quarterly: 4 quarters ago)
    Signal: (yoy_pct − 2.0) / 0.5

    Returns (signal, confidence).
    """
    if len(obs) < AI_MIN_OBS["PRS85006092"]:
        return None, 0.5

    if len(obs) < 5:
        return None, 0.5

    latest = obs[0].value
    val_4q_ago = obs[4].value
    if val_4q_ago <= 0:
        return None, 0.5

    yoy_pct = (latest / val_4q_ago - 1.0) * 100.0
    signal = (yoy_pct - 2.0) / 0.5
    return signal, 1.0


def _compute_gdp_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute BroadEconomicLift signal from A191RL1Q225SBEA.

    A191RL1Q225SBEA is already an annualised percent change (not an index).
    Signal: (growth_pct − 2.5) / 0.5

    Returns (signal, confidence).
    """
    if len(obs) < AI_MIN_OBS["A191RL1Q225SBEA"]:
        return None, 0.5

    latest = obs[0].value
    signal = (latest - 2.5) / 0.5
    return signal, 1.0


def _compute_vix_signal(
    vix_obs: list[YFObservation],
) -> tuple[Optional[float], float]:
    """
    Compute AIRiskPremiumCompressed signal from ^VIX.

    Signal: − z_score of current VIX vs 2-year rolling distribution.
    Inverted so that low VIX (below mean) → positive signal → True.

    Returns (signal, confidence).
    """
    if len(vix_obs) < 60:
        return None, 0.5

    prices = _values_from_yf(vix_obs)
    current_vix = prices[0]
    history = prices[:504]  # ~2 years of daily trading data

    z = _zscore(current_vix, history)
    # Invert: low VIX → negative z → positive signal
    signal = -z
    confidence = 1.0 if len(history) >= 100 else 0.7
    return signal, confidence


# ---------------------------------------------------------------------------
# Snapshot builder — pure function, testable without I/O
# ---------------------------------------------------------------------------

def compute_snapshot(
    yf_data: dict[str, list[YFObservation]],
    fred_data: dict[str, list[FREDObservation]],
    capex: HyperscalerCapexSnapshot,
    target_date: date,
) -> AIRegimeSnapshot:
    """
    Derive all signals and soft probabilities from raw data observations.

    Parameters
    ----------
    yf_data : dict[str, list[YFObservation]]
        Mapping ticker → observations, newest-first.
    fred_data : dict[str, list[FREDObservation]]
        Mapping FRED series_id → observations, newest-first.
    capex : HyperscalerCapexSnapshot
        Aggregated EDGAR capex result.
    target_date : date
        The week-ending date for this evidence record.

    Returns
    -------
    AIRegimeSnapshot
        Fully populated snapshot with soft probabilities and hard booleans.
    """
    snap = AIRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    # ---- SemiconductorMomentum (^SOX) ------------------------------------
    sox_obs = yf_data.get("^SOX", [])
    sox_sig, sox_conf = _compute_13w_return_zscore(sox_obs, "^SOX")
    snap.sox_return_zscore = sox_sig
    if sox_sig is None:
        # No data → maximum uncertainty
        snap.p_semiconductor_momentum = 0.5
    else:
        # Threshold at z = 0.5 → signal = z - 0.5
        snap.p_semiconductor_momentum = _soft_bool(sox_sig - 0.5)
    snap.semiconductor_momentum = snap.p_semiconductor_momentum > 0.5
    confidence["SemiconductorMomentum"] = sox_conf

    # ---- MarketConcentrationExtreme (QQQ/RSP) ----------------------------
    qqq_obs = yf_data.get("QQQ", [])
    rsp_obs = yf_data.get("RSP", [])
    conc_sig, conc_conf = _compute_concentration_ratio_zscore(qqq_obs, rsp_obs)
    snap.concentration_ratio_zscore = conc_sig
    if conc_sig is None:
        # No data → maximum uncertainty
        snap.p_market_concentration_extreme = 0.5
    else:
        # Threshold at z = 0.5 → signal = z - 0.5
        snap.p_market_concentration_extreme = _soft_bool(conc_sig - 0.5)
    snap.market_concentration_extreme = snap.p_market_concentration_extreme > 0.5
    confidence["MarketConcentrationExtreme"] = conc_conf

    # ---- HyperscalerCapexAccelerating (EDGAR) ----------------------------
    capex_sig, capex_conf = _compute_capex_signal(capex)
    if capex_sig is None:
        capex_sig = 0.0
    snap.capex_avg_yoy_pct = capex.avg_yoy_growth_pct
    snap.p_hyperscaler_capex_accelerating = _soft_bool(capex_sig)
    snap.hyperscaler_capex_accelerating = snap.p_hyperscaler_capex_accelerating > 0.5
    confidence["HyperscalerCapexAccelerating"] = capex_conf

    # ---- TechValuationDetached (QQQ price z-score) -----------------------
    val_sig, val_conf = _compute_valuation_zscore(qqq_obs)
    # val_sig is already (raw_z - 1.0); restore raw z for diagnostics
    snap.qqq_valuation_zscore = (val_sig + 1.0) if val_sig is not None else None
    if val_sig is None:
        # No data → maximum uncertainty
        snap.p_tech_valuation_detached = 0.5
    else:
        snap.p_tech_valuation_detached = _soft_bool(val_sig)
    snap.tech_valuation_detached = snap.p_tech_valuation_detached > 0.5
    confidence["TechValuationDetached"] = val_conf

    # ---- IPInvestmentRising (FRED Y033RC1Q027SBEA) -----------------------
    ip_obs = fred_data.get("Y033RC1Q027SBEA", [])
    ip_sig, ip_conf = _compute_ip_investment_signal(ip_obs)
    if ip_sig is None:
        ip_sig = 0.0
    snap.ip_investment_signal = ip_sig
    snap.p_ip_investment_rising = _soft_bool(ip_sig)
    snap.ip_investment_rising = snap.p_ip_investment_rising > 0.5
    confidence["IPInvestmentRising"] = ip_conf

    # ---- LaborProductivityImproving (FRED PRS85006092) -------------------
    prod_obs = fred_data.get("PRS85006092", [])
    prod_sig, prod_conf = _compute_labor_productivity_signal(prod_obs)
    if prod_sig is None:
        prod_sig = 0.0
    snap.labor_prod_yoy_pct = (
        (prod_sig * 0.5 + 2.0) if prod_sig is not None else None
    )
    snap.p_labor_productivity_improving = _soft_bool(prod_sig)
    snap.labor_productivity_improving = snap.p_labor_productivity_improving > 0.5
    confidence["LaborProductivityImproving"] = prod_conf

    # ---- BroadEconomicLift (FRED A191RL1Q225SBEA) ------------------------
    gdp_obs = fred_data.get("A191RL1Q225SBEA", [])
    gdp_sig, gdp_conf = _compute_gdp_signal(gdp_obs)
    if gdp_sig is None:
        gdp_sig = 0.0
    snap.gdp_growth_pct = (gdp_sig * 0.5 + 2.5) if gdp_sig is not None else None
    snap.p_broad_economic_lift = _soft_bool(gdp_sig)
    snap.broad_economic_lift = snap.p_broad_economic_lift > 0.5
    confidence["BroadEconomicLift"] = gdp_conf

    # ---- AIRiskPremiumCompressed (^VIX) ----------------------------------
    vix_obs = yf_data.get("^VIX", [])
    vix_sig, vix_conf = _compute_vix_signal(vix_obs)
    if vix_sig is None:
        vix_sig = 0.0
    snap.vix_zscore = -vix_sig  # store raw z (un-inverted) for diagnostics
    snap.p_ai_risk_premium_compressed = _soft_bool(vix_sig)
    snap.ai_risk_premium_compressed = snap.p_ai_risk_premium_compressed > 0.5
    confidence["AIRiskPremiumCompressed"] = vix_conf

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class AIRegimePipeline:
    """
    Fetches yfinance, FRED, and EDGAR data and converts them into a single
    EvidenceRecord for the ai-regime-v1 domain.

    Parameters
    ----------
    yf_client : AIYFinanceClient
        yfinance client for market data.
    fred : FREDClient
        FRED API client.
    edgar : EDGARClient
        SEC EDGAR client.
    """

    def __init__(
        self,
        yf_client: AIYFinanceClient,
        fred: FREDClient,
        edgar: EDGARClient,
    ) -> None:
        self._yf = yf_client
        self._fred = fred
        self._edgar = edgar

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def fetch_evidence(
        self,
        target_date: Optional[date] = None,
    ) -> EvidenceRecord:
        """
        Fetch all data sources for the given week and return an EvidenceRecord.

        Parameters
        ----------
        target_date : date, optional
            The evidence week-ending date (typically the most recent Friday).
            Defaults to the previous Friday from today.

        Returns
        -------
        EvidenceRecord
            Fully-populated record with 8 soft BOOLEAN assignments.
        """
        if target_date is None:
            target_date = _last_friday()

        # Fetch yfinance and FRED concurrently; EDGAR uses its own cache
        yf_task = asyncio.create_task(self._yf.fetch_all(end_date=target_date))
        fred_task = asyncio.create_task(self._fetch_fred_all(end_date=target_date))
        edgar_task = asyncio.create_task(
            self._edgar.fetch_hyperscaler_capex(as_of=target_date)
        )

        yf_data, fred_data, capex = await asyncio.gather(
            yf_task, fred_task, edgar_task, return_exceptions=False
        )

        snapshot = compute_snapshot(yf_data, fred_data, capex, target_date)
        record = self.build_evidence_record(snapshot)
        _log_snapshot(snapshot, target_date)
        return record

    async def _fetch_fred_all(
        self, end_date: date
    ) -> dict[str, list[FREDObservation]]:
        """Fetch all three FRED series concurrently."""
        from .fred_client import AI_FRED_SERIES

        async def _safe_fetch(series_id: str) -> tuple[str, list[FREDObservation]]:
            try:
                lb = AI_FETCH_LOOKBACK_DAYS.get(series_id, 2200)
                start = end_date - timedelta(days=lb)
                obs = await self._fred.fetch_series(
                    series_id=series_id,
                    end_date=end_date,
                    start_date=start,
                    limit=500,
                )
                return series_id, obs
            except IOError as exc:
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)
                return series_id, []

        series_ids = list(AI_FRED_SERIES.values())
        results = await asyncio.gather(*[_safe_fetch(sid) for sid in series_ids])
        return dict(results)

    # ------------------------------------------------------------------
    # Pure mapping — no I/O; primary test target
    # ------------------------------------------------------------------

    @staticmethod
    def build_evidence_record(snapshot: AIRegimeSnapshot) -> EvidenceRecord:
        """
        Map an AIRegimeSnapshot to an EvidenceRecord.

        Produces SOFT_OBSERVED assignments with sigmoid-calibrated
        probability distributions.  Synchronous; no external dependencies.
        """
        variables = get_variables()
        conf = snapshot.confidence

        def _assignment(
            var_name: str,
            observed_value: bool,
            p_true: float,
        ) -> ObservedAssignment:
            c = conf.get(var_name, 1.0)
            return ObservedAssignment(
                variable_id=variables[var_name].variable_id,
                observed_value=observed_value,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=c,
                probabilities={True: p_true, False: 1.0 - p_true},
            )

        assignments = [
            _assignment(
                "SemiconductorMomentum",
                snapshot.semiconductor_momentum,
                snapshot.p_semiconductor_momentum,
            ),
            _assignment(
                "MarketConcentrationExtreme",
                snapshot.market_concentration_extreme,
                snapshot.p_market_concentration_extreme,
            ),
            _assignment(
                "HyperscalerCapexAccelerating",
                snapshot.hyperscaler_capex_accelerating,
                snapshot.p_hyperscaler_capex_accelerating,
            ),
            _assignment(
                "TechValuationDetached",
                snapshot.tech_valuation_detached,
                snapshot.p_tech_valuation_detached,
            ),
            _assignment(
                "IPInvestmentRising",
                snapshot.ip_investment_rising,
                snapshot.p_ip_investment_rising,
            ),
            _assignment(
                "LaborProductivityImproving",
                snapshot.labor_productivity_improving,
                snapshot.p_labor_productivity_improving,
            ),
            _assignment(
                "BroadEconomicLift",
                snapshot.broad_economic_lift,
                snapshot.p_broad_economic_lift,
            ),
            _assignment(
                "AIRiskPremiumCompressed",
                snapshot.ai_risk_premium_compressed,
                snapshot.p_ai_risk_premium_compressed,
            ),
        ]

        target_date = snapshot.target_date or datetime.now(timezone.utc).date()
        ts = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            tzinfo=timezone.utc,
        )

        overall_confidence = (
            float(sum(conf.values()) / len(conf)) if conf else 1.0
        )

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=ts,
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                "AI-REGIME:yfinance(^SOX,QQQ,RSP,^VIX)"
                "+EDGAR(MSFT,GOOGL,AMZN,META)"
                "+FRED(Y033RC1Q027SBEA,PRS85006092,A191RL1Q225SBEA)"
                f"@week-ending-{target_date}"
            ),
            confidence=overall_confidence,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_friday(as_of: Optional[date] = None) -> date:
    """Return the most recent Friday on or before `as_of` (default: today)."""
    today = as_of or datetime.now(timezone.utc).date()
    days_since_friday = (today.weekday() - 4) % 7  # Monday=0, Friday=4
    return today - timedelta(days=days_since_friday)


def _weekly_backfill_dates(backfill_weeks: int, today: date) -> list[date]:
    """
    Return list of unique week-ending Fridays for the past backfill_weeks.

    Each date is the Friday of a past week, oldest first.
    """
    fridays: set[date] = set()
    for delta in range(backfill_weeks * 7, 0, -1):
        d = today - timedelta(days=delta)
        if d.weekday() == 4:  # Friday
            fridays.add(d)
    return sorted(fridays)


def _log_snapshot(snapshot: AIRegimeSnapshot, target_date: date) -> None:
    """Log a one-line summary of the evidence snapshot."""
    logger.info(
        (
            "AIRegime evidence week-ending=%s: "
            "SM=%s(p=%.2f) MCE=%s(p=%.2f) HCA=%s(p=%.2f) TVD=%s(p=%.2f) "
            "IPR=%s(p=%.2f) LPI=%s(p=%.2f) BEL=%s(p=%.2f) ARPC=%s(p=%.2f) | "
            "sox_z=%.2f conc_z=%.2f capex_yoy=%.1f qqq_val_z=%.2f "
            "ip_sig=%.2f prod_yoy=%.2f gdp_pct=%.2f vix_z=%.2f"
        ),
        target_date,
        snapshot.semiconductor_momentum,     snapshot.p_semiconductor_momentum,
        snapshot.market_concentration_extreme, snapshot.p_market_concentration_extreme,
        snapshot.hyperscaler_capex_accelerating, snapshot.p_hyperscaler_capex_accelerating,
        snapshot.tech_valuation_detached,     snapshot.p_tech_valuation_detached,
        snapshot.ip_investment_rising,        snapshot.p_ip_investment_rising,
        snapshot.labor_productivity_improving, snapshot.p_labor_productivity_improving,
        snapshot.broad_economic_lift,         snapshot.p_broad_economic_lift,
        snapshot.ai_risk_premium_compressed,  snapshot.p_ai_risk_premium_compressed,
        snapshot.sox_return_zscore or float("nan"),
        snapshot.concentration_ratio_zscore or float("nan"),
        snapshot.capex_avg_yoy_pct or float("nan"),
        snapshot.qqq_valuation_zscore or float("nan"),
        snapshot.ip_investment_signal or float("nan"),
        snapshot.labor_prod_yoy_pct or float("nan"),
        snapshot.gdp_growth_pct or float("nan"),
        snapshot.vix_zscore or float("nan"),
    )
