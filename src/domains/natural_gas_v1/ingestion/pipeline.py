"""
NaturalGasPipeline — combines NOAA + EIA observations into EvidenceRecords.

The pipeline is the single point that owns the mapping from raw API data to
domain variable UUIDs.  It fetches both sources concurrently and produces one
EvidenceRecord per call, with all four variables observed at a level.

Variable mapping (REFACTOR_SPEC D25)
------------------------------------
Each variable gets a signed signal: its distance from the line that names
it, in the unit given below. The signal is read as a level, observed exactly
(sources.grades): low below -0.5, mid within ±0.5, high above +0.5.

    TempAnom   : (temp_c − monthly_normal) / 2.0 °C
    HeatingDem : (hdd − 5.0) / 5.0
    StorageDraw: −storage_change_bcf / 20.0 Bcf
    PriceUp    : (price − median) / (0.05 × median)

Usage
-----
    pipeline = NaturalGasPipeline(noaa_client, eia_client)
    record = await pipeline.fetch_evidence(target_date)
    engine.ingest(record)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from ....engine.schemas import EvidenceRecord
from ..domain import get_variables
from .eia_client import EIAClient, NatGasSnapshot
from .noaa_client import DailyClimateObs, MONTHLY_NORMALS_C, NOAAClient
from ...sources.grades import build_graded_record

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

    async def fetch_evidence(
        self,
        target_date: date,
        eia_target_date: date | None = None,
        use_latest_eia: bool = False,
    ) -> EvidenceRecord:
        """
        Fetch data for `target_date` from both APIs concurrently and return
        a fully-populated EvidenceRecord.

        Raises
        ------
        IOError
            If either API fails to return usable data.
        """
        if eia_target_date is None and not use_latest_eia:
            eia_target_date = target_date

        climate_obs, gas_snapshot = await asyncio.gather(
            self._noaa.fetch_daily_obs(target_date),
            self._eia.fetch_snapshot(eia_target_date),
        )
        record = self.build_evidence_record(climate_obs, gas_snapshot)
        names = {v.variable_id: name for name, v in get_variables().items()}
        logger.info(
            (
                "Evidence for %s: %s | "
                "latest_price=%.3f median_price=%.3f "
                "storage_current=%.1f storage_previous=%.1f"
            ),
            target_date,
            " ".join(f"{names[a.variable_id]}={a.observed_value}" for a in record.observed_assignments),
            gas_snapshot.latest_price,
            gas_snapshot.median_price,
            gas_snapshot.storage_current_bcf,
            gas_snapshot.storage_prev_bcf,
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
        Map DailyClimateObs + NatGasSnapshot to an EvidenceRecord, each
        variable observed at the level of its signal (D25).

        This method is synchronous and has no external dependencies.
        It is the primary target for unit tests.
        """
        station_conf = _station_confidence(climate_obs.stations_used)
        monthly_normal = MONTHLY_NORMALS_C.get(climate_obs.target_date.month, 12.0)
        median_safe = max(abs(gas_snapshot.median_price), 0.01)
        return build_graded_record(
            module_id="natural-gas-v1",
            variables=get_variables(),
            signals={
                "TempAnom": (climate_obs.mean_temp_c - monthly_normal) / 2.0,
                "HeatingDem": (climate_obs.hdd - 5.0) / 5.0,
                "StorageDraw": -gas_snapshot.storage_change_bcf / 20.0,
                "PriceUp": (gas_snapshot.latest_price - gas_snapshot.median_price) / (0.05 * median_safe),
            },
            confidence={
                "TempAnom": station_conf,
                "HeatingDem": station_conf,
                "StorageDraw": 1.0,
                "PriceUp": 1.0,
            },
            target_date=climate_obs.target_date,
            source_ref=(
                f"NOAA:ncei.daily-summaries+EIA:NG.NW2_EPG0_SWO_R48_BCF.W"
                f"+NG.RNGWHHD.D@{climate_obs.target_date}"
            ),
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
