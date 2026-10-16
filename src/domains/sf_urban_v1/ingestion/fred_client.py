"""
FREDClient — sf-urban-v1 FRED series fetcher.

Series fetched (all Monthly, Seasonally Adjusted, San Francisco-Oakland-Fremont MSA)
-------------------------------------------------------------------------------------
SANF806INFO  All Employees: Information in SF-Oakland-Fremont, CA (thousands)
             Used for: TechHiringAccelerating

SANF806LEIH  All Employees: Leisure and Hospitality in SF-Oakland-Fremont, CA (thousands)
             Used for: FootTrafficRecovering

SANF806NA    All Employees: Total Nonfarm in SF-Oakland-Fremont, CA (thousands)
             Used for: PopulationFlowPositive (proxy)

Previous IDs SMU06418205101000001SA / SMU06418207072000001SA / SMU06418200000000001SA
all returned HTTP 400 "series does not exist" — replaced 2026-05-27.

The client itself is shared (domains/sources/fred.py); this module only says
which series sf-urban-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "info_emp":        "SANF806INFO",   # Information sector, SF-Oakland-Fremont, Monthly SA
    "hospitality_emp": "SANF806LEIH",  # Leisure & Hospitality, SF-Oakland-Fremont, Monthly SA
    "total_emp":       "SANF806NA",    # Total Nonfarm, SF-Oakland-Fremont, Monthly SA
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "SANF806INFO": 730,   # 2 years monthly for z-score
    "SANF806LEIH": 730,
    "SANF806NA":   730,
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 730
