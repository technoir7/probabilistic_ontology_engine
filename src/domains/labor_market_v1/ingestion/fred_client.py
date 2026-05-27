"""
FREDClient — labor-market-v1 FRED series fetcher.

Series fetched
--------------
UNRATE          Unemployment Rate (monthly, seasonally adjusted, %)
                Used for: UnemploymentRising (z-score), TightLaborMarket (composite)

CES0500000003   Average Hourly Earnings of All Employees: Total Private (monthly, $/hr)
                Used for: WageInflationPersistent (YoY z-score), RealWageGrowthPositive

JTSJOL          Job Openings: Total Nonfarm (monthly, thousands)
                Used for: JobOpeningsFalling (inverted z-score), TightLaborMarket

ICSA            Initial Claims (weekly, thousands)
                Used for: LayoffCycleBeginning (z-score)

PRS85006092     Nonfarm Business Sector: Real Output Per Hour of All Persons (quarterly, index)
                Used for: LaborProductivityWeak (YoY change)

CIVPART         Labor Force Participation Rate (monthly, seasonally adjusted, %)
                Used for: ParticipationRateFalling (inverted z-score)

CPIAUCSL        CPI All Urban Consumers (monthly, seasonally adjusted)
                Used for: RealWageGrowthPositive (nominal wage - CPI)
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
    "unrate":       "UNRATE",
    "wages":        "CES0500000003",
    "job_openings": "JTSJOL",
    "initial_claims": "ICSA",
    "productivity": "PRS85006092",
    "participation": "CIVPART",
    "cpi":          "CPIAUCSL",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "UNRATE":        450,   # 15 months for trend + z-score
    "CES0500000003": 430,   # 14 months for 12m YoY
    "JTSJOL":        430,   # 14 months for z-score
    "ICSA":          400,   # 52+ weeks for z-score
    "PRS85006092":   1500,  # ~4 years quarterly for YoY trend
    "CIVPART":       430,   # 14 months for z-score
    "CPIAUCSL":      430,   # 14 months for real wage computation
}


@dataclass(frozen=True)
class FREDObservation:
    obs_date: date
    value: float
    series_id: str


class FREDClient:
    """Asynchronous FRED client for labor-market-v1 series."""

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
            raise IOError(f"FRED API HTTP {exc.response.status_code} for {series_id}") from exc
        except Exception as exc:
            raise IOError(f"FRED API request failed for {series_id}: {exc}") from exc

        raw_observations: list[dict] = body.get("observations", [])
        if not raw_observations:
            raise IOError(f"FRED returned empty observations for {series_id}")

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
