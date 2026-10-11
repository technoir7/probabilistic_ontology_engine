"""
FREDClient — fetches macroeconomic data from api.stlouisfed.org (FRED API v1).

API key must be supplied via the FRED_API_KEY environment variable (or loaded
from .env by the caller).

Series fetched
--------------
T10Y2Y        Market Yield on U.S. Treasury Securities at 10-Year minus 2-Year
              Constant Maturity (percentage points, daily business days).
              Used for: YieldCurveInverted

CPIAUCSL      Consumer Price Index for All Urban Consumers: All Items
              (seasonally adjusted, monthly, index 1982-84=100).
              Used for: InflationShock (12-month YoY % change)

WALCL         Assets: Total Assets: Total Assets (Less Eliminations from
              Consolidation): Wednesday Level (weekly, USD billions).
              Used for: LiquidityStress (13-week % change)

BAMLH0A0HYM2  ICE BofA US High Yield Index Option-Adjusted Spread (%, daily).
              Used for: CreditSpreadStress (52-week rolling z-score)

VIXCLS        CBOE Volatility Index: VIX (daily, business days).
              Used for: VolatilityShock (vs rolling 90-day 75th percentile)

DEXUSEU       U.S. Dollars to Euro Spot Exchange Rate (daily, higher = stronger USD).
              Used for: DollarStrength (52-week rolling z-score)

UNRATE        Unemployment Rate (seasonally adjusted, monthly, percent).
              Used for: EquityRiskOn (3-month change direction)

NASDAQCOM     NASDAQ Composite Index (daily business days, index value).
              Used for: AIRiskOn (13-week return z-score vs historical)

FRED API endpoint
-----------------
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id={series_id}
    &api_key={key}
    &observation_start={YYYY-MM-DD}
    &observation_end={YYYY-MM-DD}
    &sort_order=desc
    &limit={n}
    &file_type=json

Missing values in FRED are returned as the string ".".

Error handling
--------------
- Raises IOError on HTTP failures or empty responses.
- Missing ("." valued) observations are silently skipped.
- If fewer observations are returned than needed, raises IOError.

The client itself is shared (domains/sources/fred.py); this module only says
which series macro-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES = {
    "yield_curve":     "T10Y2Y",
    "cpi":             "CPIAUCSL",
    "fed_balance":     "WALCL",
    "hy_spread":       "BAMLH0A0HYM2",
    "vix":             "VIXCLS",
    "usd_eur":         "DEXUSEU",
    "unemployment":    "UNRATE",
    "nasdaq":          "NASDAQCOM",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "T10Y2Y":        35,    # 5 weeks of daily data for weekly median
    "CPIAUCSL":      430,   # 14 months for 12m YoY + safety
    "WALCL":         140,   # 20 weeks for 13w % change + safety
    "BAMLH0A0HYM2":  400,   # 52+ weeks of daily for z-score
    "VIXCLS":        120,   # 90-day rolling percentile + safety
    "DEXUSEU":       400,   # 52+ weeks for z-score
    "UNRATE":        450,   # 15 months (12m mean + 3m delta + safety)
    "NASDAQCOM":     730,   # 2+ years for stable 13w return z-score
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
