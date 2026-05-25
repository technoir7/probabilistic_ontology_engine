"""
SoybeanPipeline — combines USDA NASS, USDA FAS, and Nasdaq Data Link observations
into EvidenceRecords for the soybean-v1 domain.

The pipeline owns the mapping from raw API snapshots to domain variable UUIDs.
All three sources are fetched concurrently.  The static `build_evidence_record`
method performs the pure mapping (no I/O) and is the primary unit-test target.

Variable mapping
----------------
    PlantingDelayed   ← SoybeanNASSSnapshot.planting_delayed
    DroughtIndex      ← SoybeanNASSSnapshot.drought_index
    YieldForecastDown ← SoybeanNASSSnapshot.yield_forecast_down
    ExportDemandHigh  ← SoybeanFASSnapshot.export_demand_high
    SoyPriceUp        ← SoybeanNASDAQSnapshot.price_up

Missingness handling
--------------------
    NASS data is only published during specific seasons (planting May-Jun,
    conditions Jun-Oct, yield Sep-Nov).  When a NASS field is None (off-season),
    the corresponding assignment uses MissingnessType.MISSING and confidence=0.0
    so that the learning service treats it as uninformative.

Confidence
----------
    All three sources are authoritative primary data:
        USDA NASS / FAS → confidence = 1.0 (when observed)
        Nasdaq ZS1       → confidence = 1.0

Usage
-----
    pipeline = SoybeanPipeline(nass_client, fas_client, nasdaq_client)
    record   = await pipeline.fetch_evidence(target_date)
    engine.ingest(record)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

from ....engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)
from ..domain import get_variables
from .nasdaq_client import SoybeanNASDAQSnapshot, NASDAQClient
from .usda_fas_client import SoybeanFASSnapshot, USDAFASClient
from .usda_nass_client import SoybeanNASSSnapshot, USDANASSClient

logger = logging.getLogger(__name__)


class SoybeanPipeline:
    """
    Fetches USDA NASS, USDA FAS, and Nasdaq ZS1 data concurrently and
    converts them into a single EvidenceRecord.

    Parameters
    ----------
    nass   : USDANASSClient
    fas    : USDAFASClient
    nasdaq : NASDAQClient
    """

    def __init__(
        self,
        nass:   USDANASSClient,
        fas:    USDAFASClient,
        nasdaq: NASDAQClient,
    ) -> None:
        self._nass   = nass
        self._fas    = fas
        self._nasdaq = nasdaq

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        """
        Fetch data for `target_date` from all three sources concurrently and
        return a fully-populated EvidenceRecord.

        Raises
        ------
        IOError
            If the FAS or Nasdaq client fails to return usable data.
            NASS failures degrade gracefully to MISSING assignments.
        """
        nass_snap, fas_snap, nasdaq_snap = await asyncio.gather(
            self._nass.fetch_snapshot(target_date),
            self._fas.fetch_snapshot(target_date),
            self._nasdaq.fetch_snapshot(target_date),
        )
        record = self.build_evidence_record(nass_snap, fas_snap, nasdaq_snap)
        logger.info(
            "Evidence for %s: PlantingDelayed=%s DroughtIndex=%s "
            "YieldForecastDown=%s ExportDemandHigh=%s SoyPriceUp=%s",
            target_date,
            nass_snap.planting_delayed,
            nass_snap.drought_index,
            nass_snap.yield_forecast_down,
            fas_snap.export_demand_high,
            nasdaq_snap.price_up,
        )
        return record

    # ------------------------------------------------------------------
    # Pure mapping: snapshots → EvidenceRecord  (no I/O; testable sync)
    # ------------------------------------------------------------------

    @staticmethod
    def build_evidence_record(
        nass:   SoybeanNASSSnapshot,
        fas:    SoybeanFASSnapshot,
        nasdaq: SoybeanNASDAQSnapshot,
    ) -> EvidenceRecord:
        """
        Map SoybeanNASSSnapshot + SoybeanFASSnapshot + SoybeanNASDAQSnapshot to an
        EvidenceRecord.

        This method is synchronous and has no external dependencies.
        It is the primary target for unit tests.
        """
        variables = get_variables()
        target_date = nass.target_date

        # ---- NASS-derived assignments (seasonal missingness) ----
        assignments = [
            _nass_assignment(
                variable_id=variables["PlantingDelayed"].variable_id,
                value=nass.planting_delayed,
                is_observed=nass.planting_progress_pct is not None,
            ),
            _nass_assignment(
                variable_id=variables["DroughtIndex"].variable_id,
                value=nass.drought_index,
                is_observed=nass.condition_good_exc_pct is not None,
            ),
            _nass_assignment(
                variable_id=variables["YieldForecastDown"].variable_id,
                value=nass.yield_forecast_down,
                is_observed=nass.yield_forecast_bu_ac is not None,
            ),
        ]

        # ---- FAS-derived assignment ----
        assignments.append(
            ObservedAssignment(
                variable_id=variables["ExportDemandHigh"].variable_id,
                observed_value=fas.export_demand_high,
                missingness=MissingnessType.OBSERVED,
                confidence=1.0,
            )
        )

        # ---- Nasdaq-derived assignment ----
        assignments.append(
            ObservedAssignment(
                variable_id=variables["SoyPriceUp"].variable_id,
                observed_value=nasdaq.price_up,
                missingness=MissingnessType.OBSERVED,
                confidence=1.0,
            )
        )

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                f"USDA-NASS:quickstats.nass.usda.gov"
                f"+USDA-FAS:apps.fas.usda.gov/gats"
                f"+NASDAQ:CHRIS/CME_S1"
                f"@{target_date}"
            ),
            confidence=1.0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nass_assignment(
    *,
    variable_id,
    value: bool,
    is_observed: bool,
) -> ObservedAssignment:
    """
    Build an ObservedAssignment for a NASS-derived variable.
    When `is_observed` is False (off-season / data unavailable), the
    assignment uses MissingnessType.MISSING and confidence=0.0.
    """
    return ObservedAssignment(
        variable_id=variable_id,
        observed_value=value,
        missingness=(
            MissingnessType.OBSERVED if is_observed
            else MissingnessType.MISSING
        ),
        confidence=1.0 if is_observed else 0.0,
    )
