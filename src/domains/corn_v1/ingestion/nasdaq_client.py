"""
NASDAQClient — fetches ZC (corn) front-month futures settlement prices via
the Nasdaq Data Link (formerly Quandl) REST API.

API
---
    GET https://data.nasdaq.com/api/v3/datasets/CME/ZC1.json
        ?api_key=<NASDAQ_API_KEY>
        &rows=<N>

    Dataset  : CME/ZC1  — CBOT Corn Futures, Continuous Front Month
    Units    : cents per bushel  (1 USD/bu = 100 cents/bu)
    Frequency: daily business days
    Columns  : Date | Open | High | Low | Settle | Volume | Open Interest

    The API returns newest-first by default.

    API key registration (free tier available):
        https://data.nasdaq.com/sign-up

Environment variable
--------------------
    NASDAQ_API_KEY   — required (load from .env via python-dotenv)

Derived variable
----------------
    CornPriceUp = settle_cents_per_bushel > rolling_20d_avg_cents

    where rolling_20d_avg_cents is the simple average of the 20 most recent
    settlement prices preceding the latest reading.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL      = "https://data.nasdaq.com/api/v3/datasets/CME/ZC1.json"
_PRICE_ROWS    = 21   # 1 latest + 20 for rolling average
_SETTLE_INDEX  = 4    # column index of "Settle" in CME/ZC1 data rows


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CornNASDAQSnapshot:
    target_date: date
    settle_cents_per_bushel: float   # latest ZC front-month settlement price
    rolling_20d_avg_cents: float     # 20-day simple moving average
    price_up: bool                   # True if latest settle > 20d avg


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NASDAQClient:
    """
    Asynchronous client for Nasdaq Data Link (formerly Quandl) CME ZC1.

    Parameters
    ----------
    api_key : str
        Nasdaq Data Link API key.  Obtain free at https://data.nasdaq.com/sign-up
    client : httpx.AsyncClient, optional
        Injected HTTP client.  If provided, the caller owns it (not closed
        on exit).  Pass an AsyncMock here in tests.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("NASDAQ_API_KEY is required but not set")
        self._api_key = api_key
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "NASDAQClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_snapshot(self, target_date: date) -> CornNASDAQSnapshot:
        """
        Fetch the last _PRICE_ROWS days of ZC settlement prices and return
        a CornNASDAQSnapshot.

        Raises IOError if the API cannot return usable data.
        """
        rows = await self._fetch_settle_rows()
        return self.build_snapshot(target_date, rows)

    # ------------------------------------------------------------------
    # Pure snapshot builder (no I/O — testable synchronously)
    # ------------------------------------------------------------------

    @staticmethod
    def build_snapshot(target_date: date, rows: list[list]) -> CornNASDAQSnapshot:
        """
        Map raw Nasdaq Data Link CME/ZC1 data rows to a CornNASDAQSnapshot.
        Static and synchronous so it can be unit-tested without network calls.

        Parameters
        ----------
        rows : list[list]
            Newest-first data rows from the Nasdaq Data Link JSON response.
            Each row has the column layout:
            [Date, Open, High, Low, Settle, Volume, Open Interest]

        Raises IOError if fewer than 2 rows are present.
        """
        if len(rows) < 2:
            raise IOError(
                f"Nasdaq ZC1 returned {len(rows)} row(s); need ≥2 to compute "
                "the 20-day rolling average."
            )

        prices = _extract_settle_prices(rows)
        if not prices:
            raise IOError("No valid settlement prices in Nasdaq ZC1 response")

        latest = prices[0]
        avg    = sum(prices[1:]) / len(prices[1:]) if len(prices) > 1 else latest

        return CornNASDAQSnapshot(
            target_date=target_date,
            settle_cents_per_bushel=latest,
            rolling_20d_avg_cents=avg,
            price_up=latest > avg,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_settle_rows(self) -> list[list]:
        """
        Fetch _PRICE_ROWS most-recent rows from CME/ZC1.
        Returns newest-first list of data arrays.
        Raises IOError on HTTP or parse failure.
        """
        params = {
            "api_key": self._api_key,
            "rows": _PRICE_ROWS,
        }
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise IOError(
                f"Nasdaq API HTTP {exc.response.status_code} for CME/ZC1"
            ) from exc
        except Exception as exc:
            raise IOError(f"Nasdaq API request failed for CME/ZC1: {exc}") from exc

        data = body.get("dataset", {}).get("data", [])
        if not data:
            raise IOError("Nasdaq API returned empty data array for CME/ZC1")
        return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_settle_prices(rows: list[list]) -> list[float]:
    """
    Extract settlement prices from data rows.
    Settle is at column index _SETTLE_INDEX (0-based).
    Skips rows where the value is None or non-numeric.
    """
    out: list[float] = []
    for row in rows:
        try:
            val = row[_SETTLE_INDEX]
            if val is not None:
                out.append(float(val))
        except (IndexError, TypeError, ValueError) as exc:
            logger.warning("Skipping ZC1 row with bad settle value: %s", exc)
    return out
