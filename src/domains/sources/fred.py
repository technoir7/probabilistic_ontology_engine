"""
FRED (St. Louis Fed) series client, shared by every domain that reads FRED.

A domain subclasses FREDClient only to say which series it reads: SERIES
(role → series id), LOOKBACK_DAYS (series id → window) and
DEFAULT_LOOKBACK_DAYS. Request, parsing, ordering and failure handling live
here once; before, eight copies drifted in wording and logging.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import ClassVar, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass(frozen=True)
class FREDObservation:
    """A single FRED observation (date, value) pair."""
    obs_date: date
    value: float
    series_id: str


class FredHTTPError(IOError):
    """FRED answered with an HTTP error. Keeps the status and Retry-After for callers that retry."""

    def __init__(self, series_id: str, status: int, retry_after: Optional[str]) -> None:
        super().__init__(f"FRED API HTTP {status} for {series_id}")
        self.series_id = series_id
        self.status = status
        self.retry_after = retry_after


class FREDClient:
    SERIES: ClassVar[Mapping[str, str]] = {}
    LOOKBACK_DAYS: ClassVar[Mapping[str, int]] = {}
    DEFAULT_LOOKBACK_DAYS: ClassVar[int] = 400

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
        """
        Observations for one series, newest first, missing values skipped.
        One HTTP request. Raises FredHTTPError on an HTTP error and IOError
        when the request fails or returns no usable observations.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        if start_date is None:
            lookback = self.LOOKBACK_DAYS.get(series_id, self.DEFAULT_LOOKBACK_DAYS)
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
            raise FredHTTPError(
                series_id, exc.response.status_code, exc.response.headers.get("Retry-After")
            ) from exc
        except Exception as exc:
            raise IOError(f"FRED API request failed for {series_id}: {exc}") from exc

        raw_observations: list[dict] = body.get("observations", [])
        if not raw_observations:
            raise IOError(f"FRED returned empty observations for {series_id} ({start_date} to {end_date})")

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
            raise IOError(f"FRED returned no valid observations for {series_id}")

        result.sort(key=lambda o: o.obs_date, reverse=True)
        logger.debug("FRED %s: %d obs (newest: %s)", series_id, len(result), result[0].obs_date)
        return result

    async def fetch_all_series(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[FREDObservation]]:
        """
        Every series in SERIES, concurrently (one request each). A series that
        fails is logged and comes back as [] so the others still count.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        async def _safe_fetch(sid: str) -> tuple[str, list[FREDObservation]]:
            try:
                return sid, await self.fetch_series(sid, end_date=end_date)
            except IOError as exc:
                logger.warning("FRED fetch failed for %s: %s", sid, exc)
                return sid, []

        results = await asyncio.gather(*[_safe_fetch(sid) for sid in self.SERIES.values()])
        return dict(results)
