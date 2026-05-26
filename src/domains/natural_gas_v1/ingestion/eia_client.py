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
from datetime import date, datetime, timezone

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

    async def fetch_snapshot(self, target_date: date | None = None) -> NatGasSnapshot:
        """
        Fetch storage and price data and return a NatGasSnapshot.

        When ``target_date`` is provided and is before today, the snapshot is
        computed from the most recent available EIA rows at or before that
        date.  When omitted, or when ``target_date`` is today/current, the
        current latest-value behavior is preserved.
        """
        import asyncio
        today = datetime.now(timezone.utc).date()
        historical_end = target_date if target_date is not None and target_date < today else None
        storage_data, price_data = await asyncio.gather(
            self._fetch_series(
                _STORAGE_SERIES,
                length=_STORAGE_FETCH,
                end_date=historical_end,
            ),
            self._fetch_series(
                _PRICE_SERIES,
                length=_PRICE_WINDOW,
                end_date=historical_end,
            ),
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

    async def _fetch_series(
        self,
        series_id: str,
        length: int,
        end_date: date | None = None,
    ) -> list[dict]:
        """
        Fetch `length` data points for `series_id`, optionally ending at
        `end_date`.

        Returns a list of record dicts, newest first.
        Raises IOError on HTTP or parsing failure.
        """
        url = f"{_BASE_URL}/{series_id}"
        params = {
            "api_key": self._api_key,
            "length": length,
            "offset": 0,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        }
        if end_date is not None:
            params["end"] = end_date.isoformat()
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
        filtered = _rows_at_or_before(data, end_date)
        if not filtered:
            detail = f" at or before {end_date}" if end_date is not None else ""
            raise IOError(f"EIA returned no usable data for {series_id}{detail}")
        return filtered[:length]


def _rows_at_or_before(rows: list[dict], end_date: date | None) -> list[dict]:
    dated_rows: list[tuple[date, dict]] = []
    undated_rows: list[dict] = []
    for row in rows:
        row_date = _row_period_date(row)
        if row_date is None:
            undated_rows.append(row)
            continue
        if end_date is None or row_date <= end_date:
            dated_rows.append((row_date, row))

    if dated_rows:
        return [row for _, row in sorted(dated_rows, key=lambda item: item[0], reverse=True)]
    return undated_rows


def _row_period_date(row: dict) -> date | None:
    raw = row.get("period") or row.get("date")
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
