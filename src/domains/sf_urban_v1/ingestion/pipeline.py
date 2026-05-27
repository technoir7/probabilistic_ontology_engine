"""
SFUrbanPipeline — SF Open Data + FRED observations → EvidenceRecords.

Variable calibrations (all SOFT_OBSERVED, sigmoid-based)
----------------------------------------------------------
TechHiringAccelerating
    Signal  : FRED info employment YoY change z-score
    P(True) : sigmoid(z_score)

OfficeVacancyFalling
    Signal  : SF permits commercial/office fraction, inverted z-score
    P(True) : sigmoid(signal)  [rising commercial permits = vacancy falling]

RetailClosureElevated
    Signal  : SF business license expirations monthly count z-score
    P(True) : sigmoid(z_score)

PermitActivityRising
    Signal  : SF total building permits monthly count z-score
    P(True) : sigmoid(z_score)

CrimeIndexElevated
    Signal  : SF police incidents monthly count z-score
    P(True) : sigmoid(z_score)

StartupFormationRising
    Signal  : SF new business registrations monthly count z-score
    P(True) : sigmoid(z_score)

FootTrafficRecovering
    Signal  : FRED leisure/hospitality employment YoY change z-score
    P(True) : sigmoid(z_score)

PopulationFlowPositive
    Signal  : FRED total employment YoY change z-score
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
from .sfgov_client import SFGovClient, SFPermitObs, SFIncidentObs, SFBusinessObs
from .fred_client import FREDClient, FREDObservation

logger = logging.getLogger(__name__)

_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99


@dataclass
class SFUrbanSnapshot:
    """Derived signals and soft probabilities for one evidence week."""

    # Soft probabilities
    p_tech_hiring_accelerating: float = 0.5
    p_office_vacancy_falling: float = 0.5
    p_retail_closure_elevated: float = 0.5
    p_permit_activity_rising: float = 0.5
    p_crime_index_elevated: float = 0.5
    p_startup_formation_rising: float = 0.5
    p_foot_traffic_recovering: float = 0.5
    p_population_flow_positive: float = 0.5

    # Hard MAP booleans
    tech_hiring_accelerating: bool = False
    office_vacancy_falling: bool = False
    retail_closure_elevated: bool = False
    permit_activity_rising: bool = False
    crime_index_elevated: bool = False
    startup_formation_rising: bool = False
    foot_traffic_recovering: bool = False
    population_flow_positive: bool = False

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


def _monthly_counts(obs_dates: list[date], lookback_months: int = 13) -> dict[str, int]:
    """
    Bucket dates into 'YYYY-MM' keys, return counts for last lookback_months.
    """
    counts: dict[str, int] = {}
    for d in obs_dates:
        key = f"{d.year:04d}-{d.month:02d}"
        counts[key] = counts.get(key, 0) + 1
    # Keep only the most recent lookback_months
    sorted_months = sorted(counts.keys(), reverse=True)
    return {m: counts[m] for m in sorted_months[:lookback_months]}


def _monthly_zscore(obs_dates: list[date]) -> Optional[float]:
    """
    Z-score of most recent month's count vs preceding 12 months.
    Returns None if insufficient data.
    """
    if not obs_dates:
        return None
    counts = _monthly_counts(obs_dates, lookback_months=13)
    if len(counts) < 3:
        return None
    sorted_months = sorted(counts.keys())
    recent = counts[sorted_months[-1]]
    history = [counts[m] for m in sorted_months[:-1]]
    if len(history) < 2:
        return None
    return _zscore(float(recent), [float(h) for h in history])


def _fred_yoy_zscore(obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """
    YoY change z-scored vs historical YoY changes.
    Monthly FRED data: obs[0] is most recent, obs[12] is ~1 year ago.
    """
    if len(obs) < 14:  # Need at least 14 months
        return None, 0.5

    current = obs[0].value
    year_ago = obs[min(12, len(obs) - 1)].value
    if year_ago <= 0:
        return None, 0.5

    yoy_change_pct = (current / year_ago - 1.0) * 100.0

    # Historical YoY changes
    hist_changes: list[float] = []
    for i in range(min(len(obs) - 12, 13)):
        p_now = obs[i].value
        p_yr_ago = obs[min(i + 12, len(obs) - 1)].value
        if p_yr_ago > 0:
            hist_changes.append((p_now / p_yr_ago - 1.0) * 100.0)

    if len(hist_changes) < 2:
        signal = yoy_change_pct / 2.0
        return signal, 0.7

    return _zscore(yoy_change_pct, hist_changes), 1.0


# ---------------------------------------------------------------------------
# Per-variable signal computation
# ---------------------------------------------------------------------------

def _compute_tech_hiring(info_emp_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """FRED info employment YoY change z-score."""
    return _fred_yoy_zscore(info_emp_obs)


def _compute_office_vacancy_falling(permits: list[SFPermitObs]) -> tuple[Optional[float], float]:
    """
    SF permits commercial/office fraction, inverted z-score.
    Rising commercial permits fraction = office vacancy falling = positive signal.
    """
    if len(permits) < 10:
        return None, 0.5

    _COMMERCIAL_KEYWORDS = {"commercial", "office", "tenant improvement", "tenant impr",
                             "ti ", "t.i.", "commercial alteration"}

    def _is_commercial(permit_type: str) -> bool:
        pt_lower = permit_type.lower()
        return any(kw in pt_lower for kw in _COMMERCIAL_KEYWORDS)

    # Monthly fractions
    monthly_total: dict[str, int] = {}
    monthly_commercial: dict[str, int] = {}

    for p in permits:
        key = f"{p.filed_date.year:04d}-{p.filed_date.month:02d}"
        monthly_total[key] = monthly_total.get(key, 0) + 1
        if _is_commercial(p.permit_type):
            monthly_commercial[key] = monthly_commercial.get(key, 0) + 1

    months = sorted(monthly_total.keys(), reverse=True)
    if len(months) < 3:
        return None, 0.5

    fractions: list[float] = []
    for m in months:
        total = monthly_total.get(m, 0)
        commercial = monthly_commercial.get(m, 0)
        if total > 0:
            fractions.append(commercial / total)

    if len(fractions) < 3:
        return None, 0.5

    current_frac = fractions[0]
    # Inverted: rising commercial fraction = vacancy falling = positive signal
    z = _zscore(current_frac, fractions[1:])
    return z, 0.8


def _compute_retail_closure(businesses: list[SFBusinessObs]) -> tuple[Optional[float], float]:
    """SF business license expirations count z-score."""
    closure_dates = [
        b.end_date for b in businesses
        if b.end_date is not None
    ]
    if not closure_dates:
        return None, 0.5
    z = _monthly_zscore(closure_dates)
    if z is None:
        return None, 0.5
    return z, 0.8


def _compute_permit_activity(permits: list[SFPermitObs]) -> tuple[Optional[float], float]:
    """SF total building permits monthly count z-score."""
    if not permits:
        return None, 0.5
    permit_dates = [p.filed_date for p in permits]
    z = _monthly_zscore(permit_dates)
    if z is None:
        return None, 0.5
    return z, 0.8


def _compute_crime_index(incidents: list[SFIncidentObs]) -> tuple[Optional[float], float]:
    """SF police incidents monthly count z-score."""
    if not incidents:
        return None, 0.5
    incident_dates = [i.incident_date for i in incidents]
    z = _monthly_zscore(incident_dates)
    if z is None:
        return None, 0.5
    return z, 0.8


def _compute_startup_formation(businesses: list[SFBusinessObs]) -> tuple[Optional[float], float]:
    """SF new business registrations count z-score."""
    start_dates = [b.start_date for b in businesses]
    if not start_dates:
        return None, 0.5
    z = _monthly_zscore(start_dates)
    if z is None:
        return None, 0.5
    return z, 0.8


def _compute_foot_traffic(hosp_emp_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """FRED leisure/hospitality employment YoY change z-score."""
    return _fred_yoy_zscore(hosp_emp_obs)


def _compute_population_flow(total_emp_obs: list[FREDObservation]) -> tuple[Optional[float], float]:
    """FRED total employment YoY change z-score."""
    return _fred_yoy_zscore(total_emp_obs)


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def compute_snapshot(
    sfgov_data: dict,
    fred_data: dict,
    target_date: date,
) -> SFUrbanSnapshot:
    snap = SFUrbanSnapshot(target_date=target_date)
    confidence: dict[str, float] = {}

    def _apply(var_name: str, sig: Optional[float], conf: float, p_attr: str, bool_attr: str) -> None:
        s = sig if sig is not None else 0.0
        p = _soft_bool(s)
        setattr(snap, p_attr, p)
        setattr(snap, bool_attr, p > 0.5)
        confidence[var_name] = conf

    permits = sfgov_data.get("permits", [])
    incidents = sfgov_data.get("incidents", [])
    businesses = sfgov_data.get("businesses", [])

    info_emp = fred_data.get("SANF806INFO", [])
    hosp_emp = fred_data.get("SANF806LEIH", [])
    total_emp = fred_data.get("SANF806NA", [])

    # TechHiringAccelerating
    sig, conf = _compute_tech_hiring(info_emp)
    _apply("TechHiringAccelerating", sig, conf, "p_tech_hiring_accelerating", "tech_hiring_accelerating")

    # OfficeVacancyFalling
    sig, conf = _compute_office_vacancy_falling(permits)
    _apply("OfficeVacancyFalling", sig, conf, "p_office_vacancy_falling", "office_vacancy_falling")

    # RetailClosureElevated
    sig, conf = _compute_retail_closure(businesses)
    _apply("RetailClosureElevated", sig, conf, "p_retail_closure_elevated", "retail_closure_elevated")

    # PermitActivityRising
    sig, conf = _compute_permit_activity(permits)
    _apply("PermitActivityRising", sig, conf, "p_permit_activity_rising", "permit_activity_rising")

    # CrimeIndexElevated
    sig, conf = _compute_crime_index(incidents)
    _apply("CrimeIndexElevated", sig, conf, "p_crime_index_elevated", "crime_index_elevated")

    # StartupFormationRising
    sig, conf = _compute_startup_formation(businesses)
    _apply("StartupFormationRising", sig, conf, "p_startup_formation_rising", "startup_formation_rising")

    # FootTrafficRecovering
    sig, conf = _compute_foot_traffic(hosp_emp)
    _apply("FootTrafficRecovering", sig, conf, "p_foot_traffic_recovering", "foot_traffic_recovering")

    # PopulationFlowPositive
    sig, conf = _compute_population_flow(total_emp)
    _apply("PopulationFlowPositive", sig, conf, "p_population_flow_positive", "population_flow_positive")

    snap.confidence = confidence
    return snap


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class SFUrbanPipeline:
    """Fetches SF Open Data + FRED and builds EvidenceRecords for sf-urban-v1."""

    def __init__(self, sfgov: SFGovClient, fred: FREDClient) -> None:
        self._sfgov = sfgov
        self._fred = fred

    async def fetch_evidence(
        self,
        target_date: Optional[date] = None,
    ) -> EvidenceRecord:
        if target_date is None:
            target_date = _last_friday()

        import asyncio
        sfgov_data, fred_data = await asyncio.gather(
            self._sfgov.fetch_all(end_date=target_date),
            self._fred.fetch_all_series(end_date=target_date),
        )

        snapshot = compute_snapshot(sfgov_data, fred_data, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: SFUrbanSnapshot) -> EvidenceRecord:
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
            _assignment("TechHiringAccelerating",  snapshot.tech_hiring_accelerating,  snapshot.p_tech_hiring_accelerating),
            _assignment("OfficeVacancyFalling",     snapshot.office_vacancy_falling,     snapshot.p_office_vacancy_falling),
            _assignment("RetailClosureElevated",    snapshot.retail_closure_elevated,    snapshot.p_retail_closure_elevated),
            _assignment("PermitActivityRising",     snapshot.permit_activity_rising,     snapshot.p_permit_activity_rising),
            _assignment("CrimeIndexElevated",       snapshot.crime_index_elevated,       snapshot.p_crime_index_elevated),
            _assignment("StartupFormationRising",   snapshot.startup_formation_rising,   snapshot.p_startup_formation_rising),
            _assignment("FootTrafficRecovering",    snapshot.foot_traffic_recovering,    snapshot.p_foot_traffic_recovering),
            _assignment("PopulationFlowPositive",   snapshot.population_flow_positive,   snapshot.p_population_flow_positive),
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
                "SFGov:permits+incidents+businesses"
                "|FRED:SANF806INFO+SANF806LEIH+SANF806NA"
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
