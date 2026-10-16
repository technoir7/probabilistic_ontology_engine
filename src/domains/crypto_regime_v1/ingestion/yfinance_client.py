"""
CryptoYFinanceClient — yfinance wrapper for crypto regime market data.

Tickers fetched
---------------
BTC-USD  Bitcoin USD price  → RiskAssetCorrelation, DollarDebasementNarrative
QQQ      Nasdaq-100 ETF      → RiskAssetCorrelation
GLD      SPDR Gold ETF       → DollarDebasementNarrative

Lookback: 2 years for stable z-score distributions.

The client itself is shared (domains/sources/yfinance.py); this module only
names the tickers crypto-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.yfinance import YFinanceClient, YFObservation

__all__ = ['FETCH_LOOKBACK_DAYS', 'CRYPTO_YF_TICKERS', 'CryptoYFinanceClient', 'YFObservation', 'CryptoYFObs']

CRYPTO_YF_TICKERS: list[str] = ["BTC-USD", "QQQ", "GLD"]

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "BTC-USD": 730,
    "QQQ": 730,
    "GLD": 730,
}

CryptoYFObs = YFObservation  # name the crypto pipeline and tests use


class CryptoYFinanceClient(YFinanceClient):
    TICKERS = CRYPTO_YF_TICKERS
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 730
