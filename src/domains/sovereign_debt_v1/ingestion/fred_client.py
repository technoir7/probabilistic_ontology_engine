"""
FREDClient — sovereign debt domain FRED series fetcher.

Series fetched
--------------
DGS10         Market Yield on 10-Year Treasury (daily, %)
              Used for: USYieldSpiking (13-week z-score)

BAMLH0A0HYM2  ICE BofA US High Yield OAS (daily, %)
              Used for: SpreadWidening (z-score), CreditDefaultRisk (level)

DEXUSEU       USD/EUR spot rate (daily; lower = stronger USD)
              Used for: DollarStrengthening (inverted z-score)

WALCL         Fed Total Assets (weekly, USD billions)
              Used for: FedBalanceSheetShrinking (13w change),
                        GlobalLiquidityContracting (composite)

DTWEXBGS      Trade Weighted U.S. Dollar Index: Broad, Goods (weekly)
              Used for: EMStressElevated (z-score)

GFDEBTN       Federal Debt: Total Public Debt (quarterly, USD billions)
              Used for: FiscalDominanceRisk (YoY growth rate trend)

M2SL          M2 Money Stock (monthly, USD billions)
              Used for: GlobalLiquidityContracting (composite with WALCL)

The client itself is shared (domains/sources/fred.py); this module only says
which series sovereign-debt-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "dgs10":       "DGS10",
    "hy_spread":   "BAMLH0A0HYM2",
    "usd_eur":     "DEXUSEU",
    "fed_balance": "WALCL",
    "broad_usd":   "DTWEXBGS",
    "fed_debt":    "GFDEBTN",
    "m2":          "M2SL",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "DGS10":        400,   # 52+ weeks of daily for z-score
    "BAMLH0A0HYM2": 400,   # 52+ weeks daily for z-score and level
    "DEXUSEU":      400,   # 52+ weeks daily for z-score
    "WALCL":        140,   # 20 weeks for 13w change + safety
    "DTWEXBGS":     400,   # 52+ weeks weekly for z-score
    "GFDEBTN":      1500,  # ~4 years quarterly for YoY trend
    "M2SL":         180,   # 6 months for 3m growth rate
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
