"""
FREDClient — geopolitics-v1 FRED series fetcher.

Series fetched
--------------
DCOILWTICO  WTI Crude Oil Price (daily, USD/bbl)
            Used for: TradeDisruptionRisk, SupplyChainStress, EnergyWeaponizationRisk

PPIACO      Producer Price Index, All Commodities (monthly)
            Used for: SupplyChainStress (composite)

DTWEXBGS    Trade Weighted U.S. Dollar Index: Broad, Goods (weekly)
            Used for: CurrencyWarSignal (volatility)

INDPRO      Industrial Production Index (monthly)
            Used for: GlobalTradeVolumeWeak (inverted 3m change)

The client itself is shared (domains/sources/fred.py); this module only says
which series geopolitics-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "wti":       "DCOILWTICO",
    "ppi":       "PPIACO",
    "broad_usd": "DTWEXBGS",
    "indpro":    "INDPRO",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "DCOILWTICO": 400,
    "PPIACO":     400,
    "DTWEXBGS":   400,
    "INDPRO":     400,
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
