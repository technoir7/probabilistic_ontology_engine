"""
LaborMarketPipeline — FRED observations → EvidenceRecords for labor-market-v1.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.
A variable whose series has too little data is MISSING (D10), never a
middle reading.

UnemploymentRising
    Signal : (UNRATE latest - its 12-month mean) / 0.30  [positive = rising]

WageInflationPersistent
    Signal : CES0500000003 YoY % z-scored against its historical YoY rates

JobOpeningsFalling
    Signal : -JTSJOL 24-month z-score  [below-average openings → positive]

LayoffCycleBeginning
    Signal : ICSA 52-week rolling z-score

LaborProductivityWeak
    Signal : -(PRS85006092 YoY % z-score vs historical YoY)  [below trend → positive]

ParticipationRateFalling
    Signal : -CIVPART 24-month z-score  [below-average participation → positive]

RealWageGrowthPositive
    Signal : (CES0500000003 YoY % - CPIAUCSL YoY %) / 1.0
    high   : real wages up more than 0.5%; low: down more than 0.5%

TightLaborMarket
    Signal : mean of -UNRATE z-score and JTSJOL z-score (either alone when
             the other is unavailable)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from ....engine.schemas import (
    EvidenceRecord,
)
from ..domain import get_variables
from .fred_client import FREDClient, FREDObservation
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)

_MIN_OBS: dict[str, int] = {
    "UNRATE":        4,
    "CES0500000003": 13,   # 13 months for 12m YoY
    "JTSJOL":        13,
    "ICSA":          26,   # 26 weeks for z-score
    "PRS85006092":   5,    # 5 quarters for YoY trend
    "CIVPART":       13,
    "CPIAUCSL":      13,
}


# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class LaborMarketSnapshot:
    """
    Derived signals for one evidence week. *signals* holds each variable's
    signed signal (read as a level when the record is built); a variable
    without one is MISSING.
    """

    signals: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    target_date: Optional[date] = None


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
    """JTSJOL: inverted z-score (falling openings = JobOpeningsFalling high)."""
    if len(obs) < _MIN_OBS["JTSJOL"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:24])
    z = _zscore(current, values)
    return -z, 1.0  # Invert: below-average openings → high


def _compute_layoff_cycle_beginning(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """ICSA 52-week rolling z-score (elevated claims = LayoffCycleBeginning high)."""
    if len(obs) < _MIN_OBS["ICSA"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:52])
    return _zscore(current, values), 1.0


def _compute_labor_productivity_weak(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """PRS85006092 YoY below historical mean → LaborProductivityWeak high."""
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

    # Negate: below-trend productivity → positive signal
    return -_zscore(yoy_pct, hist_yoy), 1.0


def _compute_participation_rate_falling(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """CIVPART: inverted z-score (falling participation = high)."""
    if len(obs) < _MIN_OBS["CIVPART"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:24])
    z = _zscore(current, values)
    return -z, 1.0  # Invert: below-average participation → high


def _compute_real_wage_growth_positive(
    wage_obs: list[FREDObservation],
    cpi_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Real wage growth = CES0500000003 YoY % - CPIAUCSL YoY %.
    Positive real wage growth → RealWageGrowthPositive high.
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
    Low unemployment AND high openings = TightLaborMarket high.
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

    def _apply(var_name: str, sig: Optional[float], conf: float) -> None:
        confidence[var_name] = conf
        if sig is not None:
            snap.signals[var_name] = sig

    unrate_obs = observations.get("UNRATE", [])
    wage_obs = observations.get("CES0500000003", [])
    jtsjol_obs = observations.get("JTSJOL", [])
    cpi_obs = observations.get("CPIAUCSL", [])

    sig, conf = _compute_unemployment_rising(unrate_obs)
    _apply("UnemploymentRising", sig, conf)

    sig, conf = _compute_wage_inflation_persistent(wage_obs)
    _apply("WageInflationPersistent", sig, conf)

    sig, conf = _compute_job_openings_falling(jtsjol_obs)
    _apply("JobOpeningsFalling", sig, conf)

    sig, conf = _compute_layoff_cycle_beginning(observations.get("ICSA", []))
    _apply("LayoffCycleBeginning", sig, conf)

    sig, conf = _compute_labor_productivity_weak(observations.get("PRS85006092", []))
    _apply("LaborProductivityWeak", sig, conf)

    sig, conf = _compute_participation_rate_falling(observations.get("CIVPART", []))
    _apply("ParticipationRateFalling", sig, conf)

    sig, conf = _compute_real_wage_growth_positive(wage_obs, cpi_obs)
    _apply("RealWageGrowthPositive", sig, conf)

    sig, conf = _compute_tight_labor_market(unrate_obs, jtsjol_obs)
    _apply("TightLaborMarket", sig, conf)

    snap.confidence = confidence
    return snap


class LaborMarketPipeline:
    """Fetches FRED series and builds EvidenceRecords for labor-market-v1."""

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: LaborMarketSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="labor-market-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="FRED:UNRATE+CES0500000003+JTSJOL+ICSA+PRS85006092+CIVPART+CPIAUCSL"
            f"@week-ending-{target_date}",
        )


