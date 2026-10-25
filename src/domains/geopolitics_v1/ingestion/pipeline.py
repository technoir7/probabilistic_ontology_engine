"""
GeopoliticsPipeline — GDELT + FRED observations → EvidenceRecords.

Variable signals (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal, read as a level observed exactly
(sources.grades): low below -0.5, mid within ±0.5, high above +0.5. The
GDELT article volumes are noisy but still measured numbers, so they are
degrees like the rest. A variable whose inputs are too thin for its signal,
including a GDELT outage (the client returns no rows), is MISSING (D10).

ConflictIntensityElevated
    Signal : 4-week avg of GDELT "conflict" values z-scored vs 90-day history

TradeDisruptionRisk
    Signal : DCOILWTICO z-score (rising oil = trade disruption risk)

SanctionsPressureElevated
    Signal : 4-week avg of GDELT "sanctions" values z-score

DiplomaticTensionHigh
    Signal : 4-week avg of GDELT "diplomatic" values z-score

SupplyChainStress
    Signal : (DCOILWTICO_zscore + PPIACO_zscore) / 2

CurrencyWarSignal
    Signal : DTWEXBGS rolling 28-day std z-scored vs history

EnergyWeaponizationRisk
    Signal : (GDELT "energy_sanction" 4w avg z + DCOILWTICO 13w change z) / 2

GlobalTradeVolumeWeak
    Signal : -INDPRO 3-month change z-score (inverted: weak production = signal)
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
from .gdelt_client import GDELTClient, GDELTObs
from .fred_client import FREDClient, FREDObservation
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)


# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class GeopoliticsSnapshot:
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


def _gdelt_4week_avg_zscore(obs: list[GDELTObs]) -> tuple[Optional[float], float]:
    """
    Compute 4-week (28-day) average of GDELT values, z-scored vs full history.

    Returns (None, 0.5) on empty/insufficient data, so the variable is MISSING.
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

    def _apply(var_name: str, sig: Optional[float], conf: float) -> None:
        confidence[var_name] = conf
        if sig is not None:
            snap.signals[var_name] = sig

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
    _apply("ConflictIntensityElevated", sig, conf)

    # TradeDisruptionRisk
    sig, conf = _compute_trade_disruption_risk(wti_obs)
    _apply("TradeDisruptionRisk", sig, conf)

    # SanctionsPressureElevated
    sig, conf = _compute_sanctions_pressure(sanctions_obs)
    _apply("SanctionsPressureElevated", sig, conf)

    # DiplomaticTensionHigh
    sig, conf = _compute_diplomatic_tension(diplomatic_obs)
    _apply("DiplomaticTensionHigh", sig, conf)

    # SupplyChainStress
    sig, conf = _compute_supply_chain_stress(wti_obs, ppi_obs)
    _apply("SupplyChainStress", sig, conf)

    # CurrencyWarSignal
    sig, conf = _compute_currency_war_signal(dtwex_obs)
    _apply("CurrencyWarSignal", sig, conf)

    # EnergyWeaponizationRisk
    sig, conf = _compute_energy_weaponization(energy_obs, wti_obs)
    _apply("EnergyWeaponizationRisk", sig, conf)

    # GlobalTradeVolumeWeak
    sig, conf = _compute_global_trade_volume_weak(indpro_obs)
    _apply("GlobalTradeVolumeWeak", sig, conf)

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
        target_date: date,
    ) -> EvidenceRecord:

        import asyncio
        gdelt_data, fred_data = await asyncio.gather(
            self._gdelt.fetch_all(end_date=target_date),
            self._fred.fetch_all_series(end_date=target_date),
        )

        snapshot = compute_snapshot(gdelt_data, fred_data, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: GeopoliticsSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="geopolitics-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="GDELT:conflict+sanctions+diplomatic+energy"
            "|FRED:DCOILWTICO+PPIACO+DTWEXBGS+INDPRO"
            f"@week-ending-{target_date}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


