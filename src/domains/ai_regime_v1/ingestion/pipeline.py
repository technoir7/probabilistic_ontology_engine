"""
AIRegimePipeline — combines yfinance, FRED, and SEC EDGAR observations
into EvidenceRecords for the ai-regime-v1 domain.

This pipeline owns the mapping from raw API data to domain variable UUIDs.
All three sources are fetched concurrently (yfinance and FRED) or
sequentially with cache (EDGAR).  One EvidenceRecord is produced per
weekly call.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.

SemiconductorMomentum
    Source : yfinance ^SOX
    Signal : z-score of current 13-week (91-day) price return vs the
             historical distribution of 13-week returns (2-year window),
             minus 0.5 (the line sits at z = 0.5)

MarketConcentrationExtreme
    Source : yfinance QQQ and RSP
    Signal : z-score of current 13-week return of the QQQ/RSP price ratio
             vs its historical distribution, minus 0.5

HyperscalerCapexAccelerating
    Source : SEC EDGAR (MSFT, GOOGL, AMZN, META)
    Signal : (avg_yoy_growth_pct − 20.0) / 10.0
    high   : above 25%; low: below 15%

TechValuationDetached
    Source : yfinance QQQ
    Signal : z-score of current QQQ price vs 3-year (750-day) price
             history, minus 1.0 (the line sits at z = 1.0)
    Rationale: QQQ price elevation vs own 3-year trend is a reasonable
               proxy for stretched P/E, since aggregate earnings grow
               more smoothly than price.

IPInvestmentRising
    Source : FRED Y033RC1Q027SBEA (quarterly)
    Signal : (current_4q_growth − median_4q_growth) / max(iqr, 0.5)
             4-quarter growth = (latest / 4q_ago − 1) * 100

LaborProductivityImproving
    Source : FRED PRS85006092 (quarterly)
    Signal : (yoy_pct − 2.0) / 0.5
    high   : above 2.25%; low: below 1.75%

BroadEconomicLift
    Source : FRED A191RL1Q225SBEA (quarterly, already annualised %)
    Signal : (growth_pct − 2.5) / 0.5
    high   : above 2.75%; low: below 2.25%

AIRiskPremiumCompressed
    Source : yfinance ^VIX
    Signal : − z_score of current VIX vs 2-year rolling distribution
             (inverted: low VIX → positive signal → compressed premium)

Cadence
-------
Weekly cadence.  Invoked once per week (Monday 09:00 UTC) using data
from the prior week (observation_end = previous Friday).

EDGAR data is cached 6 hours.  yfinance and FRED calls happen on each run.

Missing data handling
---------------------
A variable whose source has too little data for its signal is MISSING in
the record (decision D10), never a middle reading: "no input" is not "near
the line".
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

from ....engine.schemas import (
    EvidenceRecord,
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
from ...sources.grades import build_graded_record, level_of
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Snapshot dataclass — carries all derived signals
# ---------------------------------------------------------------------------

# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class AIRegimeSnapshot:
    """
    Derived signals for one evidence week.

    *signals* holds each variable's signed signal (read as a level when the
    record is built); a variable without one is MISSING. The raw fields are
    for logging and diagnostics.
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

    signals: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)

    # Target date for this evidence record
    target_date: Optional[date] = None


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

    Signal: z_score − 1.0 (the line sits at z = 1.0)

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

    Positive when current 4q growth exceeds the historical median.

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
        # Insufficient history: compare to zero growth instead
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
    Inverted so that low VIX (below mean) → positive signal.

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
    Derive every variable's signal from raw data observations.

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
        The signals, raw diagnostics and per-variable confidence; a variable
        whose source has too little data has no signal.
    """
    snap = AIRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def take(name: str, signal: Optional[float], conf: float) -> None:
        confidence[name] = conf
        if signal is not None:
            snap.signals[name] = signal

    # SOX and concentration lines sit at z = 0.5, hence the offset.
    sox_sig, conf = _compute_13w_return_zscore(yf_data.get("^SOX", []), "^SOX")
    take("SemiconductorMomentum", sox_sig - 0.5 if sox_sig is not None else None, conf)
    snap.sox_return_zscore = sox_sig

    qqq_obs = yf_data.get("QQQ", [])
    conc_sig, conf = _compute_concentration_ratio_zscore(qqq_obs, yf_data.get("RSP", []))
    take("MarketConcentrationExtreme", conc_sig - 0.5 if conc_sig is not None else None, conf)
    snap.concentration_ratio_zscore = conc_sig

    capex_sig, conf = _compute_capex_signal(capex)
    take("HyperscalerCapexAccelerating", capex_sig, conf)
    snap.capex_avg_yoy_pct = capex.avg_yoy_growth_pct

    # val_sig is already (raw_z - 1.0); the raw z is kept for diagnostics
    val_sig, conf = _compute_valuation_zscore(qqq_obs)
    take("TechValuationDetached", val_sig, conf)
    snap.qqq_valuation_zscore = val_sig + 1.0 if val_sig is not None else None

    ip_sig, conf = _compute_ip_investment_signal(fred_data.get("Y033RC1Q027SBEA", []))
    take("IPInvestmentRising", ip_sig, conf)
    snap.ip_investment_signal = ip_sig

    prod_sig, conf = _compute_labor_productivity_signal(fred_data.get("PRS85006092", []))
    take("LaborProductivityImproving", prod_sig, conf)
    snap.labor_prod_yoy_pct = prod_sig * 0.5 + 2.0 if prod_sig is not None else None

    gdp_sig, conf = _compute_gdp_signal(fred_data.get("A191RL1Q225SBEA", []))
    take("BroadEconomicLift", gdp_sig, conf)
    snap.gdp_growth_pct = gdp_sig * 0.5 + 2.5 if gdp_sig is not None else None

    vix_sig, conf = _compute_vix_signal(yf_data.get("^VIX", []))
    take("AIRiskPremiumCompressed", vix_sig, conf)
    snap.vix_zscore = -vix_sig if vix_sig is not None else None  # raw z, un-inverted

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
        target_date: date,
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
            One record: each variable observed at its level, or MISSING.
        """

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

        Each variable with a signal is observed at its level (D25); the
        rest are MISSING. Synchronous; no external dependencies.
        """
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="ai-regime-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="AI-REGIME:yfinance(^SOX,QQQ,RSP,^VIX)"
            "+EDGAR(MSFT,GOOGL,AMZN,META)"
            "+FRED(Y033RC1Q027SBEA,PRS85006092,A191RL1Q225SBEA)"
            f"@week-ending-{target_date}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_snapshot(snapshot: AIRegimeSnapshot, target_date: date) -> None:
    """Log a one-line summary of the evidence snapshot."""
    logger.info(
        "AIRegime evidence week-ending=%s: %s",
        target_date,
        " ".join(f"{name}={level_of(sig)}({sig:+.2f})" for name, sig in snapshot.signals.items()) or "no signals",
    )
