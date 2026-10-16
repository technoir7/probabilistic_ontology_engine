"""
Art Institute of Chicago public API: what the museum acquired in a fiscal year.

POST https://api.artic.edu/api/v1/artworks/search with an Elasticsearch query
and a cardinality aggregation; `fiscal_year` is the year of acquisition
(believed to run July to June 30 of that year; the API does not say). Free,
no key, CC0. Only records the museum has published online are counted, and
recent years keep filling in as cataloguing catches up.
Any failure returns None (the pipeline then records the variable as MISSING).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_USER_AGENT = "probabilistic-ontology-engine/0.1 (art_prestige_regime_v1)"


@dataclass(frozen=True)
class Acquisitions:
    objects: int
    artists: int  # distinct artist_id: one gift of 4,000 prints is one artist, not 4,000 works


class AICClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None, timeout: float = 30.0) -> None:
        self._injected = client is not None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "AICClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def acquisitions(
        self, fiscal_year: int, artwork_types: Sequence[str] | None = None
    ) -> Acquisitions | None:
        """Works acquired in *fiscal_year*, optionally only of these artwork types. One request."""
        filters: list[dict] = [{"term": {"fiscal_year": fiscal_year}}]
        if artwork_types:
            filters.append({"terms": {"artwork_type_title.keyword": list(artwork_types)}})
        body = {
            "query": {"bool": {"filter": filters}},
            "aggs": {"artists": {"cardinality": {"field": "artist_id"}}},
            "limit": 0,
        }
        try:
            resp = await self._client.post(_SEARCH_URL, json=body, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
            return Acquisitions(
                objects=int(data["pagination"]["total"]),
                artists=int(data["aggregations"]["artists"]["value"]),
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            logger.warning("AIC acquisitions for FY%s %s failed: %s", fiscal_year, artwork_types or "", exc)
            return None
