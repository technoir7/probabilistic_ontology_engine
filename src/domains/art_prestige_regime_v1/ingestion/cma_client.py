"""
Cleveland Museum of Art open-access API: distinct artists acquired in each
year. Free, no key, CC0.

The API cannot filter by acquisition, so every work is read (about 69
pages of 1,000, some 13 minutes) and dated by its accession number, which
begins with the year accessioned. Only December records ask, and the
answer is kept for the process (CMA_ARTISTS), since the server opens a new
source for every month: a rebuild reads the collection once. Python's default User-Agent is refused, so the
client names itself, as the AIC client does.
Any failure returns None (the museum signal then rests on Chicago alone).
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_URL = "https://openaccess-api.clevelandart.org/api/artworks/"
_USER_AGENT = "probabilistic-ontology-engine/0.1 (art_prestige_regime_v1)"
_YEAR = re.compile(r"(\d{4})\.")


class HeldCollection:
    """The last successful read of the collection, for *ttl_s*."""

    def __init__(self, ttl_s: float = 6 * 3600, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl, self._clock = ttl_s, clock
        self._held: tuple[float, dict[int, int]] | None = None

    def get(self) -> dict[int, int] | None:
        if self._held is None or self._clock() - self._held[0] > self._ttl:
            return None
        return self._held[1]

    def put(self, value: dict[int, int]) -> None:
        self._held = (self._clock(), value)


CMA_ARTISTS = HeldCollection()


class CMAClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None, page_size: int = 1000,
                 cache: HeldCollection | None = None, timeout: float = 120.0) -> None:
        self._injected = client is not None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self._page_size = page_size
        self._cache = cache if cache is not None else CMA_ARTISTS

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "CMAClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def artists_by_year(self) -> dict[int, int] | None:
        """Accession year → distinct artists. The whole collection, unless read lately."""
        if (held := self._cache.get()) is not None:
            return held
        got = await self._read_all()
        if got is not None:
            self._cache.put(got)
        return got

    async def _read_all(self) -> dict[int, int] | None:
        artists: dict[int, set] = defaultdict(set)
        skip, total = 0, None
        try:
            while total is None or skip < total:
                resp = await self._client.get(
                    _URL, params={"limit": str(self._page_size), "skip": str(skip), "fields": "accession_number,creators"},
                    headers={"User-Agent": _USER_AGENT})
                resp.raise_for_status()
                body = resp.json()
                total = int(body["info"]["total"])
                for work in body["data"]:
                    if (m := _YEAR.match(work.get("accession_number") or "")):
                        artists[int(m.group(1))].update(c["id"] for c in work.get("creators") or [])
                skip += self._page_size
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            logger.warning("Cleveland acquisitions failed at skip=%d: %s", skip, exc)
            return None
        return {year: len(ids) for year, ids in artists.items()}
