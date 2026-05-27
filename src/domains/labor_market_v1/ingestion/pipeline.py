"""
LaborMarketPipeline — FRED observations → EvidenceRecords for labor-market-v1.

Variable calibrations
----------------------
UnemploymentRising
    Signal  : (UNRATE_latest - UNRATE_12m_mean) / 0.30
    P(True) : sigmoid(signal)  [positive delta = rising = True]

WageInflationPersistent
    Signal  : CES0500000003 YoY % vs historical mean: (yoy - hist_mean) / hist_std
    P(True) : sigmoid(z_score)

JobOpeningsFalling
    Signal  : -JTSJOL 12-month z-score  [falling openings = negative z = inverted positive]
    P(True) : sigmoid(-z_score)

LayoffCycleBeginning
    Signal  : ICSA 52-week rolling z-score
    P(True) : sigmoid(z_score)

LaborProductivityWeak
    Signal  : -(PRS85006092 YoY % - historical mean YoY) / historical std
    P(True) : sigmoid(-z_score)  [below trend = weak = True]

ParticipationRateFalling
    Signal  : -CIVPART 12-month z-score  [falling participation = True]
    P(True) : sigmoid(-z_score)

RealWageGrowthPositive
    Signal  : (CES0500000003 YoY % - CPIAUCSL YoY %) / 1.0
    P(True) : sigmoid(signal)  [positive real wage = True]

TightLaborMarket
    Signal  : composite of -UNRATE z-score + JTSJOL z-score
    P(True) : sigmoid(composite / 2.0)
"""
from __future__ import annotations

import logging
import math
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

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99

_MIN_OBS: dict[str, int] = {
    "UNRATE":        4,
    "CES0500000003": 13,   # 13 months for 12m YoY
    "JTSJOL":        13,
    "ICSA":          26,   # 26 weeks for z-score
    "PRS85006092":   5,    # 5 quarters for YoY trend
    "CIVPART":       13,
    "CPIAUCSL":      13,
}


@dataclass
class LaborMarketSnapshot:
    p_unemployment_rising: float = 0.5
    p_wage_inflation_persistent: float = 0.5
    p_job_openings_falling: float = 0.5
    p_layoff_cycle_beginning: float = 0.5
    p_labor_productivity_weak: float = 0.5
    p_participation_rate_falling: float = 0.5
    p_real_wage_growth_positive: float = 0.5
    p_tight_labor_market: float = 0.5

    unemployment_rising: bool = False
    wage_inflation_persistent: bool = False
    job_openings_falling: bool = False
    layoff_cycle_beginning: bool = False
    labor_productivity_weak: bool = False
    participation_rate_falling: bool = False
    real_wage_growth_positive: bool = False
    tight_labor_market: bool = False

    confidence: dict[str, float] = field(default_factory=dict)
    target_date: Optional[date] = None


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


def _values_from_obs(obs: list[FREDObservation]) -> list[float]:
    return [o.value for o in obs]


