"""
SovereignDebtPipeline — FRED observations → EvidenceRecords.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.
A variable whose series has too little data is MISSING (decision D10),
never a middle reading.

USYieldSpiking
    Signal : DGS10 52-week rolling z-score

SpreadWidening
    Signal : BAMLH0A0HYM2 52-week rolling z-score

DollarStrengthening
    Signal : -DEXUSEU 52-week z-score  (lower EUR/USD = stronger USD)

FedBalanceSheetShrinking
    Signal : -(WALCL 13w change %) * 5.0
    high   : balance sheet shrinking by more than 0.1%; low: growing by more

EMStressElevated
    Signal : DTWEXBGS 52-week rolling z-score

FiscalDominanceRisk
    Signal : (GFDEBTN YoY growth - historical mean) / historical std

CreditDefaultRisk
    Signal : (BAMLH0A0HYM2 level - 6.0) / 0.5
    high   : above 6.25%; low: below 5.75%

GlobalLiquidityContracting
    Signal : confidence-weighted average of the WALCL and M2SL contraction
             signals
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
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
    "DGS10":        52,   # 52 trading days for z-score
    "BAMLH0A0HYM2": 52,
    "DEXUSEU":      52,
    "WALCL":        14,   # 14 weeks for 13w change
    "DTWEXBGS":     26,   # 26 weeks for z-score
    "GFDEBTN":      5,    # 5 quarters for YoY + trend
    "M2SL":         4,    # 4 months for 3m change
}


# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class SovereignDebtSnapshot:
    """
    Derived signals for one evidence week.

    *signals* holds each variable's signed signal (read as a level when the
    record is built); a variable without one is MISSING.
    """

    signals: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)

    target_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


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
    """DEXUSEU inverted 52-week z-score (lower EUR/USD = stronger USD = positive)."""
    if len(obs) < _MIN_OBS["DEXUSEU"]:
        return None, 0.5
    current = obs[0].value
    values = _values_from_obs(obs[:260])
    # Negate so that falling DEXUSEU (stronger USD) → positive signal
    return -_zscore(current, values), 1.0


def _compute_fed_balance_sheet_shrinking(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """WALCL 13-week change: a shrinking balance sheet gives a positive signal."""
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
    Both contracting → a positive signal. The mean of the parts that have
    data: a missing part is not a zero reading. Confidence is the share of
    the two that have data.
    """
    parts: list[float] = []

    if len(walcl_obs) >= 14:
        current = walcl_obs[0].value
        week_13 = walcl_obs[13].value
        if week_13 > 0:
            parts.append(-(current / week_13 - 1.0) * 100.0 * 5.0)

    if len(m2sl_obs) >= 4:
        current = m2sl_obs[0].value
        three_m_ago = m2sl_obs[3].value
        if three_m_ago > 0:
            # Scale: -1% M2 3m → signal ≈ +5
            parts.append(-(current / three_m_ago - 1.0) * 100.0 * 5.0)

    if not parts:
        return None, 0.5
    return sum(parts) / len(parts), len(parts) / 2


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def compute_snapshot(
    observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> SovereignDebtSnapshot:
    snap = SovereignDebtSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def take(name: str, signal: Optional[float], conf: float) -> None:
        confidence[name] = conf
        if signal is not None:
            snap.signals[name] = signal

    take("USYieldSpiking", *_compute_us_yield_spiking(observations.get("DGS10", [])))
    take("SpreadWidening", *_compute_spread_widening(observations.get("BAMLH0A0HYM2", [])))
    take("DollarStrengthening", *_compute_dollar_strengthening(observations.get("DEXUSEU", [])))
    take("FedBalanceSheetShrinking", *_compute_fed_balance_sheet_shrinking(observations.get("WALCL", [])))
    take("EMStressElevated", *_compute_em_stress_elevated(observations.get("DTWEXBGS", [])))
    take("FiscalDominanceRisk", *_compute_fiscal_dominance_risk(observations.get("GFDEBTN", [])))
    take("CreditDefaultRisk", *_compute_credit_default_risk(observations.get("BAMLH0A0HYM2", [])))
    take("GlobalLiquidityContracting", *_compute_global_liquidity_contracting(
        observations.get("WALCL", []),
        observations.get("M2SL", []),
    ))

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
        target_date: date,
    ) -> EvidenceRecord:
        observations = await self._fred.fetch_all_series(end_date=target_date)
        snapshot = compute_snapshot(observations, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: SovereignDebtSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="sovereign-debt-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="FRED:DGS10+BAMLH0A0HYM2+DEXUSEU+WALCL+DTWEXBGS+GFDEBTN+M2SL"
            f"@week-ending-{target_date}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


