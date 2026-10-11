"""
FREDClient — crypto-regime-v1 FRED series fetcher.

Series fetched
--------------
DEXUSEU   USD/EUR spot rate (daily; lower = stronger USD)
          Used for: DollarDebasementNarrative (inverted z-score)

The client itself is shared (domains/sources/fred.py); this module only says
which series crypto-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "dex_us_eu": "DEXUSEU",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "DEXUSEU": 400,   # 52+ weeks of daily for z-score
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
