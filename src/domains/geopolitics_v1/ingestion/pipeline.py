"""
GeopoliticsPipeline — GDELT + FRED observations → EvidenceRecords.

Variable calibrations (all SOFT_OBSERVED, sigmoid-based)
----------------------------------------------------------
NOTE: Prob clamp is [0.05, 0.95] instead of [0.01, 0.99] due to GDELT noise.

ConflictIntensityElevated
    Signal  : 4-week avg of GDELT "conflict" values z-scored vs 90-day history
    P(True) : sigmoid(z_score)

TradeDisruptionRisk
    Signal  : DCOILWTICO z-score (rising oil = trade disruption risk)
    P(True) : sigmoid(z_score)

SanctionsPressureElevated
    Signal  : 4-week avg of GDELT "sanctions" values z-score
    P(True) : sigmoid(z_score)

DiplomaticTensionHigh
    Signal  : 4-week avg of GDELT "diplomatic" values z-score
    P(True) : sigmoid(z_score)

SupplyChainStress
    Signal  : (DCOILWTICO_zscore + PPIACO_zscore) / 2
    P(True) : sigmoid(composite)

CurrencyWarSignal
    Signal  : DTWEXBGS rolling 28-day std z-scored vs history
    P(True) : sigmoid(z_score)

EnergyWeaponizationRisk
    Signal  : (GDELT "energy_sanction" 4w avg z + DCOILWTICO 13w change z) / 2
    P(True) : sigmoid(composite)

GlobalTradeVolumeWeak
    Signal  : -INDPRO 3-month change z-score (inverted: weak production = signal)
    P(True) : sigmoid(signal)
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
from .gdelt_client import GDELTClient, GDELTObs
from .fred_client import FREDClient, FREDObservation

logger = logging.getLogger(__name__)

# Wider clamp due to GDELT signal noise
_CLAMP_LO: float = 0.05
_CLAMP_HI: float = 0.95


@dataclass
class GeopoliticsSnapshot:
    """Derived signals and soft probabilities for one evidence week."""

    # Soft probabilities
    p_conflict_intensity_elevated: float = 0.5
    p_trade_disruption_risk: float = 0.5
    p_sanctions_pressure_elevated: float = 0.5
    p_diplomatic_tension_high: float = 0.5
    p_supply_chain_stress: float = 0.5
    p_currency_war_signal: float = 0.5
    p_energy_weaponization_risk: float = 0.5
    p_global_trade_volume_weak: float = 0.5

    # Hard MAP booleans
    conflict_intensity_elevated: bool = False
    trade_disruption_risk: bool = False
    sanctions_pressure_elevated: bool = False
    diplomatic_tension_high: bool = False
    supply_chain_stress: bool = False
    currency_war_signal: bool = False
    energy_weaponization_risk: bool = False
    global_trade_volume_weak: bool = False

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


def _gdelt_4week_avg_zscore(obs: list[GDELTObs]) -> tuple[Optional[float], float]:
    """
    Compute 4-week (28-day) average of GDELT values, z-scored vs full history.

    Returns (None, 0.5) on empty/insufficient data — GDELT fallback.
    """
    if not obs:
        return None, 0.5

    values = [o.value for o in obs]
    if len(values) < 4:
        return None, 0.5

    recent_28 = values[:min(28, len(values))]
    recent_avg = float(np.mean(recent_28))

    if len(values) < 8:
        # Not enough history for z-score, use simple signal
        overall_avg = float(np.mean(values))
        overall_std = float(np.std(values, ddof=1)) if len(values) > 1 else 1.0
        if overall_std < 1e-9:
            return 0.0, 0.5
        signal = (recent_avg - overall_avg) / overall_std
        return signal, 0.7

    return _zscore(recent_avg, values), 1.0


# ---------------------------------------------------------------------------
# Per-variable signal computation
# ---------------------------------------------------------------------------

def _compute_conflict_intensity(obs: list[GDELTObs]) -> tuple[Optional[float], float]:
    """GDELT "conflict war" 4-week avg z-score."""
    return _gdelt_4week_avg_zscore(obs)


def _compute_trade_disruption_risk(wti_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DCOILWTICO z-score (rising oil → trade disruption risk)."""
    if len(wti_obs) < 52:
        return None, 0.5
    current = wti_obs[0].value
    values = [o.value for o in wti_obs[:260]]
    return _zscore(current, values), 1.0


def _compute_sanctions_pressure(obs: list[GDELTObs]) -> tuple[Optional[float], float]:
    """GDELT "sanctions" 4-week avg z-score."""
    return _gdelt_4week_avg_zscore(obs)


