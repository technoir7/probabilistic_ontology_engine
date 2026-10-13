"""
Art Institute of Chicago public API: how many works the museum acquired in a
fiscal year, optionally only those matching some terms.

POST https://api.artic.edu/api/v1/artworks/search with an Elasticsearch query;
`fiscal_year` is the year of acquisition (AIC's fiscal year ends June 30).
Free, no key. Counts for recent years keep rising for a while as cataloguing
catches up, so callers compare shares of a year's acquisitions, not counts.
Any failure returns None (the pipeline then records the variable as MISSING).
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_USER_AGENT = "probabilistic-ontology-engine/0.1 (art_prestige_regime_v1)"


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

    async def acquisitions(self, fiscal_year: int, any_of: Mapping[str, Sequence[str]] | None = None) -> int | None:
        """
        Works acquired in *fiscal_year*; with *any_of* ({field: [terms]}), only
        those matching at least one term in any of the fields. One request.
        """
        must: list[dict] = [{"term": {"fiscal_year": fiscal_year}}]
        if any_of:
            must.append({"bool": {"should": [{"terms": {field: list(terms)}} for field, terms in any_of.items()],
                                  "minimum_should_match": 1}})
        try:
            resp = await self._client.post(
                _SEARCH_URL,
                json={"query": {"bool": {"must": must}}, "limit": 0},
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            return int(resp.json()["pagination"]["total"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            logger.warning("AIC acquisitions for FY%s %s failed: %s", fiscal_year, any_of, exc)
            return None
