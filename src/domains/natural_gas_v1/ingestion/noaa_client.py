"""
NOAAClient — fetches temperature observations from api.weather.gov.

No API key required. User-Agent header is mandatory per NWS policy.

Monitored stations (representative CONUS coverage, weighted toward heating-
demand regions):
    KORD  Chicago O'Hare          (Midwest / Great Lakes)
    KJFK  New York Kennedy        (Northeast)
    KATL  Atlanta Hartsfield      (Southeast)
    KDFW  Dallas/Fort Worth       (South-Central)
    KDEN  Denver International    (Mountain)

For each station the client fetches all hourly observations for the target UTC
date (up to 500 per station; major airports report every 4–5 minutes so a full
day yields ~300 readings).  Valid readings (non-null temperature, qualityControl
in {"V","C","S"}) are averaged to produce a per-station daily mean in Celsius.
Station means are then averaged to produce a CONUS mean.

Derived quantities returned in `DailyClimateObs`:
    mean_temp_c   — CONUS mean daily temperature (Celsius)
    hdd           — heating degree days: max(0, 18.33 - mean_temp_c)
                    (18.33°C = 65°F, the standard US HDD base)
    temp_anom     — True if mean_temp_c > monthly seasonal normal
    heating_dem   — True if hdd > 0  (any heating demand exists)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monitored stations
# ---------------------------------------------------------------------------

STATIONS: list[str] = ["KORD", "KJFK", "KATL", "KDFW", "KDEN"]

# ---------------------------------------------------------------------------
# Monthly CONUS temperature normals (°C) — approximate population-weighted
# averages across the five monitored stations, based on 30-year climatology.
# Used for TempAnom classification.
# ---------------------------------------------------------------------------

MONTHLY_NORMALS_C: dict[int, float] = {
    1: 1.5,   # January
    2: 3.5,   # February
    3: 8.0,   # March
    4: 13.0,  # April
    5: 18.0,  # May
    6: 22.5,  # June
    7: 25.0,  # July
    8: 24.0,  # August
    9: 19.5,  # September
    10: 13.5, # October
    11: 7.0,  # November
    12: 2.5,  # December
}

HDD_BASE_C: float = 18.33  # 65°F expressed in Celsius

# Quality-control codes accepted as valid observations
_VALID_QC: frozenset[str] = frozenset({"V", "C", "S"})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DailyClimateObs:
    target_date: date
    mean_temp_c: float          # CONUS mean temperature (Celsius)
    hdd: float                  # heating degree days (≥ 0)
    temp_anom: bool             # above seasonal normal?
    heating_dem: bool           # HDD > 0?
    stations_used: int          # number of stations with valid data
    station_means: dict[str, float]  # per-station means for diagnostics


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NOAAClient:
    """
    Asynchronous client for api.weather.gov station observations.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        If provided, this client is used for all HTTP requests and is NOT
        closed on exit (caller owns it).  Pass an AsyncMock here in tests.
        If omitted, the NOAAClient creates and manages its own client.
    """

    BASE_URL = "https://api.weather.gov"
    USER_AGENT = "probabilistic-ontology-engine/0.1 (natural-gas-domain)"
    _OBS_LIMIT = 500   # max observations per station per day (~300 for busy airports)

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT},
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "NOAAClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_daily_obs(self, target_date: date) -> DailyClimateObs:
        """
        Fetch and aggregate observations for all monitored stations on
        `target_date` (UTC).

        Returns a DailyClimateObs.  If fewer than 2 stations have valid
        data an IOError is raised.
        """
        start = datetime(
            target_date.year, target_date.month, target_date.day,
            0, 0, 0, tzinfo=timezone.utc,
        )
        end = start + timedelta(days=1)

        tasks = [
            self._fetch_station_mean(station, start, end)
            for station in STATIONS
        ]
        results: list[tuple[str, float | None]] = await asyncio.gather(*tasks)

        station_means: dict[str, float] = {}
        for station, mean in results:
            if mean is not None:
                station_means[station] = mean

        if len(station_means) < 2:
            raise IOError(
                f"Only {len(station_means)}/{len(STATIONS)} stations returned "
                f"valid data for {target_date}; need at least 2"
            )

        conus_mean = sum(station_means.values()) / len(station_means)
        hdd = max(0.0, HDD_BASE_C - conus_mean)
        normal = MONTHLY_NORMALS_C[target_date.month]

        return DailyClimateObs(
            target_date=target_date,
            mean_temp_c=conus_mean,
            hdd=hdd,
            temp_anom=conus_mean > normal,
            heating_dem=hdd > 0.0,
            stations_used=len(station_means),
            station_means=station_means,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_station_mean(
        self, station: str, start: datetime, end: datetime
    ) -> tuple[str, float | None]:
        """
        Return (station_id, daily_mean_c) or (station_id, None) on error.
        """
        url = f"{self.BASE_URL}/stations/{station}/observations"
        params = {
            "start": _fmt_utc(start),
            "end": _fmt_utc(end),
            "limit": self._OBS_LIMIT,
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("NOAA fetch failed for %s: %s", station, exc)
            return station, None

        temps: list[float] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            temp_obj = props.get("temperature", {}) or {}
            value = temp_obj.get("value")
            qc = temp_obj.get("qualityControl", "")
            if value is not None and qc in _VALID_QC:
                temps.append(float(value))

        if len(temps) < 3:
            logger.warning(
                "Station %s: only %d valid readings for %s; skipping",
                station, len(temps), start.date(),
            )
            return station, None

        return station, sum(temps) / len(temps)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _fmt_utc(dt: datetime) -> str:
    """Format a UTC datetime as 'YYYY-MM-DDTHH:MM:SSZ' for the NWS API."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