def _compute_diplomatic_tension(obs: list[GDELTObs]) -> tuple[Optional[float], float]:
    """GDELT "diplomatic tension" 4-week avg z-score."""
    return _gdelt_4week_avg_zscore(obs)


def _compute_supply_chain_stress(
    wti_obs: list[FREDObservation],
    ppi_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """(DCOILWTICO_zscore + PPIACO_zscore) / 2 composite."""
    wti_sig = 0.0
    wti_conf = 0.0
    if len(wti_obs) >= 52:
        current = wti_obs[0].value
        values = [o.value for o in wti_obs[:260]]
        wti_sig = _zscore(current, values)
        wti_conf = 1.0

    ppi_sig = 0.0
    ppi_conf = 0.0
    if len(ppi_obs) >= 12:
        current = ppi_obs[0].value
        values = [o.value for o in ppi_obs]
        ppi_sig = _zscore(current, values)
        ppi_conf = 1.0

    if wti_conf == 0.0 and ppi_conf == 0.0:
        return None, 0.5

    weights = wti_conf + ppi_conf
    composite = (wti_sig * wti_conf + ppi_sig * ppi_conf) / weights
    conf = max(wti_conf, ppi_conf)
    return composite, conf


def _compute_currency_war_signal(dtwex_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """DTWEXBGS rolling 28-day std z-scored vs history of rolling 28-day stds."""
    if len(dtwex_obs) < 30:
        return None, 0.5

    values = [o.value for o in dtwex_obs]

    # Compute rolling 28-day volatility windows
    vol_windows: list[float] = []
    for i in range(len(values) - 27):
        window = values[i:i + 28]
        if len(window) >= 2:
            vol_windows.append(float(np.std(window, ddof=1)))

    if len(vol_windows) < 2:
        return None, 0.5

    current_vol = vol_windows[0]
    return _zscore(current_vol, vol_windows), 1.0


def _compute_energy_weaponization(
    energy_obs: list[GDELTObs],
    wti_obs: list[FREDObservation],
) -> tuple[Optional[float], float]:
    """(GDELT energy_sanction 4w avg z + DCOILWTICO 13w change z) / 2."""
    gdelt_sig = 0.0
    gdelt_conf = 0.0
    if energy_obs:
        sig, conf = _gdelt_4week_avg_zscore(energy_obs)
        if sig is not None:
            gdelt_sig = sig
            gdelt_conf = conf

    wti_sig = 0.0
    wti_conf = 0.0
    if len(wti_obs) >= 14:
        current = wti_obs[0].value
        # 13-week (91-day) change using closest available
        idx_13w = min(91, len(wti_obs) - 1)
        past = wti_obs[idx_13w].value
        if past > 0:
            change_pct = (current / past - 1.0) * 100.0
            # Z-score vs historical 13w changes
            changes: list[float] = []
            for i in range(len(wti_obs) - 91):
                p_now = wti_obs[i].value
                p_past = wti_obs[i + 91].value
                if p_past > 0:
                    changes.append((p_now / p_past - 1.0) * 100.0)
            if len(changes) >= 2:
                wti_sig = _zscore(change_pct, changes)
                wti_conf = 1.0
            else:
                wti_sig = change_pct / 10.0
                wti_conf = 0.7

    if gdelt_conf == 0.0 and wti_conf == 0.0:
        return None, 0.5

    weights = gdelt_conf + wti_conf
    if weights == 0:
        return None, 0.5

    composite = (gdelt_sig * gdelt_conf + wti_sig * wti_conf) / weights
    conf = max(gdelt_conf, wti_conf)
    return composite, conf


def _compute_global_trade_volume_weak(indpro_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """INDPRO 3-month change inverted z-score (weak production = weak trade)."""
    if len(indpro_obs) < 6:
        return None, 0.5

    current = indpro_obs[0].value
    three_m_ago = indpro_obs[min(3, len(indpro_obs) - 1)].value
    if three_m_ago <= 0:
        return None, 0.5

    change_pct = (current / three_m_ago - 1.0) * 100.0

    # Historical 3m changes for z-score
    changes: list[float] = []
    for i in range(len(indpro_obs) - 3):
        p_now = indpro_obs[i].value
        p_3m_ago = indpro_obs[i + 3].value
        if p_3m_ago > 0:
            changes.append((p_now / p_3m_ago - 1.0) * 100.0)

    if len(changes) < 2:
        signal = -change_pct / 1.0
        return signal, 0.7

    z = _zscore(change_pct, changes)
    return -z, 1.0  # Inverted: weak production → positive signal


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def compute_snapshot(
    gdelt_data: dict,
    fred_data: dict,
    target_date: date,
) -> GeopoliticsSnapshot:
    snap = GeopoliticsSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    conflict_obs = gdelt_data.get("conflict", [])
    sanctions_obs = gdelt_data.get("sanctions", [])
    diplomatic_obs = gdelt_data.get("diplomatic", [])
    energy_obs = gdelt_data.get("energy_sanction", [])

    wti_obs = fred_data.get("DCOILWTICO", [])
    ppi_obs = fred_data.get("PPIACO", [])
    dtwex_obs = fred_data.get("DTWEXBGS", [])
    indpro_obs = fred_data.get("INDPRO", [])

    # ConflictIntensityElevated
    sig, conf = _compute_conflict_intensity(conflict_obs)
    _apply("ConflictIntensityElevated", sig, conf, "p_conflict_intensity_elevated", "conflict_intensity_elevated")

    # TradeDisruptionRisk
    sig, conf = _compute_trade_disruption_risk(wti_obs)
    _apply("TradeDisruptionRisk", sig, conf, "p_trade_disruption_risk", "trade_disruption_risk")

    # SanctionsPressureElevated
    sig, conf = _compute_sanctions_pressure(sanctions_obs)
    _apply("SanctionsPressureElevated", sig, conf, "p_sanctions_pressure_elevated", "sanctions_pressure_elevated")

    # DiplomaticTensionHigh
    sig, conf = _compute_diplomatic_tension(diplomatic_obs)
    _apply("DiplomaticTensionHigh", sig, conf, "p_diplomatic_tension_high", "diplomatic_tension_high")

    # SupplyChainStress
    sig, conf = _compute_supply_chain_stress(wti_obs, ppi_obs)
    _apply("SupplyChainStress", sig, conf, "p_supply_chain_stress", "supply_chain_stress")

    # CurrencyWarSignal
    sig, conf = _compute_currency_war_signal(dtwex_obs)
    _apply("CurrencyWarSignal", sig, conf, "p_currency_war_signal", "currency_war_signal")

    # EnergyWeaponizationRisk
    sig, conf = _compute_energy_weaponization(energy_obs, wti_obs)
    _apply("EnergyWeaponizationRisk", sig, conf, "p_energy_weaponization_risk", "energy_weaponization_risk")

    # GlobalTradeVolumeWeak
    sig, conf = _compute_global_trade_volume_weak(indpro_obs)
    _apply("GlobalTradeVolumeWeak", sig, conf, "p_global_trade_volume_weak", "global_trade_volume_weak")

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class GeopoliticsPipeline:
    """Fetches GDELT + FRED and builds EvidenceRecords for geopolitics-v1."""

    def __init__(self, gdelt: GDELTClient, fred: FREDClient) -> None:
        self._gdelt = gdelt
        self._fred = fred

    async def fetch_evidence(
        self,
        target_date: Optional[date] = None,
    ) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()

        import asyncio
        gdelt_data, fred_data = await asyncio.gather(
            self._gdelt.fetch_all(end_date=target_date),
            self._fred.fetch_all_series(end_date=target_date),
        )

        snapshot = compute_snapshot(gdelt_data, fred_data, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: GeopoliticsSnapshot) -> EvidenceRecord:
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
            _assignment("ConflictIntensityElevated",  snapshot.conflict_intensity_elevated,  snapshot.p_conflict_intensity_elevated),
            _assignment("TradeDisruptionRisk",         snapshot.trade_disruption_risk,         snapshot.p_trade_disruption_risk),
            _assignment("SanctionsPressureElevated",   snapshot.sanctions_pressure_elevated,   snapshot.p_sanctions_pressure_elevated),
            _assignment("DiplomaticTensionHigh",       snapshot.diplomatic_tension_high,       snapshot.p_diplomatic_tension_high),
            _assignment("SupplyChainStress",           snapshot.supply_chain_stress,           snapshot.p_supply_chain_stress),
            _assignment("CurrencyWarSignal",           snapshot.currency_war_signal,           snapshot.p_currency_war_signal),
            _assignment("EnergyWeaponizationRisk",     snapshot.energy_weaponization_risk,     snapshot.p_energy_weaponization_risk),
            _assignment("GlobalTradeVolumeWeak",       snapshot.global_trade_volume_weak,      snapshot.p_global_trade_volume_weak),
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
                "GDELT:conflict+sanctions+diplomatic+energy"
                "|FRED:DCOILWTICO+PPIACO+DTWEXBGS+INDPRO"
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
