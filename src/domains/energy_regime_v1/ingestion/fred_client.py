"""
FREDClient — energy-regime-v1 FRED series fetcher.

Series fetched
--------------
DCOILWTICO    WTI Crude Oil Prices (daily, USD/barrel)
              Used for: OPECSupplyConstraint (13w momentum), GeopoliticalRiskElevated (volatility)

CPIENGSL      CPI: Energy (monthly, seasonally adjusted, index)
              Used for: EnergyInflationPersistent (12-month YoY % change)

INDPRO        Industrial Production Index (monthly, seasonally adjusted)
              Used for: DemandDestructionRisk (3-month change direction)

UNRATE        Unemployment Rate (monthly, seasonally adjusted, %)
              Used for: DemandDestructionRisk (direction composite)

The client itself is shared (domains/sources/fred.py); this module only says
which series energy-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "wti_crude":   "DCOILWTICO",
    "energy_cpi":  "CPIENGSL",
    "indpro":      "INDPRO",
    "unrate":      "UNRATE",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "DCOILWTICO": 400,   # 52+ weeks for momentum and volatility
    "CPIENGSL":   430,   # 14 months for 12m YoY
    "INDPRO":     180,   # 6 months for 3m change
    "UNRATE":     180,   # 6 months for trend
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
