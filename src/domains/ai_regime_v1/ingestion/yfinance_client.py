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

# ---------------------------------------------------------------------------
# Tickers and lookback windows
# ---------------------------------------------------------------------------

AI_TICKERS: list[str] = ["^SOX", "QQQ", "RSP", "^VIX"]

# Number of calendar days to request per ticker (padded for holidays)
FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "^SOX":  800,   # ~3 years for return z-score history
    "QQQ":   800,   # ~3 years for concentration ratio and valuation
    "RSP":   800,   # ~3 years for concentration ratio
    "^VIX":  560,   # ~2 years for VIX rolling mean/std
}

_DEFAULT_LOOKBACK = 800


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class YFObservation:
    """A single daily close-price observation."""
    obs_date: date
    close_price: float
    ticker: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AIYFinanceClient:
    """
    Asynchronous yfinance client for AI regime market variables.

    Parameters
    ----------
    download_fn : callable, optional
        Injected replacement for yfinance.download.  Use in tests to
        avoid network calls.
    """

    def __init__(
        self,
        download_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._download = download_fn or yf.download

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> "AIYFinanceClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[YFObservation]]:
        """
        Fetch daily close prices for all four AI regime tickers.

        Parameters
        ----------
        end_date : date, optional
            Upper bound for fetched data.  Defaults to today.

        Returns
        -------
        dict[str, list[YFObservation]]
            Mapping ticker → observations, newest-first.
            Missing tickers return an empty list (never raises).
        """
        from datetime import datetime, timezone
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        # Use the longest lookback needed for a single download call
        max_lookback = max(FETCH_LOOKBACK_DAYS.values())
        start_date = end_date - timedelta(days=max_lookback)

        try:
            df = await asyncio.to_thread(
                self._run_download,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            logger.error("yfinance multi-ticker download failed: %s", exc)
            return {t: [] for t in AI_TICKERS}

        if df is None or getattr(df, "empty", False):
            logger.warning("yfinance returned empty DataFrame for AI tickers")
            return {t: [] for t in AI_TICKERS}

        result: dict[str, list[YFObservation]] = {}
        for ticker in AI_TICKERS:
            obs = _extract_ticker_observations(df, ticker, end_date)
            # Trim to each ticker's lookback window
            lb = FETCH_LOOKBACK_DAYS.get(ticker, _DEFAULT_LOOKBACK)
            cutoff = end_date - timedelta(days=lb)
            obs = [o for o in obs if o.obs_date >= cutoff]
            result[ticker] = obs
            logger.debug(
                "yfinance %s: %d observations (newest: %s)",
                ticker,
                len(obs),
                obs[0].obs_date if obs else "none",
            )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_download(self, start_date: date, end_date: date) -> Any:
        """Synchronous yfinance download call (runs in thread)."""
        return self._download(
            tickers=AI_TICKERS,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — testable synchronously)
# ---------------------------------------------------------------------------

def _extract_ticker_observations(
    df: Any,
    ticker: str,
    end_date: date,
) -> list[YFObservation]:
    """
    Extract close prices for a single ticker from a yfinance multi-ticker
    DataFrame, handling both MultiIndex and flat column structures.

    Returns observations sorted newest-first, with NaN and zero values
    excluded.
    """
    if not isinstance(df, pd.DataFrame):
        logger.debug("yfinance: df is not a DataFrame (got %s)", type(df))
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
            # idx may be a Timestamp or date-like
            if hasattr(idx, "date"):
                obs_date = idx.date()
            else:
                obs_date = date.fromisoformat(str(idx)[:10])
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

        observations.append(YFObservation(
            obs_date=obs_date,
            close_price=price,
            ticker=ticker,
        ))

    observations.sort(key=lambda o: o.obs_date, reverse=True)
    return observations


def _extract_close_series(df: pd.DataFrame, ticker: str) -> "pd.Series":
    """
    Robust extraction of Close price series for a ticker from a
    potentially MultiIndex DataFrame returned by yfinance multi-ticker
    download.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        # Flat columns — single ticker
        if "Close" in df.columns:
            return df["Close"]
        raise KeyError(f"No Close column for {ticker}")

    # MultiIndex: try (Price, Ticker) structure
    level_names = list(df.columns.names)

    # Common yfinance structure: ('Price', 'Ticker')
    if "Price" in level_names and "Ticker" in level_names:
        try:
            price_level_idx = level_names.index("Price")
            ticker_level_idx = level_names.index("Ticker")
            close_df = df.xs("Close", axis=1, level=price_level_idx)
            if ticker in close_df.columns:
                return close_df[ticker]
        except (KeyError, ValueError):
            pass

    # Try ('Ticker', 'Price') structure
    if len(level_names) == 2:
        try:
            close_df = df.xs("Close", axis=1, level=1)
            if ticker in close_df.columns:
                return close_df[ticker]
        except (KeyError, ValueError):
            pass
        try:
            close_df = df.xs("Close", axis=1, level=0)
            if ticker in close_df.columns:
                return close_df[ticker]
        except (KeyError, ValueError):
            pass

    # Fall back: look for ticker in level values, then Close in remaining
    for level_idx in range(len(level_names)):
        try:
            sub = df.xs(ticker, axis=1, level=level_idx)
            if "Close" in sub.columns:
                return sub["Close"]
        except (KeyError, ValueError):
            continue

    raise KeyError(f"Cannot extract Close series for {ticker} from MultiIndex columns")
