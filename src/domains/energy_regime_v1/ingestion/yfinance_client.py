"""
EnergyYFinanceClient — yfinance wrapper for energy regime market data.

Tickers fetched
---------------
CL=F   WTI Crude Oil Futures (continuous)  → OilPriceSurge
NG=F   Natural Gas Futures (continuous)     → NatGasPriceSurge
XLE    Energy Select Sector SPDR ETF        → EnergyEquityMomentum, RenewablesDisplacement ratio
ICLN   iShares Global Clean Energy ETF      → RenewablesDisplacement ratio

Lookback periods
----------------
CL=F   2 years (for stable 13-week return z-score distribution)
NG=F   2 years
XLE    2 years
ICLN   2 years

All tickers fetched in a single multi-ticker download call for efficiency.

The client itself is shared (domains/sources/yfinance.py); this module only
names the tickers energy-regime-v1 reads.
"""
from __future__ import annotations

from ...sources.yfinance import YFinanceClient, YFObservation

__all__ = ['FETCH_LOOKBACK_DAYS', 'ENERGY_TICKERS', 'EnergyYFinanceClient', 'YFObservation']

ENERGY_TICKERS: list[str] = ["CL=F", "NG=F", "XLE", "ICLN"]

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "CL=F":  730,
    "NG=F":  730,
    "XLE":   730,
    "ICLN":  730,
}


class EnergyYFinanceClient(YFinanceClient):
    TICKERS = ENERGY_TICKERS
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 730
