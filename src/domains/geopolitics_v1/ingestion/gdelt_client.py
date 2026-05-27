"""
GDELTClient — geopolitics-v1 GDELT V2 API fetcher.

GDELT V2 Timeline API
---------------------
Base URL: https://api.gdeltproject.org/api/v2/doc/doc
Mode: timelinevol (daily article volume as % of all coverage)

CRITICAL: GDELT is very unreliable. Every fetch is wrapped in try/except.
On any failure, returns empty list []. The pipeline handles empty lists
by falling back to p=0.5.

Queries
-------
conflict      "conflict war"
sanctions     "sanctions"
diplomatic    "diplomatic tension"
energy_sanction "energy sanctions"
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

GDELT_QUERIES: dict[str, str] = {
    "conflict": "conflict war",
    "sanctions": "sanctions",
    "diplomatic": "diplomatic tension",
    "energy_sanction": "energy sanctions",
}


@dataclass(frozen=True)
class GDELTObs:
    """A single GDELT timeline observation."""
    obs_date: date
    value: float    # article share percentage (typically 0-10 scale)
    query_label: str


class GDELTClient:
    """
    Asynchronous GDELT V2 client for geopolitics-v1.

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

    async def __aenter__(self) -> "GDELTClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def fetch_timeline(
        self,
        query: str,
        label: str,
        lookback_days: int = 90,
        end_date: Optional[date] = None,
    ) -> list[GDELTObs]:
        """
        Fetch GDELT timeline volume for a query.

        CRITICAL: Returns empty list on any failure.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        start_str = start_date.strftime("%Y%m%d") + "000000"
        end_str = end_date.strftime("%Y%m%d") + "235959"

        params = {
            "query": query,
            "mode": "timelinevol",
            "format": "json",
            "startdatetime": start_str,
            "enddatetime": end_str,
        }

        try:
            resp = await self._client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("GDELT fetch_timeline(%s) failed: %s", label, exc)
            return []

        try:
            timeline = body.get("timeline", [])
            if not timeline:
                logger.debug("GDELT: empty timeline for query '%s'", query)
                return []

            series = timeline[0].get("series", [])
            result: list[GDELTObs] = []
            for entry in series:
                try:
                    date_str = str(entry.get("date", ""))[:8]
                    obs_date = date(
                        int(date_str[:4]),
                        int(date_str[4:6]),
                        int(date_str[6:8]),
                    )
                    value = float(entry.get("value", 0.0))
                    result.append(GDELTObs(obs_date=obs_date, value=value, query_label=label))
                except Exception:
                    continue

            result.sort(key=lambda o: o.obs_date, reverse=True)
            logger.debug("GDELT %s: %d obs", label, len(result))
            return result

        except Exception as exc:
            logger.warning("GDELT parse error for '%s': %s", label, exc)
            return []

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[GDELTObs]]:
        """
        Fetch all 4 GDELT query timelines concurrently.

        Each query is wrapped in try/except — failure of one does not
        affect the others. Returns empty list for any failed query.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        tasks = {
            label: asyncio.create_task(
                self.fetch_timeline(query=query, label=label, end_date=end_date)
            )
            for label, query in GDELT_QUERIES.items()
        }

        results: dict[str, list[GDELTObs]] = {}
        for label, task in tasks.items():
            try:
                results[label] = await task
            except Exception as exc:
                logger.warning("GDELT task failed for '%s': %s", label, exc)
                results[label] = []

        return results
