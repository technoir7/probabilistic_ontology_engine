"""
NOAAClient — daily high and low temperatures from NOAA NCEI's Global
Historical Climatology Network daily summaries (Access Data Service).

No API key required. Unlike api.weather.gov, which serves only about the last
week of observations, NCEI keeps the full history, so a rebuild can refetch
past years. A day's summary appears about four days later.

Monitored stations (representative CONUS coverage, weighted toward heating-
demand regions), with their GHCN-Daily ids:
    KORD  Chicago O'Hare          USW00094846  (Midwest / Great Lakes)
    KJFK  New York Kennedy        USW00094789  (Northeast)
    KATL  Atlanta Hartsfield      USW00013874  (Southeast)
    KDFW  Dallas/Fort Worth       USW00003927  (South-Central)
    KDEN  Denver International    USW00003017  (Mountain)

One request fetches every station's summary for the target day. A station's
daily mean is the midpoint of its high and low, the convention degree days
are defined by; station means are averaged to a CONUS mean.

Derived quantities returned in `DailyClimateObs`:
    mean_temp_c   — CONUS mean daily temperature (Celsius)
    hdd           — heating degree days: max(0, 18.33 - mean_temp_c)
                    (18.33°C = 65°F, the standard US HDD base)
    temp_anom     — True if mean_temp_c > monthly seasonal normal
    heating_dem   — True if hdd > 0  (any heating demand exists)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Monitored stations
# ---------------------------------------------------------------------------

STATIONS: dict[str, str] = {
    "KORD": "USW00094846",
    "KJFK": "USW00094789",
    "KATL": "USW00013874",
    "KDFW": "USW00003927",
    "KDEN": "USW00003017",
}

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
    Asynchronous client for NCEI's daily-summaries service.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        If provided, this client is used for all HTTP requests and is NOT
        closed on exit (caller owns it).  Pass an AsyncMock here in tests.
        If omitted, the NOAAClient creates and manages its own client.
    """

    URL = "https://www.ncei.noaa.gov/access/services/data/v1"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "NOAAClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def fetch_daily_obs(self, target_date: date) -> DailyClimateObs:
        """
        Fetch every monitored station's summary for `target_date` and
        aggregate them. Raises IOError if the request fails or fewer than
        2 stations have both a high and a low.
        """
        day = target_date.isoformat()
        params = {
            "dataset": "daily-summaries",
            "stations": ",".join(STATIONS.values()),
            "startDate": day,
            "endDate": day,
            "dataTypes": "TMAX,TMIN",
            "units": "metric",
            "format": "json",
        }
        try:
            resp = await self._client.get(self.URL, params=params)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            raise IOError(f"NOAA NCEI request failed for {day}: {exc}") from exc

        icao = {ghcn: code for code, ghcn in STATIONS.items()}
        station_means: dict[str, float] = {}
        for row in rows:
            if row.get("DATE") == day and row.get("STATION") in icao and "TMAX" in row and "TMIN" in row:
                station_means[icao[row["STATION"]]] = (float(row["TMAX"]) + float(row["TMIN"])) / 2

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
