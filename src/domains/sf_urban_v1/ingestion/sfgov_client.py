"""
SFGovClient — sf-urban-v1 SF Open Data (Socrata) monthly counts.

Datasets
--------
Building permits:  https://data.sf.gov/resource/i98e-djp9.json   (filed_date, proposed_use)
Police incidents:  https://data.sf.gov/resource/wg3w-h783.json   (incident_date)
Businesses:        https://data.sf.gov/resource/g8m3-pdis.json   (location_start_date / location_end_date)

The signals only need counts per month, so the server aggregates
(date_trunc_ym + count, grouped by month). Fetching rows instead, capped at
1,000-2,000 and newest first, covered weeks rather than the 13 months the
z-scores need, and in a historical backfill returned only rows newer than the
target date, which were then dropped (REFACTOR_SPEC B13).

Every query is bounded to [end_date - lookback, end_date], so a backfill sees
only what existed on its target date. Any failure returns [] (the pipeline
then records those variables as MISSING).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# data.sfgov.org now answers every request with 301 → data.sf.gov; httpx does
# not follow redirects, so the old host made every SFGov fetch return [].
_BASE_URL = "https://data.sf.gov/resource"

# 13 complete months before the target plus the month in progress.
_DEFAULT_LOOKBACK_DAYS = 430


@dataclass(frozen=True)
class MonthlyCount:
    """Number of records in one calendar month (``month`` is its first day)."""
    month: date
    count: int
    category: str = ""   # permits: proposed_use (e.g. "office"); otherwise ""


class SFGovClient:
    """
    Asynchronous SF Open Data client for sf-urban-v1.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        Injected HTTP client for testing.
    timeout : float
        Request timeout in seconds.
    """

    BASE_URL = _BASE_URL

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "SFGovClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _monthly(
        self,
        dataset: str,
        date_column: str,
        end_date: date,
        lookback_days: int,
        category_column: str | None = None,
    ) -> list[MonthlyCount]:
        """One aggregated query: count per month (and category) in the bounded window."""
        start = end_date - timedelta(days=lookback_days)
        group = "month" + (f", {category_column}" if category_column else "")
        params = {
            "$select": f"date_trunc_ym({date_column}) as month, "
                       + (f"{category_column}, " if category_column else "")
                       + "count(*) as n",
            "$where": f"{date_column} between '{start.isoformat()}T00:00:00' and '{end_date.isoformat()}T23:59:59'",
            "$group": group,
            "$order": "month",
            "$limit": "5000",
        }
        try:
            resp = await self._client.get(f"{self.BASE_URL}/{dataset}.json", params=params)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            logger.warning("SFGov %s monthly counts failed: %s", dataset, exc)
            return []

        result: list[MonthlyCount] = []
        for row in rows:
            try:
                month = date.fromisoformat(str(row["month"])[:10])
                count = int(row["n"])
            except (KeyError, ValueError, TypeError):
                continue
            result.append(MonthlyCount(month=month, count=count, category=str(row.get(category_column, "") or "") if category_column else ""))
        logger.debug("SFGov %s: %d month rows", dataset, len(result))
        return result

    async def fetch_permits(self, end_date: Optional[date] = None, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> list[MonthlyCount]:
        """Permits filed per month and proposed use."""
        end_date = end_date or datetime.now(timezone.utc).date()
        return await self._monthly("i98e-djp9", "filed_date", end_date, lookback_days, "proposed_use")

    async def fetch_incidents(self, end_date: Optional[date] = None, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> list[MonthlyCount]:
        """Police incidents per month."""
        end_date = end_date or datetime.now(timezone.utc).date()
        return await self._monthly("wg3w-h783", "incident_date", end_date, lookback_days)

    async def fetch_business_openings(self, end_date: Optional[date] = None, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> list[MonthlyCount]:
        """Business locations started per month."""
        end_date = end_date or datetime.now(timezone.utc).date()
        return await self._monthly("g8m3-pdis", "location_start_date", end_date, lookback_days)

    async def fetch_business_closures(self, end_date: Optional[date] = None, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> list[MonthlyCount]:
        """Business locations ended per month."""
        end_date = end_date or datetime.now(timezone.utc).date()
        return await self._monthly("g8m3-pdis", "location_end_date", end_date, lookback_days)

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[MonthlyCount]]:
        """All four monthly series concurrently (four requests)."""
        end_date = end_date or datetime.now(timezone.utc).date()
        permits, incidents, openings, closures = await asyncio.gather(
            self.fetch_permits(end_date=end_date),
            self.fetch_incidents(end_date=end_date),
            self.fetch_business_openings(end_date=end_date),
            self.fetch_business_closures(end_date=end_date),
        )
        return {
            "permits": permits,
            "incidents": incidents,
            "business_openings": openings,
            "business_closures": closures,
        }
