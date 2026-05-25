"""
NaturalGasPipeline — combines NOAA + EIA observations into EvidenceRecords.

The pipeline is the single point that owns the mapping from raw API data to
domain variable UUIDs.  It fetches both sources concurrently and produces one
EvidenceRecord per call, containing all four Boolean assignments.

Variable mapping
----------------
    TempAnom    ← DailyClimateObs.temp_anom
    HeatingDem  ← DailyClimateObs.heating_dem
    StorageDraw ← NatGasSnapshot.storage_draw
    PriceUp     ← NatGasSnapshot.price_up

Usage
-----
    pipeline = NaturalGasPipeline(noaa_client, eia_client)
    record = await pipeline.fetch_evidence(target_date)
    engine.ingest(record)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from ....engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)
from ..domain import get_variables
from .eia_client import EIAClient, NatGasSnapshot
from .noaa_client import DailyClimateObs, NOAAClient

logger = logging.getLogger(__name__)


class NaturalGasPipeline:
    """
    Fetches NOAA climate observations and EIA natural gas market data
    concurrently and converts them into a single EvidenceRecord.

    Parameters
    ----------
    noaa : NOAAClient
    eia  : EIAClient
    """

    def __init__(self, noaa: NOAAClient, eia: EIAClient) -> None:
        self._noaa = noaa
        self._eia = eia

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        """
        Fetch data for `target_date` from both APIs concurrently and return
        a fully-populated EvidenceRecord.

        Raises
        ------
        IOError
            If either API fails to return usable data.
        """
        climate_obs, gas_snapshot = await asyncio.gather(
            self._noaa.fetch_daily_obs(target_date),
            self._eia.fetch_snapshot(),
        )
        record = self.build_evidence_record(climate_obs, gas_snapshot)
        logger.info(
            "Evidence for %s: TempAnom=%s HeatingDem=%s StorageDraw=%s PriceUp=%s",
            target_date,
            climate_obs.temp_anom,
            climate_obs.heating_dem,
            gas_snapshot.storage_draw,
            gas_snapshot.price_up,
        )
        return record

    # ------------------------------------------------------------------
    # Pure mapping: raw data → EvidenceRecord  (no I/O; testable sync)
    # ------------------------------------------------------------------

    @staticmethod
    def build_evidence_record(
        climate_obs: DailyClimateObs,
        gas_snapshot: NatGasSnapshot,
    ) -> EvidenceRecord:
        """
        Map DailyClimateObs + NatGasSnapshot to an EvidenceRecord.

        This method is synchronous and has no external dependencies.
        It is the primary target for unit tests.
        """
        variables = get_variables()

        assignments = [
            ObservedAssignment(
                variable_id=variables["TempAnom"].variable_id,
                observed_value=climate_obs.temp_anom,
                missingness=MissingnessType.OBSERVED,
                confidence=_station_confidence(climate_obs.stations_used),
            ),
            ObservedAssignment(
                variable_id=variables["HeatingDem"].variable_id,
                observed_value=climate_obs.heating_dem,
                missingness=MissingnessType.OBSERVED,
                confidence=_station_confidence(climate_obs.stations_used),
            ),
            ObservedAssignment(
                variable_id=variables["StorageDraw"].variable_id,
                observed_value=gas_snapshot.storage_draw,
                missingness=MissingnessType.OBSERVED,
                confidence=1.0,   # EIA is the authoritative source; no uncertainty
            ),
            ObservedAssignment(
                variable_id=variables["PriceUp"].variable_id,
                observed_value=gas_snapshot.price_up,
                missingness=MissingnessType.OBSERVED,
                confidence=1.0,
            ),
        ]

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=datetime(
                climate_obs.target_date.year,
                climate_obs.target_date.month,
                climate_obs.target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=assignments,
            source_type=SourceType.API,
            source_ref=(
                f"NOAA:api.weather.gov+EIA:NG.NW2_EPG0_SWO_R48_BCF.W"
                f"+NG.RNGWHHD.D@{climate_obs.target_date}"
            ),
            confidence=_station_confidence(climate_obs.stations_used),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _station_confidence(n_stations: int) -> float:
    """
    Confidence weight based on how many NOAA stations reported.
    Full confidence (1.0) when all 5 stations are available.
    Minimum 0.4 when the floor of 2 stations is met.
    """
    total = 5  # STATIONS count in noaa_client
    return max(0.4, n_stations / total)
