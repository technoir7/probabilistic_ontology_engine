"""
NASDAQClient — fetches ZC (corn) front-month futures prices via yfinance.

The class name and snapshot shape are retained for compatibility with the
existing corn ingestion pipeline.

Market data
-----------
    ticker   : ZC=F  — CBOT corn front-month futures
    source   : Yahoo Finance via yfinance
    interval : daily

Derived variable
----------------
    CornPriceUp = latest_close_cents_per_bushel > rolling_20d_avg_cents

    where rolling_20d_avg_cents is the simple average of up to the 20 most
    recent daily close prices preceding the latest reading.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_TICKER = "ZC=F"
_PRICE_ROWS = 21   # 1 latest + up to 20 for rolling average


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CornNASDAQSnapshot:
    target_date: date
    settle_cents_per_bushel: float   # latest ZC front-month close price
    rolling_20d_avg_cents: float     # 20-day simple moving average
    price_up: bool                   # True if latest close > 20d avg


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NASDAQClient:
    """
    Asynchronous wrapper around yfinance.download for ZC=F.

    Parameters
    ----------
    download_fn : callable, optional
        Injected replacement for yfinance.download.  Tests can use this to
        avoid network calls.
    """

    def __init__(
        self,
        download_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._download = download_fn or yf.download

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> "NASDAQClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_snapshot(self, target_date: date) -> CornNASDAQSnapshot:
        """
        Fetch one month of daily ZC=F prices and return a CornNASDAQSnapshot.

        Raises IOError if yfinance returns no usable close prices.
        """
        history = await self._fetch_price_history()
        return self.build_snapshot(target_date, history)

    # ------------------------------------------------------------------
    # Pure snapshot builder (no I/O — testable synchronously)
    # ------------------------------------------------------------------

    @staticmethod
    def build_snapshot(target_date: date, history: Any) -> CornNASDAQSnapshot:
        """
        Map yfinance daily price history to a CornNASDAQSnapshot.

        Raises IOError if fewer than 2 close prices are present.
        """
        prices = _extract_close_prices(history)
        if len(prices) < 2:
            raise IOError(
                f"yfinance {_TICKER} returned {len(prices)} close price(s); "
                "need at least 2 to compute the rolling average."
            )

        window = prices[-_PRICE_ROWS:]
        latest = window[-1]
        prior = window[:-1]
        avg = sum(prior) / len(prior)

        return CornNASDAQSnapshot(
            target_date=target_date,
            settle_cents_per_bushel=latest,
            rolling_20d_avg_cents=avg,
            price_up=latest > avg,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_price_history(self) -> Any:
        """
        Fetch daily ZC=F price history.
        Returns the yfinance DataFrame.
        """
        try:
            history = await asyncio.to_thread(self._download_history)
        except Exception as exc:
            raise IOError(f"yfinance request failed for {_TICKER}: {exc}") from exc

        if history is None or getattr(history, "empty", False):
            raise IOError(f"yfinance returned empty price history for {_TICKER}")
        return history

    def _download_history(self) -> Any:
        try:
            return self._download(
                ticker=_TICKER,
                period="1mo",
                interval="1d",
            )
        except TypeError as exc:
            if "ticker" not in str(exc):
                raise
            return self._download(
                tickers=_TICKER,
                period="1mo",
                interval="1d",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_close_prices(history: Any) -> list[float]:
    """Extract chronological daily close prices from a yfinance DataFrame."""
    close = _close_series(history)
    prices: list[float] = []
    for raw in close.dropna().tolist():
        try:
            prices.append(float(raw))
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping %s row with bad close value: %s", _TICKER, exc)
    return prices


def _close_series(history: Any):
    if not isinstance(history, pd.DataFrame):
        raise IOError(f"yfinance {_TICKER} response is not a DataFrame")

    if isinstance(history.columns, pd.MultiIndex):
        names = list(history.columns.names)
        if "Price" in names:
            close = history.xs("Close", axis=1, level="Price")
        elif "Close" in history.columns.get_level_values(0):
            close = history["Close"]
        elif "Close" in history.columns.get_level_values(-1):
            close = history.xs("Close", axis=1, level=-1)
        else:
            raise IOError(f"yfinance {_TICKER} response has no Close column")

        if isinstance(close, pd.DataFrame):
            if _TICKER in close.columns:
                return close[_TICKER]
            if len(close.columns) == 1:
                return close.iloc[:, 0]
            raise IOError(f"yfinance {_TICKER} Close data is ambiguous")
        return close

    if "Close" not in history.columns:
        raise IOError(f"yfinance {_TICKER} response has no Close column")
    return history["Close"]
