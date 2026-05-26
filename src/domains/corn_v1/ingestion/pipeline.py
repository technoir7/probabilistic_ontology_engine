"""
CornPipeline — combines USDA NASS and yfinance observations
into EvidenceRecords for the corn-v1 domain.

The pipeline owns the mapping from raw API snapshots to domain variable UUIDs.
Both sources are fetched concurrently.  The static `build_evidence_record`
method performs the pure mapping (no I/O) and is the primary unit-test target.

Variable mapping
----------------
    PlantingDelayed   ← CornNASSSnapshot.planting_delayed
    DroughtIndex      ← CornNASSSnapshot.drought_index
    YieldForecastDown ← CornNASSSnapshot.yield_forecast_down
    CornPriceUp       ← CornNASDAQSnapshot.price_up

Missingness handling
--------------------
    NASS data is only published during specific seasons (planting Apr-Jul,
    conditions Jun-Oct, yield Jun-Nov).  When a NASS field is None (off-season),
    the corresponding assignment uses MissingnessType.MISSING and confidence=0.0
    so that the learning service treats it as uninformative.

Confidence
----------
    Both sources are authoritative primary data:
        USDA NASS     → confidence = 1.0 (when observed)
        yfinance ZC=F → confidence = 1.0

Usage
-----
    pipeline = CornPipeline(nass_client, nasdaq_client)
    record   = await pipeline.fetch_evidence(target_date)
    engine.ingest(record)
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date
from uuid import uuid4

from ...agriculture_weekly import canonical_weekly_timestamp, latest_week_ending_on_or_before
from ....engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)
from ..domain import get_variables
from .nasdaq_client import CornNASDAQSnapshot, NASDAQClient
from .usda_nass_client import CornNASSSnapshot, USDANASSClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sigmoid calibration helpers (duplicated from nat-gas pipeline to avoid
# cross-domain imports; shared utility could be extracted later)
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99

_PLANTING_DELAY_THRESHOLD = 5.0   # pp behind 5yr avg
_DROUGHT_THRESHOLD = 55.0         # % good+excellent


def _soft_bool(signal: float) -> float:
    """Sigmoid-calibrated P(True), clamped to [0.01, 0.99]."""
    return max(_CLAMP_LO, min(_CLAMP_HI, _sigmoid(signal)))


class CornPipeline:
    """
    Fetches USDA NASS and yfinance ZC=F data concurrently and
    converts them into a single EvidenceRecord.

    Parameters
    ----------
    nass   : USDANASSClient
    nasdaq : NASDAQClient
        Compatibility name for the yfinance-backed price client.
    """

    def __init__(
        self,
        nass:   USDANASSClient,
        nasdaq: NASDAQClient,
    ) -> None:
        self._nass   = nass
        self._nasdaq = nasdaq

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        """
        Fetch data for `target_date` from both sources concurrently and
        return a fully-populated EvidenceRecord.

        Raises
        ------
        IOError
            If the price client fails to return usable data.
            NASS failures degrade gracefully to MISSING assignments.
        """
        week_end = latest_week_ending_on_or_before(target_date)
        nass_snap, nasdaq_snap = await asyncio.gather(
            self._nass.fetch_snapshot(week_end),
            self._nasdaq.fetch_snapshot(week_end),
        )
        record = self.build_evidence_record(nass_snap, nasdaq_snap)
        # Distinguish MISSING (API failure / off-season) from False in the log
        def _obs_label(raw_pct, derived_bool) -> str:
            if raw_pct is None:
                return "MISSING"
            return str(derived_bool)

        amap = {a.variable_id: a for a in record.observed_assignments}
        variables = get_variables()

        def _p(varname: str) -> str:
            a = amap.get(variables[varname].variable_id)
            if a and a.probabilities:
                return f"p={a.probabilities.get(True, 0):.2f}"
            if a and a.missingness == MissingnessType.MISSING:
                return "MISSING"
            return "hard"

        logger.info(
            "Evidence for %s [soft]: "
            "PlantingDelayed=%s(%s) DroughtIndex=%s(%s) "
            "YieldForecastDown=%s(%s) CornPriceUp=%s(%s)",
            week_end,
            _obs_label(nass_snap.planting_progress_pct, nass_snap.planting_delayed),
            _p("PlantingDelayed"),
            _obs_label(nass_snap.condition_good_exc_pct, nass_snap.drought_index),
            _p("DroughtIndex"),
            _obs_label(nass_snap.yield_forecast_bu_ac, nass_snap.yield_forecast_down),
            _p("YieldForecastDown"),
            nasdaq_snap.price_up,
            _p("CornPriceUp"),
        )
        return record

    # ------------------------------------------------------------------
    # Pure mapping: snapshots → EvidenceRecord  (no I/O; testable sync)
    # ------------------------------------------------------------------

    @staticmethod
    def build_evidence_record(
        nass:   CornNASSSnapshot,
        nasdaq: CornNASDAQSnapshot,
    ) -> EvidenceRecord:
        """
        Map CornNASSSnapshot + CornNASDAQSnapshot to an EvidenceRecord.

        This method is synchronous and has no external dependencies.
        It is the primary target for unit tests.
        """
        variables = get_variables()
        target_date = latest_week_ending_on_or_before(nass.target_date)

        # ---- NASS-derived assignments (seasonal missingness or soft evidence) ----

        # PlantingDelayed: soft P(True) from gap relative to threshold
        p_planting = None
        if nass.planting_progress_pct is not None and nass.planting_5yr_avg_pct is not None:
            signal = (
                (nass.planting_5yr_avg_pct - _PLANTING_DELAY_THRESHOLD - nass.planting_progress_pct)
                / 10.0
            )
            p_planting = _soft_bool(signal)

        # DroughtIndex: soft P(True) from distance below drought threshold
        p_drought = None
        if nass.condition_good_exc_pct is not None:
            signal = (_DROUGHT_THRESHOLD - nass.condition_good_exc_pct) / 10.0
            p_drought = _soft_bool(signal)

        # YieldForecastDown: soft P(True) from fractional shortfall vs prior year
        p_yield_down = None
        if nass.yield_forecast_bu_ac is not None and nass.yield_prior_year_bu_ac is not None:
            prior_safe = max(abs(nass.yield_prior_year_bu_ac), 0.01)
            signal = (nass.yield_prior_year_bu_ac - nass.yield_forecast_bu_ac) / (0.05 * prior_safe)
            p_yield_down = _soft_bool(signal)

        assignments = [
            _nass_soft_assignment(
                variable_id=variables["PlantingDelayed"].variable_id,
                value=nass.planting_delayed,
                is_observed=nass.planting_progress_pct is not None,
                p_true=p_planting,
            ),
            _nass_soft_assignment(
                variable_id=variables["DroughtIndex"].variable_id,
                value=nass.drought_index,
                is_observed=nass.condition_good_exc_pct is not None,
                p_true=p_drought,
            ),
            _nass_soft_assignment(
                variable_id=variables["YieldForecastDown"].variable_id,
                value=nass.yield_forecast_down,
                is_observed=nass.yield_forecast_bu_ac is not None,
                p_true=p_yield_down,
            ),
        ]

        # ---- yfinance-derived assignment (soft P(True) from price vs rolling avg) ----
        avg_safe = max(abs(nasdaq.rolling_20d_avg_cents), 0.01)
        p_price_up = _soft_bool(
            (nasdaq.settle_cents_per_bushel - nasdaq.rolling_20d_avg_cents) / (0.05 * avg_safe)
        )
        assignments.append(
            ObservedAssignment(
                variable_id=variables["CornPriceUp"].variable_id,
                observed_value=nasdaq.price_up,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=1.0,
                probabilities={True: p_price_up, False: 1.0 - p_price_up},
            )
        )

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=canonical_weekly_timestamp(target_date),
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                f"USDA-NASS:quickstats.nass.usda.gov"
                f"+YFINANCE:ZC=F"
                f"@iso-week-ending:{target_date}"
            ),
            confidence=1.0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nass_soft_assignment(
    *,
    variable_id,
    value: bool,
    is_observed: bool,
    p_true: float | None = None,
) -> ObservedAssignment:
    """
    Build an ObservedAssignment for a NASS-derived variable.

    When ``is_observed`` is False (off-season / API failure / data unavailable)
    the assignment is MISSING with confidence=0.0.  This correctly represents
    an absence of evidence — never a negative signal.

    When ``is_observed`` is True and ``p_true`` is provided the assignment is
    SOFT_OBSERVED with a sigmoid-calibrated probability distribution.
    ``observed_value`` retains the hard Boolean (MAP) for backward compat.

    When ``is_observed`` is True but ``p_true`` is None (insufficient raw data
    to compute a signal) the assignment falls back to hard OBSERVED.
    """
    if not is_observed:
        return ObservedAssignment(
            variable_id=variable_id,
            observed_value=False,   # default sentinel; missingness=MISSING is authoritative
            missingness=MissingnessType.MISSING,
            confidence=0.0,
        )
    if p_true is not None:
        return ObservedAssignment(
            variable_id=variable_id,
            observed_value=value,   # MAP value for backward compat
            missingness=MissingnessType.SOFT_OBSERVED,
            confidence=1.0,
            probabilities={True: p_true, False: 1.0 - p_true},
        )
    # Fallback: hard observation (5yr_avg unavailable etc.)
    return ObservedAssignment(
        variable_id=variable_id,
        observed_value=value,
        missingness=MissingnessType.OBSERVED,
        confidence=1.0,
    )
