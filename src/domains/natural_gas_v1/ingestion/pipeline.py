"""
NaturalGasPipeline — combines NOAA + EIA observations into EvidenceRecords.

The pipeline is the single point that owns the mapping from raw API data to
domain variable UUIDs.  It fetches both sources concurrently and produces one
EvidenceRecord per call, containing all four Boolean assignments.

Variable mapping
----------------
    TempAnom    ← DailyClimateObs.temp_anom / mean_temp_c vs monthly normal
    HeatingDem  ← DailyClimateObs.heating_dem / hdd magnitude
    StorageDraw ← NatGasSnapshot.storage_draw / storage_change_bcf magnitude
    PriceUp     ← NatGasSnapshot.price_up / price vs median distance

Soft evidence
-------------
All four Boolean assignments are emitted as SOFT_OBSERVED with sigmoid-
calibrated probability distributions.  The boolean MAP value is preserved
in observed_value for backward compatibility.  Calibration functions:

    TempAnom   : P(True) = sigmoid((temp_c − monthly_normal) / 2.0)
    HeatingDem : P(True) = sigmoid((hdd − 5.0) / 5.0)
    StorageDraw: P(True) = sigmoid(−storage_change_bcf / 20.0)
    PriceUp    : P(True) = sigmoid((price − median) / (0.05 × median))

All P(True) values are clamped to [0.01, 0.99].

Usage
-----
    pipeline = NaturalGasPipeline(noaa_client, eia_client)
    record = await pipeline.fetch_evidence(target_date)
    engine.ingest(record)
"""
from __future__ import annotations

import asyncio
import logging
import math
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
from .noaa_client import DailyClimateObs, MONTHLY_NORMALS_C, NOAAClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sigmoid calibration helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


_CLAMP_LO: float = 0.01
_CLAMP_HI: float = 0.99


def _soft_bool(signal: float) -> float:
    """Convert a signed signal to P(True) via sigmoid, clamped to [0.01, 0.99]."""
    return max(_CLAMP_LO, min(_CLAMP_HI, _sigmoid(signal)))


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
        # Retrieve soft probabilities from assignments for logging
        amap = {a.variable_id: a for a in record.observed_assignments}
        variables = get_variables()

        def _p(varname: str) -> float:
            a = amap.get(variables[varname].variable_id)
            if a and a.probabilities:
                return a.probabilities.get(True, float("nan"))
            return float("nan")

        logger.info(
            (
                "Evidence for %s [soft]: "
                "TempAnom=%s(p=%.2f) HeatingDem=%s(p=%.2f) "
                "StorageDraw=%s(p=%.2f) PriceUp=%s(p=%.2f) | "
                "latest_price=%.3f median_price=%.3f "
                "storage_current=%.1f storage_previous=%.1f"
            ),
            target_date,
            climate_obs.temp_anom, _p("TempAnom"),
            climate_obs.heating_dem, _p("HeatingDem"),
            gas_snapshot.storage_draw, _p("StorageDraw"),
            gas_snapshot.price_up, _p("PriceUp"),
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
        Map DailyClimateObs + NatGasSnapshot to an EvidenceRecord.

        Produces SOFT_OBSERVED assignments with sigmoid-calibrated probability
        distributions.  The boolean MAP value is preserved in ``observed_value``
        for backward compatibility with callers that only read the hard field.

        This method is synchronous and has no external dependencies.
        It is the primary target for unit tests.
        """
        variables = get_variables()
        station_conf = _station_confidence(climate_obs.stations_used)

        # --- TempAnom: P(True) ∝ distance above monthly normal ---
        monthly_normal = MONTHLY_NORMALS_C.get(climate_obs.target_date.month, 12.0)
        p_temp_anom = _soft_bool(
            (climate_obs.mean_temp_c - monthly_normal) / 2.0
        )

        # --- HeatingDem: P(True) ∝ HDD magnitude ---
        p_heating_dem = _soft_bool(
            (climate_obs.hdd - 5.0) / 5.0
        )

        # --- StorageDraw: P(True) ∝ magnitude of draw (negative change) ---
        p_storage_draw = _soft_bool(
            -gas_snapshot.storage_change_bcf / 20.0
        )

        # --- PriceUp: P(True) ∝ distance above rolling median (5 % scale) ---
        median_safe = max(abs(gas_snapshot.median_price), 0.01)
        p_price_up = _soft_bool(
            (gas_snapshot.latest_price - gas_snapshot.median_price) / (0.05 * median_safe)
        )

        assignments = [
            ObservedAssignment(
                variable_id=variables["TempAnom"].variable_id,
                observed_value=climate_obs.temp_anom,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=station_conf,
                probabilities={True: p_temp_anom, False: 1.0 - p_temp_anom},
            ),
            ObservedAssignment(
                variable_id=variables["HeatingDem"].variable_id,
                observed_value=climate_obs.heating_dem,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=station_conf,
                probabilities={True: p_heating_dem, False: 1.0 - p_heating_dem},
            ),
            ObservedAssignment(
                variable_id=variables["StorageDraw"].variable_id,
                observed_value=gas_snapshot.storage_draw,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=1.0,
                probabilities={True: p_storage_draw, False: 1.0 - p_storage_draw},
            ),
            ObservedAssignment(
                variable_id=variables["PriceUp"].variable_id,
                observed_value=gas_snapshot.price_up,
                missingness=MissingnessType.SOFT_OBSERVED,
                confidence=1.0,
                probabilities={True: p_price_up, False: 1.0 - p_price_up},
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
