"""
FREDClient — labor-market-v1 FRED series fetcher.

Series fetched
--------------
UNRATE          Unemployment Rate (monthly, seasonally adjusted, %)
                Used for: UnemploymentRising (z-score), TightLaborMarket (composite)

CES0500000003   Average Hourly Earnings of All Employees: Total Private (monthly, $/hr)
                Used for: WageInflationPersistent (YoY z-score), RealWageGrowthPositive

JTSJOL          Job Openings: Total Nonfarm (monthly, thousands)
                Used for: JobOpeningsFalling (inverted z-score), TightLaborMarket

ICSA            Initial Claims (weekly, thousands)
                Used for: LayoffCycleBeginning (z-score)

PRS85006092     Nonfarm Business Sector: Real Output Per Hour of All Persons (quarterly, index)
                Used for: LaborProductivityWeak (YoY change)

CIVPART         Labor Force Participation Rate (monthly, seasonally adjusted, %)
                Used for: ParticipationRateFalling (inverted z-score)

CPIAUCSL        CPI All Urban Consumers (monthly, seasonally adjusted)
                Used for: RealWageGrowthPositive (nominal wage - CPI)

The client itself is shared (domains/sources/fred.py); this module only says
which series labor-market-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "unrate":       "UNRATE",
    "wages":        "CES0500000003",
    "job_openings": "JTSJOL",
    "initial_claims": "ICSA",
    "productivity": "PRS85006092",
    "participation": "CIVPART",
    "cpi":          "CPIAUCSL",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "UNRATE":        450,   # 15 months for trend + z-score
    "CES0500000003": 430,   # 14 months for 12m YoY
    "JTSJOL":        430,   # 14 months for z-score
    "ICSA":          400,   # 52+ weeks for z-score
    "PRS85006092":   1500,  # ~4 years quarterly for YoY trend
    "CIVPART":       430,   # 14 months for z-score
    "CPIAUCSL":      430,   # 14 months for real wage computation
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
