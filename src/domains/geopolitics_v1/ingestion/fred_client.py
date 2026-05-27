"""
FREDClient — geopolitics-v1 FRED series fetcher.

Series fetched
--------------
DCOILWTICO  WTI Crude Oil Price (daily, USD/bbl)
            Used for: TradeDisruptionRisk, SupplyChainStress, EnergyWeaponizationRisk

PPIACO      Producer Price Index, All Commodities (monthly)
            Used for: SupplyChainStress (composite)

DTWEXBGS    Trade Weighted U.S. Dollar Index: Broad, Goods (weekly)
            Used for: CurrencyWarSignal (volatility)

INDPRO      Industrial Production Index (monthly)
            Used for: GlobalTradeVolumeWeak (inverted 3m change)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

FRED_SERIES: dict[str, str] = {
    "wti":       "DCOILWTICO",
    "ppi":       "PPIACO",
    "broad_usd": "DTWEXBGS",
    "indpro":    "INDPRO",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "DCOILWTICO": 400,
    "PPIACO":     400,
    "DTWEXBGS":   400,
    "INDPRO":     400,
}


@dataclass(frozen=True)
class FREDObservation:
    """A single FRED observation (date, value) pair."""
    obs_date: date
    value: float
    series_id: str


class FREDClient:
    """Asynchronous FRED client for geopolitics-v1 series."""

    def __init__(
        self,
        api_key: str,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY is required but not set")
        self._api_key = api_key
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "FREDClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def fetch_series(
        self,
        series_id: str,
        end_date: Optional[date] = None,
        start_date: Optional[date] = None,
        limit: int = 500,
    ) -> list[FREDObservation]:
        from datetime import datetime, timezone
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        if start_date is None:
            lookback = FETCH_LOOKBACK_DAYS.get(series_id, 400)
            start_date = end_date - timedelta(days=lookback)

        params: dict = {
            "series_id":         series_id,
            "api_key":           self._api_key,
            "file_type":         "json",
            "sort_order":        "desc",
            "limit":             limit,
            "observation_start": start_date.isoformat(),
            "observation_end":   end_date.isoformat(),
        }

        try:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise IOError(
                f"FRED API HTTP {exc.response.status_code} for {series_id}"
            ) from exc
        except Exception as exc:
            raise IOError(
                f"FRED API request failed for {series_id}: {exc}"
            ) from exc

        raw_observations: list[dict] = body.get("observations", [])
        if not raw_observations:
            raise IOError(
                f"FRED returned empty observations for {series_id} "
                f"({start_date} to {end_date})"
            )

        result: list[FREDObservation] = []
        for obs in raw_observations:
            raw_value = obs.get("value", ".")
            if raw_value == "." or raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (ValueError, TypeError):
                continue
            try:
                obs_date = date.fromisoformat(str(obs.get("date", ""))[:10])
            except ValueError:
                continue
            result.append(FREDObservation(obs_date=obs_date, value=value, series_id=series_id))

        if not result:
            raise IOError(
                f"FRED returned no valid observations for {series_id}"
            )

        result.sort(key=lambda o: o.obs_date, reverse=True)
        logger.debug(
            "FRED %s: %d obs (newest: %s)", series_id, len(result), result[0].obs_date
        )
        return result

    async def fetch_all_series(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[FREDObservation]]:
        import asyncio
        from datetime import datetime, timezone
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        series_ids = list(FRED_SERIES.values())

        async def _safe_fetch(sid: str) -> tuple[str, list[FREDObservation]]:
            try:
                obs = await self.fetch_series(sid, end_date=end_date)
                return sid, obs
            except IOError as exc:
                logger.warning("FRED fetch failed for %s: %s", sid, exc)
                return sid, []

        results = await asyncio.gather(*[_safe_fetch(sid) for sid in series_ids])
        return dict(results)
