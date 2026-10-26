"""
The New York Times Archive API: every article of a month with its subject
keywords. An art article is one with the subject "Art"; its other subjects
are its tags. The subject field's name and the tags' capitals vary across
eras, so both are compared in lower case. Free for non-commercial use with
a developer key, at most 5 calls a minute and 500 a day; one call a month,
but each is large (every article of the month).

A month that cannot be read returns None, and its signals are MISSING.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

import httpx

from ...sources.rate_limit import RateLimiter
from .tag_counts import PRESS_MONTHS, MonthCache, TagCounts

logger = logging.getLogger(__name__)

_URL = "https://api.nytimes.com/svc/archive/v1/{year}/{month}.json"
ART = "art"
NYT_RATE_LIMIT = RateLimiter(12.0)


class NYTClient:
    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None,
                 rate_limit: RateLimiter | None = None, backoff_s: tuple[float, ...] = (60.0, 120.0, 300.0),
                 cache: MonthCache | None = None, timeout: float = 180.0) -> None:
        self._key = api_key
        self._injected = client is not None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        # Looked up here, not bound as defaults, so tests can replace the shared ones.
        self._rate_limit = rate_limit or NYT_RATE_LIMIT
        self._backoff_s = backoff_s
        self._cache = cache if cache is not None else PRESS_MONTHS

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "NYTClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def month(self, year: int, month: int) -> TagCounts | None:
        """The month's counts, from PRESS_MONTHS if read lately."""
        key = ("nyt", year, month)
        if (cached := self._cache.get(key)) is not None:
            return cached
        counts = await self._read(year, month)
        if counts is not None:
            self._cache.put(key, counts)
        return counts

    async def _read(self, year: int, month: int) -> TagCounts | None:
        """The month's art articles and their other subjects. One (large) request."""
        body = await self._get(_URL.format(year=year, month=month), f"{year}-{month:02d}")
        if body is None:
            return None
        tags: Counter[str] = Counter()
        articles = 0
        try:
            for doc in body["response"]["docs"]:
                subjects = {k["value"].strip().lower() for k in doc.get("keywords") or []
                            if (k.get("name") or "").lower() == "subject"}
                if ART in subjects:
                    articles += 1
                    tags.update(subjects - {ART})
        except (KeyError, TypeError, AttributeError) as exc:
            logger.warning("NYT %d-%02d: unexpected response: %s", year, month, exc)
            return None
        return TagCounts(articles=articles, tags=dict(tags))

    async def _get(self, url: str, label: str) -> dict | None:
        for backoff in (*self._backoff_s, None):
            await self._rate_limit.wait()
            try:
                resp = await self._client.get(url, params={"api-key": self._key})
            except httpx.HTTPError as exc:
                reason = f"dropped ({type(exc).__name__})"   # the message would carry the key in the URL
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code not in (429, 500, 502, 503, 504):
                    logger.warning("NYT %s: HTTP %d", label, resp.status_code)
                    return None
                reason = f"HTTP {resp.status_code}"
            if backoff is None:
                logger.warning("NYT %s: gave up, %s", label, reason)
                return None
            logger.info("NYT %s: %s; retrying in %.0f s", label, reason, backoff)
            self._rate_limit.defer(backoff)
        return None
