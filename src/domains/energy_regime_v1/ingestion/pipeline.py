"""
EnergyRegimePipeline — FRED + yfinance observations → EvidenceRecords.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed
exactly (sources.grades): low below -0.5, mid within ±0.5, high above +0.5.
A variable whose series has too little data is MISSING (D10), never a
middle reading.

OilPriceSurge
    Signal : CL=F 13-week return z-score vs historical 13-week returns

NatGasPriceSurge
    Signal : NG=F 13-week return z-score vs historical

EnergyEquityMomentum
    Signal : XLE 13-week return z-score vs historical

OPECSupplyConstraint
    Signal : DCOILWTICO (FRED) 13-week momentum z-score

RenewablesDisplacement
    Signal : ICLN/XLE ratio 52-week z-score

EnergyInflationPersistent
    Signal : (CPIENGSL 12m YoY % - 5.0) / 1.5  [5% threshold, 1.5pp scale]
    high   : above 5.75%; low: below 4.25%

GeopoliticalRiskElevated
    Signal : DCOILWTICO 90-day return volatility z-score vs historical volatility

DemandDestructionRisk
    Signal : mean of INDPRO 3m decline and UNRATE 3m rise, each scaled
             (either alone when the other is unavailable)
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
from .yfinance_client import EnergyYFinanceClient, YFObservation
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)

# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class EnergyRegimeSnapshot:
    """
    Derived signals for one evidence week. *signals* holds each variable's
    signed signal (read as a level when the record is built); a variable
    without one is MISSING.
    """

    signals: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    target_date: Optional[date] = None


def _compute_13w_return_zscore(obs: list[YFObservation]) -> tuple[Optional[float], float]:
    """
    Compute the 13-week return for the most recent observation and
    z-score it against historical 13-week returns in the series.

    Requires at least 91 observations (13 weeks of daily data + history).
    """
    if len(obs) < 91:
        return None, 0.5

    current_price = obs[0].close_price
    price_13w_ago = obs[min(91, len(obs) - 1)].close_price
    if price_13w_ago <= 0:
        return None, 0.5

    current_return = (current_price / price_13w_ago - 1.0) * 100.0

    historical_returns: list[float] = []
    step = 7
    for i in range(0, min(len(obs) - 91, 365), step):
        p_now = obs[i].close_price
        p_13w = obs[min(i + 91, len(obs) - 1)].close_price
        if p_13w > 0:
            historical_returns.append((p_now / p_13w - 1.0) * 100.0)

    if len(historical_returns) < 10:
        signal = current_return / 10.0
        return signal, 0.7

    return _zscore(current_return, historical_returns), 1.0


def _compute_opec_supply_constraint(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """
    DCOILWTICO 13-week momentum z-score.
    Positive momentum (prices trending up) = supply constrained.
    """
    if len(obs) < 91:
        return None, 0.5

    current = obs[0].value
    week_13_ago = obs[min(91, len(obs) - 1)].value
    if week_13_ago <= 0:
        return None, 0.5

    momentum = (current / week_13_ago - 1.0) * 100.0

    # Z-score vs historical 13-week momenta
    hist: list[float] = []
    for i in range(0, min(len(obs) - 91, 365), 7):
        p_now = obs[i].value
        p_13w = obs[min(i + 91, len(obs) - 1)].value
        if p_13w > 0:
            hist.append((p_now / p_13w - 1.0) * 100.0)

    if len(hist) < 10:
        return momentum / 10.0, 0.7

    return _zscore(momentum, hist), 1.0


def _compute_renewables_displacement(
    icln_obs: list[YFObservation],
    xle_obs: list[YFObservation],
) -> tuple[Optional[float], float]:
    """
    ICLN/XLE price ratio 52-week z-score.
    Rising ratio = renewables outperforming = RenewablesDisplacement high.
    """
    if len(icln_obs) < 52 or len(xle_obs) < 52:
        return None, 0.5

    # Build aligned ratio series using the shorter dataset
    n = min(len(icln_obs), len(xle_obs), 260)
    ratios: list[float] = []
    for i in range(n):
        xle_price = xle_obs[i].close_price if i < len(xle_obs) else None
        icln_price = icln_obs[i].close_price if i < len(icln_obs) else None
        if xle_price and icln_price and xle_price > 0:
            ratios.append(icln_price / xle_price)

    if len(ratios) < 52:
        return None, 0.5

    current_ratio = ratios[0]
    return _zscore(current_ratio, ratios), 1.0


def _compute_energy_inflation_persistent(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """CPIENGSL 12-month YoY % change. Threshold: 5%."""
    if len(obs) < 13:
        return None, 0.5
    latest = obs[0].value
    year_ago = obs[12].value
    if year_ago == 0:
        return None, 0.5
    yoy_pct = (latest / year_ago - 1.0) * 100.0
    return (yoy_pct - 5.0) / 1.5, 1.0


def _compute_geopolitical_risk(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """
    DCOILWTICO 90-day return volatility z-score.
    High vol = geopolitical uncertainty premium.
    """
    if len(obs) < 90:
        return None, 0.5

    # Daily returns for rolling 90-day window
    returns_90 = []
    for i in range(min(90, len(obs)) - 1):
        if obs[i + 1].value > 0:
            returns_90.append((obs[i].value / obs[i + 1].value - 1.0) * 100.0)

    if len(returns_90) < 20:
        return None, 0.5

    vol_90 = float(np.std(returns_90, ddof=1)) if len(returns_90) > 1 else 0.0

    # Historical volatility distribution using rolling 90-day vols
    hist_vols: list[float] = []
    step = 30  # check every 30 days
    for start_i in range(90, min(len(obs) - 90, 400), step):
        hist_returns = []
        for i in range(start_i, min(start_i + 90, len(obs)) - 1):
            if obs[i + 1].value > 0:
                hist_returns.append((obs[i].value / obs[i + 1].value - 1.0) * 100.0)
        if len(hist_returns) > 20:
            hist_vols.append(float(np.std(hist_returns, ddof=1)))

    if len(hist_vols) < 3:
        # Fallback: compare to 1% daily vol as benchmark
        return (vol_90 - 1.5) / 0.5, 0.7

    return _zscore(vol_90, hist_vols), 1.0


def _compute_demand_destruction_risk(
    indpro_obs: list[FREDObservation],
    unrate_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """
    Composite of INDPRO decline + UNRATE rise.
    Both negative for economy → DemandDestructionRisk high.
    """
    indpro_signal = 0.0
    unrate_signal = 0.0
    conf_sum = 0

    if len(indpro_obs) >= 4:
        current = indpro_obs[0].value
        three_m_ago = indpro_obs[3].value if len(indpro_obs) > 3 else indpro_obs[-1].value
        if three_m_ago > 0:
            growth_pct = (current / three_m_ago - 1.0) * 100.0
            # Negative growth → positive signal (demand destruction)
            indpro_signal = -growth_pct * 5.0
            conf_sum += 1

    if len(unrate_obs) >= 4:
        current = unrate_obs[0].value
        three_m_ago = unrate_obs[min(3, len(unrate_obs) - 1)].value
        # Rising unemployment → demand destruction
        unrate_signal = (current - three_m_ago) / 0.5 * 2.0
        conf_sum += 1

    if conf_sum == 0:
        return None, 0.5

    composite = (indpro_signal + unrate_signal) / conf_sum
    return composite, 1.0 if conf_sum == 2 else 0.7


def compute_snapshot(
    yf_observations: dict[str, list[YFObservation]],
    fred_observations: dict[str, list[FREDObservation]],
    target_date: date,
) -> EnergyRegimeSnapshot:
    snap = EnergyRegimeSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float) -> None:
        confidence[var_name] = conf
        if sig is not None:
            snap.signals[var_name] = sig

    # yfinance-based signals
    sig, conf = _compute_13w_return_zscore(yf_observations.get("CL=F", []))
    _apply("OilPriceSurge", sig, conf)

    sig, conf = _compute_13w_return_zscore(yf_observations.get("NG=F", []))
    _apply("NatGasPriceSurge", sig, conf)

    sig, conf = _compute_13w_return_zscore(yf_observations.get("XLE", []))
    _apply("EnergyEquityMomentum", sig, conf)

    sig, conf = _compute_renewables_displacement(
        yf_observations.get("ICLN", []),
        yf_observations.get("XLE", []),
    )
    _apply("RenewablesDisplacement", sig, conf)

    # FRED-based signals
    sig, conf = _compute_opec_supply_constraint(fred_observations.get("DCOILWTICO", []))
    _apply("OPECSupplyConstraint", sig, conf)

    sig, conf = _compute_energy_inflation_persistent(fred_observations.get("CPIENGSL", []))
    _apply("EnergyInflationPersistent", sig, conf)

    sig, conf = _compute_geopolitical_risk(fred_observations.get("DCOILWTICO", []))
    _apply("GeopoliticalRiskElevated", sig, conf)

    sig, conf = _compute_demand_destruction_risk(
        fred_observations.get("INDPRO", []),
        fred_observations.get("UNRATE", []),
    )
    _apply("DemandDestructionRisk", sig, conf)

    snap.confidence = confidence
    return snap


class EnergyRegimePipeline:
    """Fetches FRED + yfinance data and builds EvidenceRecords for energy-regime-v1."""

    def __init__(self, fred: FREDClient, yf_client: EnergyYFinanceClient) -> None:
        self._fred = fred
        self._yf = yf_client

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:

        import asyncio
        fred_obs, yf_obs = await asyncio.gather(
            self._fred.fetch_all_series(end_date=target_date),
            self._yf.fetch_all(end_date=target_date),
        )

        snapshot = compute_snapshot(yf_obs, fred_obs, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: EnergyRegimeSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="energy-regime-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="yfinance:CL=F+NG=F+XLE+ICLN|FRED:DCOILWTICO+CPIENGSL+INDPRO+UNRATE"
            f"@week-ending-{target_date}",
        )


