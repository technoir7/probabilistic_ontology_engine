"""
EnergyRegimePipeline — FRED + yfinance observations → EvidenceRecords.

Variable calibrations
----------------------
OilPriceSurge
    Signal  : CL=F 13-week return z-score vs historical 13-week returns
    P(True) : sigmoid(z_score)

NatGasPriceSurge
    Signal  : NG=F 13-week return z-score vs historical
    P(True) : sigmoid(z_score)

EnergyEquityMomentum
    Signal  : XLE 13-week return z-score vs historical
    P(True) : sigmoid(z_score)

OPECSupplyConstraint
    Signal  : DCOILWTICO (FRED) 13-week momentum z-score
    P(True) : sigmoid(z_score)

RenewablesDisplacement
    Signal  : ICLN/XLE ratio 52-week z-score
    P(True) : sigmoid(z_score)

EnergyInflationPersistent
    Signal  : (CPIENGSL 12m YoY % - 5.0) / 1.5
    P(True) : sigmoid(signal)  [5% threshold, 1.5pp scale]

GeopoliticalRiskElevated
    Signal  : DCOILWTICO 90-day return volatility z-score vs historical volatility
    P(True) : sigmoid(z_score)

DemandDestructionRisk
    Signal  : composite of INDPRO 3m change (negative) + UNRATE 3m change (positive)
    P(True) : sigmoid(composite)
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
from .yfinance_client import EnergyYFinanceClient, YFObservation

logger = logging.getLogger(__name__)

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99


@dataclass
class EnergyRegimeSnapshot:
    p_oil_price_surge: float = 0.5
    p_nat_gas_price_surge: float = 0.5
    p_energy_equity_momentum: float = 0.5
    p_opec_supply_constraint: float = 0.5
    p_renewables_displacement: float = 0.5
    p_energy_inflation_persistent: float = 0.5
    p_geopolitical_risk_elevated: float = 0.5
    p_demand_destruction_risk: float = 0.5

    oil_price_surge: bool = False
    nat_gas_price_surge: bool = False
    energy_equity_momentum: bool = False
    opec_supply_constraint: bool = False
    renewables_displacement: bool = False
    energy_inflation_persistent: bool = False
    geopolitical_risk_elevated: bool = False
    demand_destruction_risk: bool = False

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
    Rising ratio = renewables outperforming = RenewablesDisplacement = True.
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
    Both negative for economy → DemandDestructionRisk = True.
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

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    # yfinance-based signals
    sig, conf = _compute_13w_return_zscore(yf_observations.get("CL=F", []))
    _apply("OilPriceSurge", sig, conf, "p_oil_price_surge", "oil_price_surge")

    sig, conf = _compute_13w_return_zscore(yf_observations.get("NG=F", []))
    _apply("NatGasPriceSurge", sig, conf, "p_nat_gas_price_surge", "nat_gas_price_surge")

    sig, conf = _compute_13w_return_zscore(yf_observations.get("XLE", []))
    _apply("EnergyEquityMomentum", sig, conf, "p_energy_equity_momentum", "energy_equity_momentum")

    sig, conf = _compute_renewables_displacement(
        yf_observations.get("ICLN", []),
        yf_observations.get("XLE", []),
    )
    _apply("RenewablesDisplacement", sig, conf, "p_renewables_displacement", "renewables_displacement")

    # FRED-based signals
    sig, conf = _compute_opec_supply_constraint(fred_observations.get("DCOILWTICO", []))
    _apply("OPECSupplyConstraint", sig, conf, "p_opec_supply_constraint", "opec_supply_constraint")

    sig, conf = _compute_energy_inflation_persistent(fred_observations.get("CPIENGSL", []))
    _apply("EnergyInflationPersistent", sig, conf, "p_energy_inflation_persistent", "energy_inflation_persistent")

    sig, conf = _compute_geopolitical_risk(fred_observations.get("DCOILWTICO", []))
    _apply("GeopoliticalRiskElevated", sig, conf, "p_geopolitical_risk_elevated", "geopolitical_risk_elevated")

    sig, conf = _compute_demand_destruction_risk(
        fred_observations.get("INDPRO", []),
        fred_observations.get("UNRATE", []),
    )
    _apply("DemandDestructionRisk", sig, conf, "p_demand_destruction_risk", "demand_destruction_risk")

    snap.confidence = confidence
    return snap


class EnergyRegimePipeline:
    """Fetches FRED + yfinance data and builds EvidenceRecords for energy-regime-v1."""

    def __init__(self, fred: FREDClient, yf_client: EnergyYFinanceClient) -> None:
        self._fred = fred
        self._yf = yf_client

    async def fetch_evidence(self, target_date: Optional[date] = None) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()

        import asyncio
        fred_obs, yf_obs = await asyncio.gather(
            self._fred.fetch_all_series(end_date=target_date),
            self._yf.fetch_all(end_date=target_date),
        )

        snapshot = compute_snapshot(yf_obs, fred_obs, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: EnergyRegimeSnapshot) -> EvidenceRecord:
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
            _assignment("OilPriceSurge",            snapshot.oil_price_surge,            snapshot.p_oil_price_surge),
            _assignment("NatGasPriceSurge",          snapshot.nat_gas_price_surge,        snapshot.p_nat_gas_price_surge),
            _assignment("EnergyEquityMomentum",      snapshot.energy_equity_momentum,     snapshot.p_energy_equity_momentum),
            _assignment("OPECSupplyConstraint",       snapshot.opec_supply_constraint,     snapshot.p_opec_supply_constraint),
            _assignment("RenewablesDisplacement",     snapshot.renewables_displacement,    snapshot.p_renewables_displacement),
            _assignment("EnergyInflationPersistent",  snapshot.energy_inflation_persistent, snapshot.p_energy_inflation_persistent),
            _assignment("GeopoliticalRiskElevated",   snapshot.geopolitical_risk_elevated, snapshot.p_geopolitical_risk_elevated),
            _assignment("DemandDestructionRisk",      snapshot.demand_destruction_risk,    snapshot.p_demand_destruction_risk),
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
                "yfinance:CL=F+NG=F+XLE+ICLN|FRED:DCOILWTICO+CPIENGSL+INDPRO+UNRATE"
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
