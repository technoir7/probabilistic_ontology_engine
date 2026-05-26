"""
MacroRegimePipeline — combines FRED observations into EvidenceRecords.

This pipeline is the single point that owns the mapping from raw FRED API
data to domain variable UUIDs.  It fetches all required series concurrently
and produces one EvidenceRecord per weekly call.

Variable mapping and calibration
---------------------------------
All eight Boolean assignments are emitted as SOFT_OBSERVED with
sigmoid-calibrated probability distributions.  The boolean MAP value is
preserved in observed_value for compatibility with callers reading the hard
field.

YieldCurveInverted
    Signal  : weekly median T10Y2Y (percentage points)
    P(True) : sigmoid(-median_t10y2y / 0.30)
    At 0%:     P ≈ 0.50  (boundary case, genuine uncertainty)
    At -0.30%: P ≈ 0.73  (modestly inverted)
    At -1.00%: P ≈ 0.97  (deeply inverted)
    At +1.00%: P ≈ 0.04  (steep normal curve)

InflationShock
    Signal  : CPIAUCSL 12-month year-over-year % change
    P(True) : sigmoid((yoy_pct - 3.5) / 0.75)
    At 3.5%: P ≈ 0.50  (threshold)
    At 5.0%: P ≈ 0.87
    At 2.0%: P ≈ 0.12

LiquidityStress
    Signal  : WALCL 13-week percentage change (QT = negative)
    P(True) : sigmoid(-walcl_13w_chg_pct * 5.0)
    At 0%:    P ≈ 0.50  (neutral balance sheet)
    At -2%:   P ≈ 0.99  (active QT)
    At +2%:   P ≈ 0.01  (active QE)

CreditSpreadStress
    Signal  : BAMLH0A0HYM2 52-week rolling z-score
    P(True) : sigmoid(z_score)
    At z=0:   P ≈ 0.50
    At z=+2:  P ≈ 0.88
    At z=-1:  P ≈ 0.27

VolatilityShock
    Signal  : (current VIX - rolling 90d median) / rolling 90d IQR
    P(True) : sigmoid(signal)
    At median VIX: P ≈ 0.50
    At 2 IQR above median: P ≈ 0.88

DollarStrength
    Signal  : DEXUSEU 52-week rolling z-score (higher DEXUSEU = stronger USD)
    P(True) : sigmoid(z_score)
    At z=0:   P ≈ 0.50
    At z=+1:  P ≈ 0.73  (USD above trend)

EquityRiskOn
    Signal  : -(UNRATE_latest - UNRATE_12m_mean) / 0.30
    P(True) : sigmoid(signal)
    When UNRATE at mean: P ≈ 0.50
    When UNRATE -0.30% below mean (falling): P ≈ 0.73 (risk-on)
    When UNRATE +0.50% above mean (rising):  P ≈ 0.19 (risk-off)

AIRiskOn
    Signal  : z-score of NASDAQCOM 13-week price return vs historical returns
    P(True) : sigmoid(z_score)
    At z=0:   P ≈ 0.50  (average tech momentum)
    At z=+1:  P ≈ 0.73  (tech outperforming)
    At z=-1:  P ≈ 0.27  (tech underperforming)

All P(True) values are clamped to [0.01, 0.99].

Cadence
-------
Weekly cadence.  The pipeline is invoked once per week (Monday 09:00 UTC)
using data from the prior week (observation_end = previous Friday).

Missing data handling
---------------------
If a FRED series returns insufficient data for a signal computation, the
signal defaults to 0.0 (→ P(True) = 0.50, maximum uncertainty) and the
assignment confidence is degraded to 0.5.  This prevents hard failures
during data outages while signalling genuine uncertainty to the ontology.
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
from .fred_client import FREDClient, FREDObservation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Calibration constants
# ---------------------------------------------------------------------------

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99

# Minimum observations required to compute each signal reliably.
# If fewer are available, the signal falls back to 0.0 (maximum uncertainty)
# and the confidence weight is degraded.
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

@dataclass
class MacroRegimeSnapshot:
    """
    Derived signals and soft-probability calibrations for one evidence week.

    Each *_signal field is the pre-sigmoid score fed into _soft_bool().
    Each *_p_true field is the calibrated P(True) ∈ [0.01, 0.99].
    Each *_bool field is the hard MAP boolean (observed_value).
    Each *_confidence field reflects data availability (1.0 if complete).
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

    # Derived soft probabilities
    p_yield_curve_inverted: float = 0.5
    p_inflation_shock: float = 0.5
    p_liquidity_stress: float = 0.5
    p_credit_spread_stress: float = 0.5
    p_volatility_shock: float = 0.5
    p_dollar_strength: float = 0.5
    p_equity_risk_on: float = 0.5
    p_ai_risk_on: float = 0.5

    # Hard MAP booleans (for observed_value in assignments)
    yield_curve_inverted: bool = False
    inflation_shock: bool = False
    liquidity_stress: bool = False
    credit_spread_stress: bool = False
    volatility_shock: bool = False
    dollar_strength: bool = False
    equity_risk_on: bool = False
    ai_risk_on: bool = False

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
    """Rolling z-score: (current - mean) / std. Returns 0.0 if std ≈ 0."""
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

    52-week rolling z-score.  Higher DEXUSEU = more USD per EUR = stronger USD.

    Returns (signal, confidence).
    """
    if len(obs) < _MIN_OBS["DEXUSEU"]:
        return None, 0.5

    current = obs[0].value
    values = _values_from_obs(obs[:260])  # ~52 weeks
    signal = _zscore(current, values)
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
    Derive all signals and soft probabilities from raw FRED observations.

    Parameters
    ----------
    observations : dict[str, list[FREDObservation]]
        Mapping from FRED series_id → observations (newest-first).
        Series may be absent or have insufficient data; in that case the
        affected signal defaults to 0.0 and confidence to 0.5.
    target_date : date
        The week-ending date for this evidence record.

    Returns
    -------
    MacroRegimeSnapshot
        Fully populated snapshot with soft probabilities and hard booleans.
    """
    snap = MacroRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    # ---- YieldCurveInverted ------------------------------------------------
    t10y2y_obs = observations.get("T10Y2Y", [])
    t10y2y_sig, t10y2y_conf = _compute_yield_curve_signal(t10y2y_obs, target_date)
    if t10y2y_sig is None:
        t10y2y_sig = 0.0
    snap.t10y2y_weekly_median = (
        -t10y2y_sig * 0.30 if t10y2y_sig is not None else None
    )
    snap.p_yield_curve_inverted = _soft_bool(t10y2y_sig)
    snap.yield_curve_inverted = snap.p_yield_curve_inverted > 0.5
    confidence["YieldCurveInverted"] = t10y2y_conf

    # ---- InflationShock ----------------------------------------------------
    cpi_obs = observations.get("CPIAUCSL", [])
    infl_sig, infl_conf = _compute_inflation_signal(cpi_obs)
    if infl_sig is None:
        infl_sig = 0.0
    snap.cpi_yoy_pct = (infl_sig * 0.75 + 3.5) if infl_sig is not None else None
    snap.p_inflation_shock = _soft_bool(infl_sig)
    snap.inflation_shock = snap.p_inflation_shock > 0.5
    confidence["InflationShock"] = infl_conf

    # ---- LiquidityStress ---------------------------------------------------
    walcl_obs = observations.get("WALCL", [])
    liq_sig, liq_conf = _compute_liquidity_signal(walcl_obs)
    if liq_sig is None:
        liq_sig = 0.0
    snap.walcl_13w_change_pct = (
        -liq_sig / 5.0 if liq_sig is not None else None
    )
    snap.p_liquidity_stress = _soft_bool(liq_sig)
    snap.liquidity_stress = snap.p_liquidity_stress > 0.5
    confidence["LiquidityStress"] = liq_conf

    # ---- CreditSpreadStress ------------------------------------------------
    hy_obs = observations.get("BAMLH0A0HYM2", [])
    credit_sig, credit_conf = _compute_credit_signal(hy_obs)
    if credit_sig is None:
        credit_sig = 0.0
    snap.hy_spread_zscore = credit_sig
    snap.p_credit_spread_stress = _soft_bool(credit_sig)
    snap.credit_spread_stress = snap.p_credit_spread_stress > 0.5
    confidence["CreditSpreadStress"] = credit_conf

    # ---- VolatilityShock ---------------------------------------------------
    vix_obs = observations.get("VIXCLS", [])
    vol_sig, vol_conf = _compute_volatility_signal(vix_obs)
    if vol_sig is None:
        vol_sig = 0.0
    snap.vix_signal = vol_sig
    snap.p_volatility_shock = _soft_bool(vol_sig)
    snap.volatility_shock = snap.p_volatility_shock > 0.5
    confidence["VolatilityShock"] = vol_conf

    # ---- DollarStrength ----------------------------------------------------
    dex_obs = observations.get("DEXUSEU", [])
    dol_sig, dol_conf = _compute_dollar_signal(dex_obs)
    if dol_sig is None:
        dol_sig = 0.0
    snap.dexuseu_zscore = dol_sig
    snap.p_dollar_strength = _soft_bool(dol_sig)
    snap.dollar_strength = snap.p_dollar_strength > 0.5
    confidence["DollarStrength"] = dol_conf

    # ---- EquityRiskOn ------------------------------------------------------
    unrate_obs = observations.get("UNRATE", [])
    eq_sig, eq_conf = _compute_equity_signal(unrate_obs)
    if eq_sig is None:
        eq_sig = 0.0
    snap.unrate_signal = eq_sig
    snap.p_equity_risk_on = _soft_bool(eq_sig)
    snap.equity_risk_on = snap.p_equity_risk_on > 0.5
    confidence["EquityRiskOn"] = eq_conf

    # ---- AIRiskOn ----------------------------------------------------------
    nasdaq_obs = observations.get("NASDAQCOM", [])
    ai_sig, ai_conf = _compute_ai_signal(nasdaq_obs)
    if ai_sig is None:
        ai_sig = 0.0
    snap.nasdaq_return_zscore = ai_sig
    snap.p_ai_risk_on = _soft_bool(ai_sig)
    snap.ai_risk_on = snap.p_ai_risk_on > 0.5
    confidence["AIRiskOn"] = ai_conf

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
        target_date: Optional[date] = None,
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
            Fully-populated record with 8 soft BOOLEAN assignments.

        Raises
        ------
        IOError
            If all FRED series fail to return data.
        """
        if target_date is None:
            target_date = _last_friday()

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

        Produces SOFT_OBSERVED assignments with sigmoid-calibrated probability
        distributions.  The boolean MAP value is preserved in observed_value
        for backward compatibility.

        This method is synchronous and has no external dependencies.
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
                "YieldCurveInverted",
                snapshot.yield_curve_inverted,
                snapshot.p_yield_curve_inverted,
            ),
            _assignment(
                "InflationShock",
                snapshot.inflation_shock,
                snapshot.p_inflation_shock,
            ),
            _assignment(
                "LiquidityStress",
                snapshot.liquidity_stress,
                snapshot.p_liquidity_stress,
            ),
            _assignment(
                "CreditSpreadStress",
                snapshot.credit_spread_stress,
                snapshot.p_credit_spread_stress,
            ),
            _assignment(
                "VolatilityShock",
                snapshot.volatility_shock,
                snapshot.p_volatility_shock,
            ),
            _assignment(
                "DollarStrength",
                snapshot.dollar_strength,
                snapshot.p_dollar_strength,
            ),
            _assignment(
                "EquityRiskOn",
                snapshot.equity_risk_on,
                snapshot.p_equity_risk_on,
            ),
            _assignment(
                "AIRiskOn",
                snapshot.ai_risk_on,
                snapshot.p_ai_risk_on,
            ),
        ]

        target_date = snapshot.target_date or datetime.now(timezone.utc).date()
        ts = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            tzinfo=timezone.utc,
        )

        # Overall record confidence: mean of per-variable confidences
        overall_confidence = float(
            sum(conf.values()) / len(conf)
        ) if conf else 1.0

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=ts,
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                "FRED:T10Y2Y+CPIAUCSL+WALCL+BAMLH0A0HYM2"
                "+VIXCLS+DEXUSEU+UNRATE+NASDAQCOM"
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


def _log_snapshot(snapshot: MacroRegimeSnapshot, target_date: date) -> None:
    """Log a one-line summary of the evidence snapshot for debugging."""
    logger.info(
        (
            "MacroRegime evidence week-ending=%s: "
            "YCI=%s(p=%.2f) IS=%s(p=%.2f) LS=%s(p=%.2f) CSS=%s(p=%.2f) "
            "VS=%s(p=%.2f) DS=%s(p=%.2f) ERO=%s(p=%.2f) AIRO=%s(p=%.2f) | "
            "t10y2y_med=%.3f cpi_yoy=%.2f walcl_13w=%.2f "
            "hy_z=%.2f vix_sig=%.2f dex_z=%.2f unrate_sig=%.2f nasdaq_z=%.2f"
        ),
        target_date,
        snapshot.yield_curve_inverted, snapshot.p_yield_curve_inverted,
        snapshot.inflation_shock, snapshot.p_inflation_shock,
        snapshot.liquidity_stress, snapshot.p_liquidity_stress,
        snapshot.credit_spread_stress, snapshot.p_credit_spread_stress,
        snapshot.volatility_shock, snapshot.p_volatility_shock,
        snapshot.dollar_strength, snapshot.p_dollar_strength,
        snapshot.equity_risk_on, snapshot.p_equity_risk_on,
        snapshot.ai_risk_on, snapshot.p_ai_risk_on,
        snapshot.t10y2y_weekly_median or float("nan"),
        snapshot.cpi_yoy_pct or float("nan"),
        snapshot.walcl_13w_change_pct or float("nan"),
        snapshot.hy_spread_zscore or float("nan"),
        snapshot.vix_signal or float("nan"),
        snapshot.dexuseu_zscore or float("nan"),
        snapshot.unrate_signal or float("nan"),
        snapshot.nasdaq_return_zscore or float("nan"),
    )
