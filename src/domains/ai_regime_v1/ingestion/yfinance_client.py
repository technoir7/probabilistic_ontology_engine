"""
AIYFinanceClient — yfinance wrapper for AI regime market data.

Fetches daily close prices for four tickers:
    ^SOX   Philadelphia Semiconductor Index      SemiconductorMomentum
    QQQ    Invesco QQQ Trust (NASDAQ-100 ETF)    MarketConcentrationExtreme
                                                  TechValuationDetached
    RSP    Invesco S&P 500 Equal Weight ETF       MarketConcentrationExtreme
    ^VIX   CBOE Volatility Index                 AIRiskPremiumCompressed

Data format returned
--------------------
A dict: ticker_symbol → list[YFObservation] (newest-first), where
YFObservation carries (obs_date, close_price).  Missing or zero values
are excluded.

Lookback periods
----------------
    ^SOX   3 years (for stable 13-week return z-score distribution)
    QQQ    3 years (for concentration ratio and 3-year valuation z-score)
    RSP    3 years (for concentration ratio)
    ^VIX   2 years (for VIX rolling mean/std)

Design notes
------------
- Uses asyncio.to_thread to avoid blocking the event loop on the
  synchronous yfinance.download call.
- A download_fn parameter allows test injection without network calls.
- The MultiIndex DataFrame returned by yfinance multi-ticker downloads
  is handled with defensive column extraction logic (same pattern as
  the corn NASDAQClient).

The client itself is shared (domains/sources/yfinance.py); this module only
names the tickers ai-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.yfinance import YFinanceClient, YFObservation

__all__ = ['FETCH_LOOKBACK_DAYS', 'AI_TICKERS', 'AIYFinanceClient', 'YFObservation']

AI_TICKERS: list[str] = ["^SOX", "QQQ", "RSP", "^VIX"]

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "^SOX":  800,   # ~3 years for return z-score history
    "QQQ":   800,   # ~3 years for concentration ratio and valuation
    "RSP":   800,   # ~3 years for concentration ratio
    "^VIX":  560,   # ~2 years for VIX rolling mean/std
}


class AIYFinanceClient(YFinanceClient):
    TICKERS = AI_TICKERS
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 800
