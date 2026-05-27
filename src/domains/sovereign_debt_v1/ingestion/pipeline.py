"""
SovereignDebtPipeline — FRED observations → EvidenceRecords.

Variable calibrations (all SOFT_OBSERVED, sigmoid-based)
----------------------------------------------------------
USYieldSpiking
    Signal  : DGS10 52-week rolling z-score
    P(True) : sigmoid(z_score)
    At z=0: P≈0.50; z=+2: P≈0.88 (yields spiking)

SpreadWidening
    Signal  : BAMLH0A0HYM2 52-week rolling z-score
    P(True) : sigmoid(z_score)

DollarStrengthening
    Signal  : -DEXUSEU 52-week z-score  (lower EUR/USD = stronger USD)
    P(True) : sigmoid(-z_score)
    At z=-1: P≈0.73 (USD strong)

FedBalanceSheetShrinking
    Signal  : -(WALCL 13w change %) * 5.0
    P(True) : sigmoid(signal)
    At -2%: P≈0.99 (active QT)

EMStressElevated
    Signal  : DTWEXBGS 52-week rolling z-score
    P(True) : sigmoid(z_score)
    At z=+1: P≈0.73 (broad dollar elevated → EM stress)

FiscalDominanceRisk
    Signal  : (GFDEBTN YoY growth - historical mean) / historical std
    P(True) : sigmoid(signal)

CreditDefaultRisk
    Signal  : (BAMLH0A0HYM2 level - 6.0) / 0.5
    P(True) : sigmoid(signal)
    At 6.0%: P≈0.50; at 7.0%: P≈0.88; at 5.0%: P≈0.12

GlobalLiquidityContracting
    Signal  : average of WALCL contraction signal + M2SL contraction signal
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
from .fred_client import FREDClient, FREDObservation

logger = logging.getLogger(__name__)

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99

_MIN_OBS: dict[str, int] = {
    "DGS10":        52,   # 52 trading days for z-score
    "BAMLH0A0HYM2": 52,
    "DEXUSEU":      52,
    "WALCL":        14,   # 14 weeks for 13w change
    "DTWEXBGS":     26,   # 26 weeks for z-score
    "GFDEBTN":      5,    # 5 quarters for YoY + trend
    "M2SL":         4,    # 4 months for 3m change
}


@dataclass
class SovereignDebtSnapshot:
    """Derived signals and soft probabilities for one evidence week."""

    # Soft probabilities
    p_us_yield_spiking: float = 0.5
    p_spread_widening: float = 0.5
    p_dollar_strengthening: float = 0.5
    p_fed_balance_sheet_shrinking: float = 0.5
    p_em_stress_elevated: float = 0.5
    p_fiscal_dominance_risk: float = 0.5
    p_credit_default_risk: float = 0.5
    p_global_liquidity_contracting: float = 0.5

    # Hard MAP booleans
    us_yield_spiking: bool = False
    spread_widening: bool = False
    dollar_strengthening: bool = False
    fed_balance_sheet_shrinking: bool = False
    em_stress_elevated: bool = False
    fiscal_dominance_risk: bool = False
    credit_default_risk: bool = False
    global_liquidity_contracting: bool = False

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


def _values_from_obs(obs: list[FREDObservation]) -> list[float]:
    return [o.value for o in obs]


# ---------------------------------------------------------------------------
# Per-variable signal computation
# ---------------------------------------------------------------------------

def _compute_us_yield_spiking(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DGS10 52-week rolling z-score."""
    if len(obs) < _MIN_OBS["DGS10"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    return _zscore(current, values), 1.0


def _compute_spread_widening(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """BAMLH0A0HYM2 52-week rolling z-score."""
    if len(obs) < _MIN_OBS["BAMLH0A0HYM2"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    return _zscore(current, values), 1.0


def _compute_dollar_strengthening(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DEXUSEU inverted 52-week z-score (lower EUR/USD = stronger USD = True)."""
    if len(obs) < _MIN_OBS["DEXUSEU"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    # Negate so that falling DEXUSEU (stronger USD) → positive signal
    return -_zscore(current, values), 1.0


def _compute_fed_balance_sheet_shrinking(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """WALCL 13-week change: negative change → FedBalanceSheetShrinking = True."""
    if len(obs) < _MIN_OBS["WALCL"]:
        return None, 0.5
    current = obs[0].value
    week_13 = obs[13].value if len(obs) > 13 else obs[-1].value
    if week_13 == 0:
        return None, 0.5
    change_pct = (current / week_13 - 1.0) * 100.0
    signal = -change_pct * 5.0
    return signal, 1.0


def _compute_em_stress_elevated(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DTWEXBGS 52-week rolling z-score (rising broad dollar = EM stress)."""
    if len(obs) < _MIN_OBS["DTWEXBGS"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:100])
    return _zscore(current, values), 1.0


def _compute_fiscal_dominance_risk(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """GFDEBTN: YoY growth rate z-scored vs historical growth rates."""
    if len(obs) < _MIN_OBS["GFDEBTN"]:
        return None, 0.5
    if len(obs) < 5:
        return None, 0.5
    # YoY change (4 quarters): obs[0] vs obs[4]
    current = obs[0].value
    year_ago = obs[min(4, len(obs) - 1)].value
    if year_ago == 0:
        return None, 0.5
    yoy_growth_pct = (current / year_ago - 1.0) * 100.0
    # Historical growth rates for z-score
    hist_growths: list[float] = []
    for i in range(min(len(obs) - 4, 12)):
        p_now = obs[i].value
        p_yr_ago = obs[min(i + 4, len(obs) - 1)].value
        if p_yr_ago > 0:
            hist_growths.append((p_now / p_yr_ago - 1.0) * 100.0)
    if len(hist_growths) < 3:
        # Use simple threshold: >5% YoY debt growth is concerning
        signal = (yoy_growth_pct - 5.0) / 1.0
        return signal, 0.7
    return _zscore(yoy_growth_pct, hist_growths), 1.0


def _compute_credit_default_risk(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """BAMLH0A0HYM2 absolute level threshold: > 6.0% OAS = elevated default risk."""
    if not obs:
        return None, 0.5
    current = obs[0].value
    # Threshold at 6.0%; scale 0.5 per percentage point
    signal = (current - 6.0) / 0.5
    return signal, 1.0


def _compute_global_liquidity_contracting(
    walcl_obs: list[FREDObservation],
    m2sl_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Composite of WALCL 13w change + M2SL 3m change.
    Both contracting → GlobalLiquidityContracting = True.
    """
    walcl_signal = 0.0
    walcl_conf = 0.5
    m2sl_signal = 0.0
    m2sl_conf = 0.5

    if len(walcl_obs) >= 14:
        current = walcl_obs[0].value
        week_13 = walcl_obs[13].value if len(walcl_obs) > 13 else walcl_obs[-1].value
        if week_13 > 0:
            change_pct = (current / week_13 - 1.0) * 100.0
            walcl_signal = -change_pct * 5.0
            walcl_conf = 1.0

    if len(m2sl_obs) >= 4:
        current = m2sl_obs[0].value
        three_m_ago = m2sl_obs[3].value if len(m2sl_obs) > 3 else m2sl_obs[-1].value
        if three_m_ago > 0:
            change_pct = (current / three_m_ago - 1.0) * 100.0
            # Scale: -1% M2 3m → signal ≈ +5
            m2sl_signal = -change_pct * 5.0
            m2sl_conf = 1.0

    if walcl_conf == 0.5 and m2sl_conf == 0.5:
        return None, 0.5

    # Weighted composite
    total_conf = walcl_conf + m2sl_conf
    composite = (walcl_signal * walcl_conf + m2sl_signal * m2sl_conf) / total_conf
    conf = max(walcl_conf, m2sl_conf)
    return composite, conf


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def compute_snapshot(
    observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> SovereignDebtSnapshot:
    snap = SovereignDebtSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    # USYieldSpiking
    sig, conf = _compute_us_yield_spiking(observations.get("DGS10", []))
    _apply("USYieldSpiking", sig, conf, "p_us_yield_spiking", "us_yield_spiking")

    # SpreadWidening
    sig, conf = _compute_spread_widening(observations.get("BAMLH0A0HYM2", []))
    _apply("SpreadWidening", sig, conf, "p_spread_widening", "spread_widening")

    # DollarStrengthening
    sig, conf = _compute_dollar_strengthening(observations.get("DEXUSEU", []))
    _apply("DollarStrengthening", sig, conf, "p_dollar_strengthening", "dollar_strengthening")

    # FedBalanceSheetShrinking
    sig, conf = _compute_fed_balance_sheet_shrinking(observations.get("WALCL", []))
    _apply("FedBalanceSheetShrinking", sig, conf, "p_fed_balance_sheet_shrinking", "fed_balance_sheet_shrinking")

    # EMStressElevated
    sig, conf = _compute_em_stress_elevated(observations.get("DTWEXBGS", []))
    _apply("EMStressElevated", sig, conf, "p_em_stress_elevated", "em_stress_elevated")

    # FiscalDominanceRisk
    sig, conf = _compute_fiscal_dominance_risk(observations.get("GFDEBTN", []))
    _apply("FiscalDominanceRisk", sig, conf, "p_fiscal_dominance_risk", "fiscal_dominance_risk")

    # CreditDefaultRisk
    sig, conf = _compute_credit_default_risk(observations.get("BAMLH0A0HYM2", []))
    _apply("CreditDefaultRisk", sig, conf, "p_credit_default_risk", "credit_default_risk")

    # GlobalLiquidityContracting
    sig, conf = _compute_global_liquidity_contracting(
        observations.get("WALCL", []),
        observations.get("M2SL", []),
    )
    _apply("GlobalLiquidityContracting", sig, conf, "p_global_liquidity_contracting", "global_liquidity_contracting")

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class SovereignDebtPipeline:
    """Fetches FRED series and builds EvidenceRecords for sovereign-debt-v1."""

    def __init__(self, fred: FREDClient) -> None:
        self._fred = fred

    async def fetch_evidence(
        self,
        target_date: Optional[date] = None,
    ) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: SovereignDebtSnapshot) -> EvidenceRecord:
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
            _assignment("USYieldSpiking",            snapshot.us_yield_spiking,            snapshot.p_us_yield_spiking),
            _assignment("SpreadWidening",             snapshot.spread_widening,             snapshot.p_spread_widening),
            _assignment("DollarStrengthening",        snapshot.dollar_strengthening,        snapshot.p_dollar_strengthening),
            _assignment("FedBalanceSheetShrinking",   snapshot.fed_balance_sheet_shrinking, snapshot.p_fed_balance_sheet_shrinking),
            _assignment("EMStressElevated",           snapshot.em_stress_elevated,          snapshot.p_em_stress_elevated),
            _assignment("FiscalDominanceRisk",        snapshot.fiscal_dominance_risk,       snapshot.p_fiscal_dominance_risk),
            _assignment("CreditDefaultRisk",          snapshot.credit_default_risk,         snapshot.p_credit_default_risk),
            _assignment("GlobalLiquidityContracting", snapshot.global_liquidity_contracting, snapshot.p_global_liquidity_contracting),
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
                "FRED:DGS10+BAMLH0A0HYM2+DEXUSEU+WALCL+DTWEXBGS+GFDEBTN+M2SL"
                f"@week-ending-{target_date}"
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
