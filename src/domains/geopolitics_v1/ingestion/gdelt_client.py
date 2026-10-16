"""
geopolitics-v1's GDELT queries; the client is domains/sources/gdelt.py.

Queries
-------
conflict        "conflict war"
sanctions       "sanctions"
diplomatic      "diplomatic tension"
energy_sanction "energy sanctions"
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from ...sources.gdelt import GDELTClient as _GDELTClient
from ...sources.gdelt import GDELTObs

__all__ = ["GDELT_QUERIES", "GDELTClient", "GDELTObs"]

GDELT_QUERIES: dict[str, str] = {
    "conflict": "conflict war",
    "sanctions": "sanctions",
    "diplomatic": "diplomatic tension",
    "energy_sanction": "energy sanctions",
}


class GDELTClient(_GDELTClient):
    async def fetch_all(self, end_date: Optional[date] = None) -> dict[str, list[GDELTObs]]:
        """All four timelines, one at a time (rate limit); a failed one is [] without affecting the others."""
        end_date = end_date or datetime.now(timezone.utc).date()
        return {
            label: await self.fetch_timeline(query=query, label=label, end_date=end_date)
            for label, query in GDELT_QUERIES.items()
        }
