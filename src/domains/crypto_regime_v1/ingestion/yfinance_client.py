"""
CryptoYFinanceClient — yfinance wrapper for crypto regime market data.

Tickers fetched
---------------
BTC-USD  Bitcoin USD price  → RiskAssetCorrelation, DollarDebasementNarrative
QQQ      Nasdaq-100 ETF      → RiskAssetCorrelation
GLD      SPDR Gold ETF       → DollarDebasementNarrative

Lookback: 2 years for stable z-score distributions.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CRYPTO_YF_TICKERS: list[str] = ["BTC-USD", "QQQ", "GLD"]

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "BTC-USD": 730,
    "QQQ": 730,
    "GLD": 730,
}

_DEFAULT_LOOKBACK = 730


@dataclass(frozen=True)
class CryptoYFObs:
    """A single daily close-price observation for crypto domain."""
    obs_date: date
    close_price: float
    ticker: str


class CryptoYFinanceClient:
    """
    Asynchronous yfinance client for crypto regime market variables.

    Parameters
    ----------
    download_fn : callable, optional
        Injected replacement for yfinance.download.  Use in tests to
        avoid network calls.
    """

    def __init__(self, download_fn: Callable[..., Any] | None = None) -> None:
        self._download = download_fn or yf.download

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> "CryptoYFinanceClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[CryptoYFObs]]:
        """
        Fetch daily close prices for all crypto tickers.

        Returns
        -------
        dict[str, list[CryptoYFObs]]
            Mapping ticker → observations, newest-first.
            Missing tickers return an empty list.
        """
        from datetime import datetime, timezone
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        max_lookback = max(FETCH_LOOKBACK_DAYS.values())
        start_date = end_date - timedelta(days=max_lookback)

        try:
            df = await asyncio.to_thread(
                self._run_download,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            logger.error("yfinance crypto multi-ticker download failed: %s", exc)
            return {t: [] for t in CRYPTO_YF_TICKERS}

        if df is None or getattr(df, "empty", False):
            logger.warning("yfinance returned empty DataFrame for crypto tickers")
            return {t: [] for t in CRYPTO_YF_TICKERS}

        result: dict[str, list[CryptoYFObs]] = {}
        for ticker in CRYPTO_YF_TICKERS:
            obs = _extract_ticker_observations(df, ticker, end_date)
            lb = FETCH_LOOKBACK_DAYS.get(ticker, _DEFAULT_LOOKBACK)
            cutoff = end_date - timedelta(days=lb)
            obs = [o for o in obs if o.obs_date >= cutoff]
            result[ticker] = obs
            logger.debug("yfinance crypto %s: %d obs", ticker, len(obs))

        return result

    def _run_download(self, start_date: date, end_date: date) -> Any:
        return self._download(
            tickers=CRYPTO_YF_TICKERS,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )


def _extract_ticker_observations(
    df: Any,
    ticker: str,
    end_date: date,
) -> list[CryptoYFObs]:
    """Extract close prices for a single ticker, handling MultiIndex structure."""
    if not isinstance(df, pd.DataFrame):
        return []

    try:
        close_series = _extract_close_series(df, ticker)
    except (KeyError, ValueError) as exc:
        logger.debug("yfinance: cannot extract Close for %s: %s", ticker, exc)
        return []

    if close_series is None or close_series.empty:
        return []

    observations: list[CryptoYFObs] = []
    for idx, raw_val in close_series.items():
        try:
            obs_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        except (ValueError, AttributeError):
            continue
        if obs_date > end_date:
            continue
        try:
            price = float(raw_val)
        except (TypeError, ValueError):
            continue
        if pd.isna(price) or price <= 0:
            continue
        observations.append(CryptoYFObs(obs_date=obs_date, close_price=price, ticker=ticker))

    observations.sort(key=lambda o: o.obs_date, reverse=True)
    return observations


def _extract_close_series(df: pd.DataFrame, ticker: str) -> "pd.Series":
    """Robust Close extraction from potentially MultiIndex DataFrame."""
    if not isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns:
            return df["Close"]
        raise KeyError(f"No Close column for {ticker}")

    level_names = list(df.columns.names)
    if "Price" in level_names and "Ticker" in level_names:
        try:
            price_level_idx = level_names.index("Price")
            close_df = df.xs("Close", axis=1, level=price_level_idx)
            if ticker in close_df.columns:
                return close_df[ticker]
        except (KeyError, ValueError):
            pass

    if len(level_names) == 2:
        for level in (1, 0):
            try:
                close_df = df.xs("Close", axis=1, level=level)
                if ticker in close_df.columns:
                    return close_df[ticker]
            except (KeyError, ValueError):
                pass

    for level_idx in range(len(level_names)):
        try:
            sub = df.xs(ticker, axis=1, level=level_idx)
            if "Close" in sub.columns:
                return sub["Close"]
        except (KeyError, ValueError):
            continue

    raise KeyError(f"Cannot extract Close series for {ticker}")
