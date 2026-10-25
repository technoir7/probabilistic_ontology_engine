"""
CreditCyclePipeline — FRED observations → EvidenceRecords for credit-cycle-v1.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.
A variable whose series has too little data is MISSING (D10), never a
middle reading.

HYSpreadElevated
    Signal : BAMLH0A0HYM2 52-week z-score

LeveragedLoanStress
    Signal : DRTSCILM historical z-score (higher = more tightening/delinquency)

CorporateDefaultRisk
    Signal : (BAMLH0A0HYM2 level - 5.5) / 0.5  [5.5% absolute threshold]
    high   : above 5.75%; low: below 5.25%

CreditImpulseNegative
    Signal : -(TOTCI 3-month growth %) * 10.0  [negative growth → positive signal]

BankLendingTightening
    Signal : DRTSCILM z-score * 0.8 (same series as LeveragedLoanStress, softer)

InvestmentGradeSpread
    Signal : BAMLC0A0CM 52-week z-score

HighYieldIssuanceFalling
    Signal : BAMLH0A0HYM2 3-month momentum * 2.0 (recent - prior; rising = issuance falling)

RefinancingStress
    Signal : (DGS5 + BAMLH0A0HYM2) / 2 historical z-score
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


from ....engine.schemas import (
    EvidenceRecord,
)
from ..domain import get_variables
from .fred_client import FREDClient, FREDObservation
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)

_MIN_OBS: dict[str, int] = {
    "BAMLH0A0HYM2": 52,
    "DRTSCILM":     5,    # quarterly; need 5 quarters for z-score
    "TOTCI":        2,    # a value now and one at least 3 months earlier
    "BAMLC0A0CM":   52,
    "DGS5":         52,
}


# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class CreditCycleSnapshot:
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


def _compute_hy_spread_elevated(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    if len(obs) < _MIN_OBS["BAMLH0A0HYM2"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    return _zscore(current, values), 1.0


def _compute_leveraged_loan_stress(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DRTSCILM z-score vs historical (higher = more tightening/delinquency)."""
    if len(obs) < _MIN_OBS["DRTSCILM"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs)
    return _zscore(current, values), 1.0


def _compute_corporate_default_risk(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """BAMLH0A0HYM2 level threshold: > 5.5% OAS = elevated default risk."""
    if not obs:
        return None, 0.5
    current = obs[0].value
    return (current - 5.5) / 0.5, 1.0


def _compute_credit_impulse_negative(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """TOTCI: negative 3-month growth rate → CreditImpulseNegative high.

    Found by date, not position: TOTCI is weekly, so three observations
    back would be three weeks.
    """
    if len(obs) < _MIN_OBS["TOTCI"]:
        return None, 0.5
    current = obs[0].value
    quarter_back = obs[0].obs_date - timedelta(days=91)
    three_m_ago = next((o.value for o in obs if o.obs_date <= quarter_back), None)
    if three_m_ago is None or three_m_ago == 0:
        return None, 0.5
    growth_pct = (current / three_m_ago - 1.0) * 100.0
    # Negative growth → positive signal
    return -growth_pct * 10.0, 1.0


def _compute_bank_lending_tightening(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DRTSCILM z-score with softer threshold (scale 0.8)."""
    if len(obs) < _MIN_OBS["DRTSCILM"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs)
    return _zscore(current, values) * 0.8, 1.0


def _compute_investment_grade_spread(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """BAMLC0A0CM 52-week z-score."""
    if len(obs) < _MIN_OBS["BAMLC0A0CM"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    return _zscore(current, values), 1.0


def _compute_hy_issuance_falling(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """BAMLH0A0HYM2 3-month momentum: rising spreads = issuance falling."""
    if len(obs) < 60:
        return None, 0.5
    current = obs[0].value
    three_m_ago = obs[min(60, len(obs) - 1)].value  # ~60 trading days
    momentum = current - three_m_ago  # positive = spreads widening = issuance falling
    return momentum * 2.0, 1.0


def _compute_refinancing_stress(
    dgs5_obs: list[FREDObservation],
    hy_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """DGS5 + BAMLH0A0HYM2 composite z-score."""
    if len(dgs5_obs) < _MIN_OBS["DGS5"] or len(hy_obs) < _MIN_OBS["BAMLH0A0HYM2"]:
        return None, 0.5

    # Pair by date: the two series have different holiday calendars, so pairing
    # by position drifts by a day after every date only one of them has.
    hy_by_date = {o.obs_date: o.value for o in hy_obs}
    composite_values = [
        (o.value + hy_by_date[o.obs_date]) / 2.0
        for o in dgs5_obs
        if o.obs_date in hy_by_date
    ][:260]
    if not composite_values:
        return None, 0.5
    current = composite_values[0]
    return _zscore(current, composite_values), 1.0


def compute_snapshot(
    observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> CreditCycleSnapshot:
    snap = CreditCycleSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float) -> None:
        confidence[var_name] = conf
        if sig is not None:
            snap.signals[var_name] = sig

    hy_obs = observations.get("BAMLH0A0HYM2", [])
    drtscilm_obs = observations.get("DRTSCILM", [])

    sig, conf = _compute_hy_spread_elevated(hy_obs)
    _apply("HYSpreadElevated", sig, conf)

    sig, conf = _compute_leveraged_loan_stress(drtscilm_obs)
    _apply("LeveragedLoanStress", sig, conf)

    sig, conf = _compute_corporate_default_risk(hy_obs)
    _apply("CorporateDefaultRisk", sig, conf)

    sig, conf = _compute_credit_impulse_negative(observations.get("TOTCI", []))
    _apply("CreditImpulseNegative", sig, conf)

    sig, conf = _compute_bank_lending_tightening(drtscilm_obs)
    _apply("BankLendingTightening", sig, conf)

    sig, conf = _compute_investment_grade_spread(observations.get("BAMLC0A0CM", []))
    _apply("InvestmentGradeSpread", sig, conf)

    sig, conf = _compute_hy_issuance_falling(hy_obs)
    _apply("HighYieldIssuanceFalling", sig, conf)

    sig, conf = _compute_refinancing_stress(observations.get("DGS5", []), hy_obs)
    _apply("RefinancingStress", sig, conf)

    snap.confidence = confidence
    return snap


class CreditCyclePipeline:
    """Fetches FRED series and builds EvidenceRecords for credit-cycle-v1."""

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: CreditCycleSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="credit-cycle-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="FRED:BAMLH0A0HYM2+DRTSCILM+TOTCI+BAMLC0A0CM+DGS5"
            f"@week-ending-{target_date}",
        )


