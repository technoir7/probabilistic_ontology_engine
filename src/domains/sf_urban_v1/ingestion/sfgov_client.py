"""
SFGovClient — sf-urban-v1 SF Open Data (Socrata) fetcher.

Datasets used
-------------
Building permits: https://data.sfgov.org/resource/i98e-djp9.json
Police incidents: https://data.sfgov.org/resource/wg3w-h783.json
Business registrations/closures: https://data.sfgov.org/resource/g8m3-pdis.json

CRITICAL: SF Open Data API is unreliable. Every fetch is wrapped in try/except.
On any failure, returns empty list []. The pipeline handles empty lists
by falling back to p=0.5.

No API key required (free public Socrata API).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.sfgov.org/resource"


@dataclass(frozen=True)
class SFPermitObs:
    """A single building permit observation."""
    filed_date: date
    permit_type: str


@dataclass(frozen=True)
class SFIncidentObs:
    """A single police incident observation."""
    incident_date: date
    category: str


@dataclass(frozen=True)
class SFBusinessObs:
    """A single business registration/closure observation."""
    start_date: date
    end_date: Optional[date]  # None if still active


def _parse_date_flexible(s: str) -> Optional[date]:
    """Parse date from ISO string (handles datetime and date-only strings)."""
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


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

    async def fetch_permits(
        self,
        lookback_days: int = 365,
        end_date: Optional[date] = None,
    ) -> list[SFPermitObs]:
        """
        Fetch building permit filings. Returns empty list on failure.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        url = f"{self.BASE_URL}/i98e-djp9.json"
        params = {
            "$select": "filed_date,permit_type",
            "$limit": "1000",
            "$order": "filed_date DESC",
            "$where": f"filed_date IS NOT NULL AND filed_date >= '{start_date.isoformat()}'",
        }

        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            records = resp.json()
        except Exception as exc:
            logger.warning("SFGov fetch_permits failed: %s", exc)
            return []

        result: list[SFPermitObs] = []
        for rec in records:
            try:
                filed_date = _parse_date_flexible(rec.get("filed_date", ""))
                if filed_date is None or filed_date > end_date:
                    continue
                permit_type = str(rec.get("permit_type", ""))
                result.append(SFPermitObs(filed_date=filed_date, permit_type=permit_type))
            except Exception:
                continue

        logger.debug("SFGov permits: %d obs", len(result))
        return result

    async def fetch_incidents(
        self,
        lookback_days: int = 365,
        end_date: Optional[date] = None,
    ) -> list[SFIncidentObs]:
        """
        Fetch police incident reports. Returns empty list on failure.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        url = f"{self.BASE_URL}/wg3w-h783.json"
        params = {
            "$select": "incident_date,incident_category",
            "$limit": "2000",
            "$order": "incident_date DESC",
            "$where": f"incident_date >= '{start_date.isoformat()}'",
        }

        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            records = resp.json()
        except Exception as exc:
            logger.warning("SFGov fetch_incidents failed: %s", exc)
            return []

        result: list[SFIncidentObs] = []
        for rec in records:
            try:
                incident_date = _parse_date_flexible(rec.get("incident_date", ""))
                if incident_date is None or incident_date > end_date:
                    continue
                category = str(rec.get("incident_category", ""))
                result.append(SFIncidentObs(incident_date=incident_date, category=category))
            except Exception:
                continue

        logger.debug("SFGov incidents: %d obs", len(result))
        return result

    async def fetch_businesses(
        self,
        lookback_days: int = 365,
        end_date: Optional[date] = None,
    ) -> list[SFBusinessObs]:
        """
        Fetch business registration/closure data. Returns empty list on failure.
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        url = f"{self.BASE_URL}/g8m3-pdis.json"
        params = {
            "$select": "lic_start_dt,lic_end_dt",
            "$limit": "2000",
            "$order": "lic_start_dt DESC",
            "$where": f"lic_start_dt >= '{start_date.isoformat()}'",
        }

        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            records = resp.json()
        except Exception as exc:
            logger.warning("SFGov fetch_businesses failed: %s", exc)
            return []

        result: list[SFBusinessObs] = []
        for rec in records:
            try:
                start = _parse_date_flexible(rec.get("lic_start_dt", ""))
                if start is None:
                    continue
                end_raw = rec.get("lic_end_dt", "")
                end = _parse_date_flexible(end_raw) if end_raw else None
                result.append(SFBusinessObs(start_date=start, end_date=end))
            except Exception:
                continue

        logger.debug("SFGov businesses: %d obs", len(result))
        return result

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict:
        """
        Fetch all SF Open Data sources concurrently.

        Returns dict with keys:
            "permits": list[SFPermitObs]
            "incidents": list[SFIncidentObs]
            "businesses": list[SFBusinessObs]
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        permits_task = asyncio.create_task(self.fetch_permits(end_date=end_date))
        incidents_task = asyncio.create_task(self.fetch_incidents(end_date=end_date))
        businesses_task = asyncio.create_task(self.fetch_businesses(end_date=end_date))

        permits, incidents, businesses = await asyncio.gather(
            permits_task, incidents_task, businesses_task
        )

        return {
            "permits": permits,
            "incidents": incidents,
            "businesses": businesses,
        }
