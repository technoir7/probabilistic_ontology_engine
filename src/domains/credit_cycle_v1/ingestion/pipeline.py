"""
CreditCyclePipeline — FRED observations → EvidenceRecords for credit-cycle-v1.

Variable calibrations
----------------------
HYSpreadElevated
    Signal  : BAMLH0A0HYM2 52-week z-score
    P(True) : sigmoid(z_score)

LeveragedLoanStress
    Signal  : DRTSCILM historical z-score (higher = more tightening/delinquency)
    P(True) : sigmoid(z_score)

CorporateDefaultRisk
    Signal  : (BAMLH0A0HYM2 level - 5.5) / 0.5
    P(True) : sigmoid(signal)  [5.5% absolute threshold]

CreditImpulseNegative
    Signal  : -(TOTCI 3-month growth %) * 10.0  [negative growth → positive signal]
    P(True) : sigmoid(signal)

BankLendingTightening
    Signal  : DRTSCILM z-score (same series as LeveragedLoanStress; slightly different scale)
    P(True) : sigmoid(z_score * 0.8)  [softer threshold]

InvestmentGradeSpread
    Signal  : BAMLC0A0CM 52-week z-score
    P(True) : sigmoid(z_score)

HighYieldIssuanceFalling
    Signal  : BAMLH0A0HYM2 3-month momentum (recent - prior; rising = issuance falling)
    P(True) : sigmoid(momentum * 2.0)

RefinancingStress
    Signal  : (DGS5 + BAMLH0A0HYM2) / 2 vs historical composite z-score
    P(True) : sigmoid(z_score)
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
    "BAMLH0A0HYM2": 52,
    "DRTSCILM":     5,    # quarterly; need 5 quarters for z-score
    "TOTCI":        4,    # 4 months for 3m growth
    "BAMLC0A0CM":   52,
    "DGS5":         52,
}


@dataclass
class CreditCycleSnapshot:
    p_hy_spread_elevated: float = 0.5
    p_leveraged_loan_stress: float = 0.5
    p_corporate_default_risk: float = 0.5
    p_credit_impulse_negative: float = 0.5
    p_bank_lending_tightening: float = 0.5
    p_investment_grade_spread: float = 0.5
    p_high_yield_issuance_falling: float = 0.5
    p_refinancing_stress: float = 0.5

    hy_spread_elevated: bool = False
    leveraged_loan_stress: bool = False
    corporate_default_risk: bool = False
    credit_impulse_negative: bool = False
    bank_lending_tightening: bool = False
    investment_grade_spread: bool = False
    high_yield_issuance_falling: bool = False
    refinancing_stress: bool = False

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
    """TOTCI: negative 3-month growth rate → CreditImpulseNegative = True."""
    if len(obs) < _MIN_OBS["TOTCI"]:
        return None, 0.5
    current = obs[0].value
    three_m_ago = obs[min(3, len(obs) - 1)].value
    if three_m_ago == 0:
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

    # Build composite series (shorter of the two)
    n = min(len(dgs5_obs), len(hy_obs), 260)
    composite_values = [
        (dgs5_obs[i].value + hy_obs[i].value) / 2.0
        for i in range(n)
        if i < len(dgs5_obs) and i < len(hy_obs)
    ]
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

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    hy_obs = observations.get("BAMLH0A0HYM2", [])
    drtscilm_obs = observations.get("DRTSCILM", [])

    sig, conf = _compute_hy_spread_elevated(hy_obs)
    _apply("HYSpreadElevated", sig, conf, "p_hy_spread_elevated", "hy_spread_elevated")

    sig, conf = _compute_leveraged_loan_stress(drtscilm_obs)
    _apply("LeveragedLoanStress", sig, conf, "p_leveraged_loan_stress", "leveraged_loan_stress")

    sig, conf = _compute_corporate_default_risk(hy_obs)
    _apply("CorporateDefaultRisk", sig, conf, "p_corporate_default_risk", "corporate_default_risk")

    sig, conf = _compute_credit_impulse_negative(observations.get("TOTCI", []))
    _apply("CreditImpulseNegative", sig, conf, "p_credit_impulse_negative", "credit_impulse_negative")

    sig, conf = _compute_bank_lending_tightening(drtscilm_obs)
    _apply("BankLendingTightening", sig, conf, "p_bank_lending_tightening", "bank_lending_tightening")

    sig, conf = _compute_investment_grade_spread(observations.get("BAMLC0A0CM", []))
    _apply("InvestmentGradeSpread", sig, conf, "p_investment_grade_spread", "investment_grade_spread")

    sig, conf = _compute_hy_issuance_falling(hy_obs)
    _apply("HighYieldIssuanceFalling", sig, conf, "p_high_yield_issuance_falling", "high_yield_issuance_falling")

    sig, conf = _compute_refinancing_stress(observations.get("DGS5", []), hy_obs)
    _apply("RefinancingStress", sig, conf, "p_refinancing_stress", "refinancing_stress")

    snap.confidence = confidence
    return snap


class CreditCyclePipeline:
    """Fetches FRED series and builds EvidenceRecords for credit-cycle-v1."""

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    async def fetch_evidence(self, target_date: Optional[date] = None) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: CreditCycleSnapshot) -> EvidenceRecord:
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
            _assignment("HYSpreadElevated",         snapshot.hy_spread_elevated,          snapshot.p_hy_spread_elevated),
            _assignment("LeveragedLoanStress",       snapshot.leveraged_loan_stress,       snapshot.p_leveraged_loan_stress),
            _assignment("CorporateDefaultRisk",      snapshot.corporate_default_risk,      snapshot.p_corporate_default_risk),
            _assignment("CreditImpulseNegative",     snapshot.credit_impulse_negative,     snapshot.p_credit_impulse_negative),
            _assignment("BankLendingTightening",     snapshot.bank_lending_tightening,     snapshot.p_bank_lending_tightening),
            _assignment("InvestmentGradeSpread",     snapshot.investment_grade_spread,     snapshot.p_investment_grade_spread),
            _assignment("HighYieldIssuanceFalling",  snapshot.high_yield_issuance_falling, snapshot.p_high_yield_issuance_falling),
            _assignment("RefinancingStress",         snapshot.refinancing_stress,          snapshot.p_refinancing_stress),
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
                "FRED:BAMLH0A0HYM2+DRTSCILM+TOTCI+BAMLC0A0CM+DGS5"
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
