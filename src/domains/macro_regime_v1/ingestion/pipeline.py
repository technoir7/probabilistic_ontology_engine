"""
MacroRegimePipeline — combines FRED observations into EvidenceRecords.

This pipeline is the single point that owns the mapping from raw FRED API
data to domain variable UUIDs.  It fetches all required series concurrently
and produces one EvidenceRecord per weekly call.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.

YieldCurveInverted
    Signal : -(weekly median T10Y2Y) / 0.30 percentage points
    high   : inverted by more than 0.15 points; low: positive by more than 0.15

InflationShock
    Signal : (CPIAUCSL 12-month % change - 3.5) / 0.75
    high   : above 3.875%; low: below 3.125%

LiquidityStress
    Signal : -(WALCL 13-week % change) * 5
    high   : balance sheet shrinking by more than 0.1%; low: growing by more

CreditSpreadStress
    Signal : BAMLH0A0HYM2 52-week rolling z-score

VolatilityShock
    Signal : (VIX - rolling 90-day median) / rolling 90-day IQR

DollarStrength
    Signal : DEXUSEU 52-week rolling z-score, sign flipped (dollar strong when
             a euro buys fewer dollars)

EquityRiskOn
    Signal : -(UNRATE latest - its 12-month mean) / 0.30

AIRiskOn
    Signal : z-score of the NASDAQCOM 13-week return against its history

Cadence
-------
Weekly cadence.  The pipeline is invoked once per week (Monday 09:00 UTC)
using data from the prior week (observation_end = previous Friday).

Missing data handling
---------------------
A variable whose series has too little data for its signal is MISSING in
the record (decision D10), never a middle reading: "no input" is not "near
the line".
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

from ....engine.schemas import (
    EvidenceRecord,
)
from ..domain import get_variables
from .fred_client import FREDClient, FREDObservation
from ...sources.grades import build_graded_record, level_of
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)

# Minimum observations required to compute each signal reliably; with fewer,
# the variable is MISSING.
_MIN_OBS: dict[str, int] = {
    "T10Y2Y":        5,    # at least 1 full business week
    "CPIAUCSL":      13,   # 13 months for 12m YoY
    "WALCL":         14,   # 14 weeks for 13w change
    "BAMLH0A0HYM2":  52,   # 52 observations for z-score
    "VIXCLS":        30,   # 30 observations for rolling percentile
    "DEXUSEU":       52,   # 52 observations for z-score
    "UNRATE":        4,    # at least 4 months (3m delta + 1 current)
    "NASDAQCOM":     26,   # 26 weeks for return distribution
}


# ---------------------------------------------------------------------------
# Snapshot dataclass — carries all derived signals
# ---------------------------------------------------------------------------

# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class MacroRegimeSnapshot:
    """
    Derived signals for one evidence week.

    *signals* holds each variable's signed signal (read as a level when the
    record is built); a variable without one is MISSING. The raw fields are
    for logging and diagnostics.
    """

    # Raw values for logging / diagnostics
    t10y2y_weekly_median: Optional[float] = None
    cpi_yoy_pct: Optional[float] = None
    walcl_13w_change_pct: Optional[float] = None
    hy_spread_zscore: Optional[float] = None
    vix_signal: Optional[float] = None          # (vix - median) / iqr
    dexuseu_zscore: Optional[float] = None
    unrate_signal: Optional[float] = None       # -(delta_3m) / 0.30
    nasdaq_return_zscore: Optional[float] = None

    signals: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)

    # Target date for this evidence record
    target_date: Optional[date] = None


def _values_from_obs(obs: list[FREDObservation]) -> list[float]:
    return [o.value for o in obs]


# ---------------------------------------------------------------------------
# Per-variable signal computation
# ---------------------------------------------------------------------------

def _compute_yield_curve_signal(
    obs: list[FREDObservation],
    target_date: date,
) -> tuple[Optional[float], float]:
    """
    Compute YieldCurveInverted signal from T10Y2Y observations.

    Uses the weekly median of daily T10Y2Y values for the 7 calendar days
    ending on target_date.  Falls back to the most recent available value.

    Returns (signal, confidence).
    """
    if not obs:
        return None, 0.5

    # Prefer values within the target week
    week_start = target_date - timedelta(days=6)
    week_obs = [o for o in obs if week_start <= o.obs_date <= target_date]
    use_obs = week_obs if week_obs else obs[:5]  # fallback to most recent

    if not use_obs:
        return None, 0.5

    median_val = statistics.median([o.value for o in use_obs])
    # P(YieldCurveInverted=True) ∝ how negative T10Y2Y is
    # Divide by 0.30 so that an inversion of -0.30% → signal ≈ 1.0
    signal = -median_val / 0.30
    confidence = 1.0 if len(use_obs) >= 3 else 0.7
    return signal, confidence


def _compute_inflation_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute InflationShock signal from CPIAUCSL observations.

    Computes 12-month YoY % change as (latest / 12m_ago - 1) * 100.
    Threshold: 3.5% YoY.  Scale: 0.75pp.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["CPIAUCSL"]:
        return None, 0.5

    # obs is newest-first; 12 months ago = index ~12
    if len(obs) < 13:
        return None, 0.5

    latest = obs[0].value
    year_ago = obs[12].value
    if year_ago == 0:
        return None, 0.5

    yoy_pct = (latest / year_ago - 1.0) * 100.0
    signal = (yoy_pct - 3.5) / 0.75
    return signal, 1.0


def _compute_liquidity_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute LiquidityStress signal from WALCL observations.

    Uses 13-week percentage change in the Fed balance sheet.
    Negative change (QT) → LiquidityStress=True.
    Scale factor 5.0 so a -2% contraction → signal ≈ +10 → P ≈ 0.99.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["WALCL"]:
        return None, 0.5

    current = obs[0].value
    week_13 = obs[13].value if len(obs) > 13 else obs[-1].value
    if week_13 == 0:
        return None, 0.5

    change_pct = (current / week_13 - 1.0) * 100.0
    # Negative change_pct → liquidity stress → positive signal
    signal = -change_pct * 5.0
    return signal, 1.0


def _compute_credit_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute CreditSpreadStress signal from BAMLH0A0HYM2 observations.

    52-week rolling z-score of the HY OAS spread.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["BAMLH0A0HYM2"]:
        return None, 0.5

    current = obs[0].value
    values = _values_from_obs(obs[:260])  # ~52 weeks of daily data
    signal = _zscore(current, values)
    return signal, 1.0


def _compute_volatility_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute VolatilityShock signal from VIXCLS observations.

    (current VIX - rolling 90-day median) / max(rolling IQR, 1.0)

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["VIXCLS"]:
        return None, 0.5

    current = obs[0].value
    window = _values_from_obs(obs[:90])
    arr = np.array(window, dtype=float)
    median = float(np.median(arr))
    q25 = float(np.percentile(arr, 25))
    q75 = float(np.percentile(arr, 75))
    iqr = max(q75 - q25, 1.0)
    signal = (current - median) / iqr
    return signal, 1.0


def _compute_dollar_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute DollarStrength signal from DEXUSEU observations.

    Inverted 52-week z-score: DEXUSEU is dollars per euro, so lower = stronger USD.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["DEXUSEU"]:
        return None, 0.5

    current = obs[0].value
    values = _values_from_obs(obs[:260])  # ~52 weeks
    signal = -_zscore(current, values)
    return signal, 1.0


def _compute_equity_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute EquityRiskOn signal from UNRATE observations.

    EquityRiskOn = True when unemployment is NOT rising (labour market resilient).
    Signal: -(unrate_latest - unrate_12m_mean) / 0.30
    Positive signal (unemployment below mean) → EquityRiskOn=True more likely.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["UNRATE"]:
        return None, 0.5

    latest = obs[0].value

    # 12-month rolling mean from up to 12 monthly observations
    window = _values_from_obs(obs[:12])
    mean_12m = float(np.mean(window))

    # Signal: inverted delta from mean (falling unemployment → positive)
    signal = -(latest - mean_12m) / 0.30
    return signal, 1.0


def _compute_ai_signal(
    obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Compute AIRiskOn signal from NASDAQCOM observations.

    Computes the 13-week (91-day) price return, then z-scores it against
    the historical distribution of 13-week returns in the provided window.
    This converts a raw price index into an interpretable momentum regime
    indicator without using raw prices as ontology variables.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["NASDAQCOM"]:
        return None, 0.5

    # Need at least 91 days for one 13-week return + a history of returns
    if len(obs) < 91:
        return None, 0.5

    current_price = obs[0].value
    week_13_ago_price = obs[min(91, len(obs) - 1)].value
    if week_13_ago_price == 0:
        return None, 0.5

    current_return = (current_price / week_13_ago_price - 1.0) * 100.0

    # Compute historical 13-week returns for z-score
    historical_returns: list[float] = []
    step = 7  # weekly steps for the distribution
    for i in range(0, min(len(obs) - 91, 365), step):
        p_now = obs[i].value
        p_13w = obs[min(i + 91, len(obs) - 1)].value
        if p_13w > 0:
            historical_returns.append((p_now / p_13w - 1.0) * 100.0)

    if len(historical_returns) < 10:
        # Insufficient history; use current return vs 0 as rough signal
        signal = current_return / 10.0
        return signal, 0.7

    signal = _zscore(current_return, historical_returns)
    return signal, 1.0


# ---------------------------------------------------------------------------
# Snapshot builder — pure function, testable without I/O
# ---------------------------------------------------------------------------

def compute_snapshot(
    observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> MacroRegimeSnapshot:
    """
    Derive every variable's signal from raw FRED observations.

    Parameters
    ----------
    observations : dict[str, list[FREDObservation]]
        Mapping from FRED series_id → observations (newest-first).
        Series may be absent or have insufficient data; in that case the
        affected variable has no signal and is recorded MISSING.
    target_date : date
        The week-ending date for this evidence record.

    Returns
    -------
    MacroRegimeSnapshot
        The signals, raw diagnostics and per-variable confidence.
    """
    snap = MacroRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def take(name: str, signal: Optional[float], conf: float) -> None:
        confidence[name] = conf
        if signal is not None:
            snap.signals[name] = signal

    t10y2y_sig, conf = _compute_yield_curve_signal(observations.get("T10Y2Y", []), target_date)
    take("YieldCurveInverted", t10y2y_sig, conf)
    snap.t10y2y_weekly_median = -t10y2y_sig * 0.30 if t10y2y_sig is not None else None

    infl_sig, conf = _compute_inflation_signal(observations.get("CPIAUCSL", []))
    take("InflationShock", infl_sig, conf)
    snap.cpi_yoy_pct = infl_sig * 0.75 + 3.5 if infl_sig is not None else None

    liq_sig, conf = _compute_liquidity_signal(observations.get("WALCL", []))
    take("LiquidityStress", liq_sig, conf)
    snap.walcl_13w_change_pct = -liq_sig / 5.0 if liq_sig is not None else None

    credit_sig, conf = _compute_credit_signal(observations.get("BAMLH0A0HYM2", []))
    take("CreditSpreadStress", credit_sig, conf)
    snap.hy_spread_zscore = credit_sig

    vol_sig, conf = _compute_volatility_signal(observations.get("VIXCLS", []))
    take("VolatilityShock", vol_sig, conf)
    snap.vix_signal = vol_sig

    dol_sig, conf = _compute_dollar_signal(observations.get("DEXUSEU", []))
    take("DollarStrength", dol_sig, conf)
    snap.dexuseu_zscore = dol_sig

    eq_sig, conf = _compute_equity_signal(observations.get("UNRATE", []))
    take("EquityRiskOn", eq_sig, conf)
    snap.unrate_signal = eq_sig

    ai_sig, conf = _compute_ai_signal(observations.get("NASDAQCOM", []))
    take("AIRiskOn", ai_sig, conf)
    snap.nasdaq_return_zscore = ai_sig

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class MacroRegimePipeline:
    """
    Fetches FRED series concurrently and converts them into a single
    EvidenceRecord for the macro-regime-v1 domain.

    Parameters
    ----------
    fred : FREDClient
        Configured FRED API client.
    """

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def fetch_evidence(
        self,
        target_date: date,
    ) -> EvidenceRecord:
        """
        Fetch FRED data for the given week and return an EvidenceRecord.

        Parameters
        ----------
        target_date : date, optional
            The evidence week-ending date (typically the most recent Friday).
            Defaults to the previous Friday from today.

        Returns
        -------
        EvidenceRecord
            One record: each variable observed at its level, or MISSING.

        Raises
        ------
        IOError
            If all FRED series fail to return data.
        """

        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        record = self.build_evidence_record(snapshot)

        # Log summary
        _log_snapshot(snapshot, target_date)
        return record

    # ------------------------------------------------------------------
    # Pure mapping — no I/O; primary test target
    # ------------------------------------------------------------------

    @staticmethod
    def build_evidence_record(snapshot: MacroRegimeSnapshot) -> EvidenceRecord:
        """
        Map a MacroRegimeSnapshot to an EvidenceRecord.

        Each variable with a signal is observed at its level (D25); the
        rest are MISSING.

        This method is synchronous and has no external dependencies.
        """
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="macro-regime-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="FRED:T10Y2Y+CPIAUCSL+WALCL+BAMLH0A0HYM2"
            "+VIXCLS+DEXUSEU+UNRATE+NASDAQCOM"
            f"@week-ending-{target_date}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_snapshot(snapshot: MacroRegimeSnapshot, target_date: date) -> None:
    """Log a one-line summary of the evidence snapshot for debugging."""
    logger.info(
        "MacroRegime evidence week-ending=%s: %s",
        target_date,
        " ".join(f"{name}={level_of(sig)}({sig:+.2f})" for name, sig in snapshot.signals.items()) or "no signals",
    )
