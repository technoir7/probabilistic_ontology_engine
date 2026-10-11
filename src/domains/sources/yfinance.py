"""
yfinance daily-close client, shared by the domains that read market prices.

A domain subclasses YFinanceClient only to name its TICKERS, LOOKBACK_DAYS and
DEFAULT_LOOKBACK_DAYS. One multi-ticker download per fetch; parsing copes
with the column layouts yfinance has used. Never raises: a failed or empty
download gives every ticker [] (callers fall back per variable).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, ClassVar, Mapping, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YFObservation:
    """A single daily close-price observation."""
    obs_date: date
    close_price: float
    ticker: str


class YFinanceClient:
    TICKERS: ClassVar[list[str]] = []
    LOOKBACK_DAYS: ClassVar[Mapping[str, int]] = {}
    DEFAULT_LOOKBACK_DAYS: ClassVar[int] = 730

    def __init__(self, download_fn: Callable[..., Any] | None = None) -> None:
        """*download_fn* replaces yfinance.download, e.g. in tests."""
        self._download = download_fn or yf.download

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> "YFinanceClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[YFObservation]]:
        """Ticker → daily closes up to *end_date*, newest first, trimmed to each ticker's lookback."""
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        # One download for the longest window; trimmed per ticker below.
        start_date = end_date - timedelta(days=max(self.LOOKBACK_DAYS.values()))
        try:
            df = await asyncio.to_thread(self._run_download, start_date=start_date, end_date=end_date)
        except Exception as exc:
            logger.error("yfinance download failed for %s: %s", self.TICKERS, exc)
            return {t: [] for t in self.TICKERS}

        if df is None or getattr(df, "empty", False):
            logger.warning("yfinance returned an empty DataFrame for %s", self.TICKERS)
            return {t: [] for t in self.TICKERS}

        result: dict[str, list[YFObservation]] = {}
        for ticker in self.TICKERS:
            cutoff = end_date - timedelta(days=self.LOOKBACK_DAYS.get(ticker, self.DEFAULT_LOOKBACK_DAYS))
            obs = [o for o in _extract_ticker_observations(df, ticker, end_date) if o.obs_date >= cutoff]
            result[ticker] = obs
            logger.debug("yfinance %s: %d obs", ticker, len(obs))
        return result

    def _run_download(self, start_date: date, end_date: date) -> Any:
        return self._download(
            tickers=self.TICKERS,
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
) -> list[YFObservation]:
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

    observations: list[YFObservation] = []
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
        observations.append(YFObservation(obs_date=obs_date, close_price=price, ticker=ticker))

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