def _compute_unemployment_rising(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """(UNRATE_latest - UNRATE_12m_mean) / 0.30."""
    if len(obs) < _MIN_OBS["UNRATE"]:
        return None, 0.5
    latest = obs[0].value
    window = _values_from_obs(obs[:12])
    mean_12m = float(np.mean(window))
    signal = (latest - mean_12m) / 0.30
    return signal, 1.0


def _compute_wage_inflation_persistent(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """CES0500000003 YoY growth rate z-scored vs historical YoY rates."""
    if len(obs) < _MIN_OBS["CES0500000003"]:
        return None, 0.5
    if len(obs) < 13:
        return None, 0.5
    latest = obs[0].value
    year_ago = obs[12].value
    if year_ago == 0:
        return None, 0.5
    yoy_pct = (latest / year_ago - 1.0) * 100.0

    hist_yoy: list[float] = []
    for i in range(0, min(len(obs) - 12, 36), 1):
        p_now = obs[i].value
        p_yr = obs[i + 12].value if i + 12 < len(obs) else None
        if p_yr and p_yr > 0:
            hist_yoy.append((p_now / p_yr - 1.0) * 100.0)

    if len(hist_yoy) < 6:
        # Threshold: 4% YoY wage growth is persistent
        return (yoy_pct - 4.0) / 0.5, 0.7

    return _zscore(yoy_pct, hist_yoy), 1.0


def _compute_job_openings_falling(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """JTSJOL: inverted z-score (falling openings = JobOpeningsFalling = True)."""
    if len(obs) < _MIN_OBS["JTSJOL"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:24])
    z = _zscore(current, values)
    return -z, 1.0  # Invert: below-average openings → True


def _compute_layoff_cycle_beginning(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """ICSA 52-week rolling z-score (elevated claims = LayoffCycleBeginning = True)."""
    if len(obs) < _MIN_OBS["ICSA"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:52])
    return _zscore(current, values), 1.0


def _compute_labor_productivity_weak(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """PRS85006092 YoY below historical mean → LaborProductivityWeak = True."""
    if len(obs) < _MIN_OBS["PRS85006092"]:
        return None, 0.5
    if len(obs) < 5:
        return None, 0.5
    latest = obs[0].value
    year_ago = obs[min(4, len(obs) - 1)].value  # 4 quarters back
    if year_ago == 0:
        return None, 0.5
    yoy_pct = (latest / year_ago - 1.0) * 100.0

    hist_yoy: list[float] = []
    for i in range(0, min(len(obs) - 4, 16), 1):
        p_now = obs[i].value
        p_yr = obs[min(i + 4, len(obs) - 1)].value
        if p_yr > 0:
            hist_yoy.append((p_now / p_yr - 1.0) * 100.0)

    if len(hist_yoy) < 3:
        # Below 1% YoY productivity growth is weak
        return -(yoy_pct - 1.0) / 0.5, 0.7

    # Negate: below-trend productivity → positive signal → True
    return -_zscore(yoy_pct, hist_yoy), 1.0


def _compute_participation_rate_falling(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """CIVPART: inverted z-score (falling participation = True)."""
    if len(obs) < _MIN_OBS["CIVPART"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:24])
    z = _zscore(current, values)
    return -z, 1.0  # Invert: below-average participation → True


def _compute_real_wage_growth_positive(
    wage_obs: list[FREDObservation],
    cpi_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Real wage growth = CES0500000003 YoY % - CPIAUCSL YoY %.
    Positive real wage growth → RealWageGrowthPositive = True.
    """
    if len(wage_obs) < 13 or len(cpi_obs) < 13:
        return None, 0.5

    # Wage YoY
    w_now = wage_obs[0].value
    w_yr_ago = wage_obs[12].value
    if w_yr_ago == 0:
        return None, 0.5
    wage_yoy = (w_now / w_yr_ago - 1.0) * 100.0

    # CPI YoY
    c_now = cpi_obs[0].value
    c_yr_ago = cpi_obs[12].value
    if c_yr_ago == 0:
        return None, 0.5
    cpi_yoy = (c_now / c_yr_ago - 1.0) * 100.0

    real_wage_growth = wage_yoy - cpi_yoy
    # Scale: 1% real wage growth → signal = 1.0
    return real_wage_growth / 1.0, 1.0


def _compute_tight_labor_market(
    unrate_obs: list[FREDObservation],
    jtsjol_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Composite: -UNRATE z-score + JTSJOL z-score.
    Low unemployment AND high openings = TightLaborMarket = True.
    """
    unrate_signal = 0.0
    jtsjol_signal = 0.0
    conf_count = 0

    if len(unrate_obs) >= 4:
        current = unrate_obs[0].value
        values = _values_from_obs(unrate_obs[:12])
        unrate_signal = -_zscore(current, values)  # Low unemployment → positive
        conf_count += 1

    if len(jtsjol_obs) >= 13:
        current = jtsjol_obs[0].value
        values = _values_from_obs(jtsjol_obs[:24])
        jtsjol_signal = _zscore(current, values)  # High openings → positive
        conf_count += 1

    if conf_count == 0:
        return None, 0.5

    composite = (unrate_signal + jtsjol_signal) / conf_count
    return composite, 1.0 if conf_count == 2 else 0.7


def compute_snapshot(
    observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> LaborMarketSnapshot:
    snap = LaborMarketSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    unrate_obs = observations.get("UNRATE", [])
    wage_obs = observations.get("CES0500000003", [])
    jtsjol_obs = observations.get("JTSJOL", [])
    cpi_obs = observations.get("CPIAUCSL", [])

    sig, conf = _compute_unemployment_rising(unrate_obs)
    _apply("UnemploymentRising", sig, conf, "p_unemployment_rising", "unemployment_rising")

    sig, conf = _compute_wage_inflation_persistent(wage_obs)
    _apply("WageInflationPersistent", sig, conf, "p_wage_inflation_persistent", "wage_inflation_persistent")

    sig, conf = _compute_job_openings_falling(jtsjol_obs)
    _apply("JobOpeningsFalling", sig, conf, "p_job_openings_falling", "job_openings_falling")

    sig, conf = _compute_layoff_cycle_beginning(observations.get("ICSA", []))
    _apply("LayoffCycleBeginning", sig, conf, "p_layoff_cycle_beginning", "layoff_cycle_beginning")

    sig, conf = _compute_labor_productivity_weak(observations.get("PRS85006092", []))
    _apply("LaborProductivityWeak", sig, conf, "p_labor_productivity_weak", "labor_productivity_weak")

    sig, conf = _compute_participation_rate_falling(observations.get("CIVPART", []))
    _apply("ParticipationRateFalling", sig, conf, "p_participation_rate_falling", "participation_rate_falling")

    sig, conf = _compute_real_wage_growth_positive(wage_obs, cpi_obs)
    _apply("RealWageGrowthPositive", sig, conf, "p_real_wage_growth_positive", "real_wage_growth_positive")

    sig, conf = _compute_tight_labor_market(unrate_obs, jtsjol_obs)
    _apply("TightLaborMarket", sig, conf, "p_tight_labor_market", "tight_labor_market")

    snap.confidence = confidence
    return snap


class LaborMarketPipeline:
    """Fetches FRED series and builds EvidenceRecords for labor-market-v1."""

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    async def fetch_evidence(self, target_date: Optional[date] = None) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: LaborMarketSnapshot) -> EvidenceRecord:
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
            _assignment("UnemploymentRising",       snapshot.unemployment_rising,       snapshot.p_unemployment_rising),
            _assignment("WageInflationPersistent",   snapshot.wage_inflation_persistent, snapshot.p_wage_inflation_persistent),
            _assignment("JobOpeningsFalling",        snapshot.job_openings_falling,      snapshot.p_job_openings_falling),
            _assignment("LayoffCycleBeginning",      snapshot.layoff_cycle_beginning,    snapshot.p_layoff_cycle_beginning),
            _assignment("LaborProductivityWeak",     snapshot.labor_productivity_weak,   snapshot.p_labor_productivity_weak),
            _assignment("ParticipationRateFalling",  snapshot.participation_rate_falling, snapshot.p_participation_rate_falling),
            _assignment("RealWageGrowthPositive",    snapshot.real_wage_growth_positive, snapshot.p_real_wage_growth_positive),
            _assignment("TightLaborMarket",          snapshot.tight_labor_market,        snapshot.p_tight_labor_market),
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
                "FRED:UNRATE+CES0500000003+JTSJOL+ICSA+PRS85006092+CIVPART+CPIAUCSL"
                f"@week-ending-{target_date}"
            ),
            confidence=overall_conf,
        )


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
