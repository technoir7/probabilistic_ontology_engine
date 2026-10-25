"""
SFUrbanPipeline — SF Open Data + FRED observations → EvidenceRecords.

Variable signals (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal, read as a level observed exactly
(sources.grades): low below -0.5, mid within ±0.5, high above +0.5. A
variable whose inputs are too thin for its signal, including an SF Open Data
outage (the client returns no rows), is MISSING (D10).

TechHiringAccelerating
    Signal : FRED info employment YoY change z-score

OfficeVacancyFalling
    Signal : SF permits commercial/office fraction, inverted z-score
             [rising commercial permits = vacancy falling]

RetailClosureElevated
    Signal : SF business license expirations monthly count z-score

PermitActivityRising
    Signal : SF total building permits monthly count z-score

CrimeIndexElevated
    Signal : SF police incidents monthly count z-score

StartupFormationRising
    Signal : SF new business registrations monthly count z-score

FootTrafficRecovering
    Signal : FRED leisure/hospitality employment YoY change z-score

PopulationFlowPositive
    Signal : FRED total employment YoY change z-score
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
from .sfgov_client import MonthlyCount, SFGovClient
from .fred_client import FREDClient, FREDObservation
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore as _zscore

logger = logging.getLogger(__name__)


# slots: a misspelled field name raises instead of silently adding a field.
@dataclass(slots=True)
class SFUrbanSnapshot:
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


def _complete_months(counts: list[MonthlyCount], target_date: date, months: int = 13) -> dict[date, list[MonthlyCount]]:
    """
    Rows grouped by month, for the last *months* months that ended before
    *target_date*'s month. The month in progress is left out: a weekly run on
    the 10th would otherwise compare ten days against whole months, which
    biases every z-score low.
    """
    first_of_target_month = target_date.replace(day=1)
    by_month: dict[date, list[MonthlyCount]] = {}
    for row in counts:
        if row.month < first_of_target_month:
            by_month.setdefault(row.month, []).append(row)
    return {m: by_month[m] for m in sorted(by_month)[-months:]}


def _monthly_zscore(counts: list[MonthlyCount], target_date: date) -> Optional[float]:
    """
    Z-score of the latest complete month's count vs the up to 12 before it.
    None with fewer than 3 complete months.
    """
    by_month = _complete_months(counts, target_date)
    if len(by_month) < 3:
        return None
    totals = [float(sum(r.count for r in rows)) for rows in by_month.values()]
    return _zscore(totals[-1], totals[:-1])


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


# Matched against a permit's proposed_use. The numeric permit_type code never
# matched these (REFACTOR_SPEC B19), so this signal used to be constant.
_COMMERCIAL_KEYWORDS = {"commercial", "office", "tenant improvement", "tenant impr",
                        "ti ", "t.i.", "commercial alteration"}


def _is_commercial(proposed_use: str) -> bool:
    use = proposed_use.lower()
    return any(kw in use for kw in _COMMERCIAL_KEYWORDS)


def _compute_office_vacancy_falling(permits: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    """
    Share of permits whose proposed use is office/commercial, latest complete
    month vs the months before it. Rising share = office vacancy falling.
    """
    by_month = _complete_months(permits, target_date)
    fractions = []
    for rows in by_month.values():
        total = sum(r.count for r in rows)
        if total > 0:
            fractions.append(sum(r.count for r in rows if _is_commercial(r.category)) / total)
    if len(fractions) < 3:
        return None, 0.5
    return _zscore(fractions[-1], fractions[:-1]), 0.8


def _count_signal(counts: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    z = _monthly_zscore(counts, target_date)
    return (None, 0.5) if z is None else (z, 0.8)


def _compute_retail_closure(closures: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    """Business locations ended per month, z-scored."""
    return _count_signal(closures, target_date)


def _compute_permit_activity(permits: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    """Building permits filed per month, z-scored."""
    return _count_signal(permits, target_date)


def _compute_crime_index(incidents: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    """Police incidents per month, z-scored."""
    return _count_signal(incidents, target_date)


def _compute_startup_formation(openings: list[MonthlyCount], target_date: date) -> tuple[Optional[float], float]:
    """Business locations started per month, z-scored."""
    return _count_signal(openings, target_date)


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

    def _apply(var_name: str, sig: Optional[float], conf: float) -> None:
        confidence[var_name] = conf
        if sig is not None:
            snap.signals[var_name] = sig

    permits = sfgov_data.get("permits", [])
    incidents = sfgov_data.get("incidents", [])
    openings = sfgov_data.get("business_openings", [])
    closures = sfgov_data.get("business_closures", [])

    info_emp = fred_data.get("SANF806INFO", [])
    hosp_emp = fred_data.get("SANF806LEIH", [])
    total_emp = fred_data.get("SANF806NA", [])

    # TechHiringAccelerating
    sig, conf = _compute_tech_hiring(info_emp)
    _apply("TechHiringAccelerating", sig, conf)

    # OfficeVacancyFalling
    sig, conf = _compute_office_vacancy_falling(permits, target_date)
    _apply("OfficeVacancyFalling", sig, conf)

    # RetailClosureElevated
    sig, conf = _compute_retail_closure(closures, target_date)
    _apply("RetailClosureElevated", sig, conf)

    # PermitActivityRising
    sig, conf = _compute_permit_activity(permits, target_date)
    _apply("PermitActivityRising", sig, conf)

    # CrimeIndexElevated
    sig, conf = _compute_crime_index(incidents, target_date)
    _apply("CrimeIndexElevated", sig, conf)

    # StartupFormationRising
    sig, conf = _compute_startup_formation(openings, target_date)
    _apply("StartupFormationRising", sig, conf)

    # FootTrafficRecovering
    sig, conf = _compute_foot_traffic(hosp_emp)
    _apply("FootTrafficRecovering", sig, conf)

    # PopulationFlowPositive
    sig, conf = _compute_population_flow(total_emp)
    _apply("PopulationFlowPositive", sig, conf)

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
        target_date: date,
    ) -> EvidenceRecord:

        import asyncio
        sfgov_data, fred_data = await asyncio.gather(
            self._sfgov.fetch_all(end_date=target_date),
            self._fred.fetch_all_series(end_date=target_date),
        )

        snapshot = compute_snapshot(sfgov_data, fred_data, target_date)
        return self.build_evidence_record(snapshot)

    @staticmethod
    def build_evidence_record(snapshot: SFUrbanSnapshot) -> EvidenceRecord:
        target_date = snapshot.target_date
        return build_graded_record(
            module_id="sf-urban-v1",
            variables=get_variables(),
            signals=snapshot.signals,
            confidence=snapshot.confidence,
            target_date=target_date,
            source_ref="SFGov:permits+incidents+businesses"
            "|FRED:SANF806INFO+SANF806LEIH+SANF806NA"
            f"@week-ending-{target_date}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


