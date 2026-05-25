"""
EIAClient — fetches natural gas data from api.eia.gov (v2 API).

API key must be supplied via the EIA_API_KEY environment variable (or the
.env file loaded by the caller).

Series used
-----------
NG.NW2_EPG0_SWO_R48_BCF.W
    Weekly Lower-48 States Natural Gas Working Underground Storage (Bcf).
    Published every Thursday.  Two consecutive readings are fetched;
    the week-over-week change determines StorageDraw.

NG.RNGWHHD.D
    Henry Hub Natural Gas Spot Price ($/MMBtu, daily business days).
    28 daily readings are fetched; the most recent price is compared to
    the 28-day rolling median to determine PriceUp.

Endpoint
--------
GET https://api.eia.gov/v2/seriesid/{series_id}
    ?api_key={key}
    &length={n}
    &offset=0
Data is returned newest-first.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.eia.gov/v2/seriesid"
_STORAGE_SERIES = "NG.NW2_EPG0_SWO_R48_BCF.W"
_PRICE_SERIES   = "NG.RNGWHHD.D"

_PRICE_WINDOW   = 28   # rolling days for median baseline
_STORAGE_FETCH  = 3    # need 2 consecutive weeks; fetch 3 for safety


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class NatGasSnapshot:
    storage_current_bcf: float   # latest week's storage level
    storage_prev_bcf: float      # preceding week's storage level
    storage_change_bcf: float    # current - previous (negative = draw)
    storage_draw: bool           # True if storage decreased
    latest_price: float          # most recent Henry Hub price ($/MMBtu)
    median_price: float          # 28-day rolling median
    price_up: bool               # True if latest > median


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class EIAClient:
    """
    Asynchronous client for api.eia.gov natural gas series.

    Parameters
    ----------
    api_key : str
        EIA open-data API key.  Obtain free at https://www.eia.gov/opendata/
    client : httpx.AsyncClient, optional
        Injected HTTP client.  If provided, the caller owns it and it is not
        closed on exit.  Pass an AsyncMock here in tests.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("EIA_API_KEY is required but not set")
        self._api_key = api_key
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "EIAClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_snapshot(self) -> NatGasSnapshot:
        """
        Fetch the latest storage and price data and return a NatGasSnapshot.
        Both series are fetched concurrently.
        """
        import asyncio
        storage_data, price_data = await asyncio.gather(
            self._fetch_series(_STORAGE_SERIES, length=_STORAGE_FETCH),
            self._fetch_series(_PRICE_SERIES,   length=_PRICE_WINDOW),
        )

        # ---- storage ----
        if len(storage_data) < 2:
            raise IOError(
                f"Expected ≥2 storage records, got {len(storage_data)}. "
                "EIA API may be unavailable or the series is delayed."
            )
        current_bcf = float(storage_data[0]["value"])
        prev_bcf    = float(storage_data[1]["value"])
        change_bcf  = current_bcf - prev_bcf

        # ---- price ----
        if not price_data:
            raise IOError("No price records returned by EIA API")

        prices = [float(r["value"]) for r in price_data if r.get("value") is not None]
        if not prices:
            raise IOError("All returned price records have null values")

        latest_price = prices[0]
        median_price = statistics.median(prices)

        return NatGasSnapshot(
            storage_current_bcf=current_bcf,
            storage_prev_bcf=prev_bcf,
            storage_change_bcf=change_bcf,
            storage_draw=change_bcf < 0.0,
            latest_price=latest_price,
            median_price=median_price,
            price_up=latest_price > median_price,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_series(self, series_id: str, length: int) -> list[dict]:
        """
        Fetch `length` most-recent data points for `series_id`.
        Returns a list of record dicts, newest first.
        Raises IOError on HTTP or parsing failure.
        """
        url = f"{_BASE_URL}/{series_id}"
        params = {
            "api_key": self._api_key,
            "length": length,
            "offset": 0,
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise IOError(
                f"EIA API HTTP {exc.response.status_code} for {series_id}"
            ) from exc
        except Exception as exc:
            raise IOError(f"EIA API request failed for {series_id}: {exc}") from exc

        data = body.get("response", {}).get("data", [])
        if not data:
            raise IOError(f"EIA returned empty data array for {series_id}")
        return data
