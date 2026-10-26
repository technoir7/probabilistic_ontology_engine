"""
The Guardian Open Platform: each month's articles in the `artanddesign`
section and the keyword tags its editors gave them. Free for
non-commercial use with a developer key; up to 200 articles a page, so a
month is one or two requests.

A month that cannot be read returns None, and its signals are MISSING.
"""
from __future__ import annotations

import calendar
import logging
from collections import Counter
from typing import Optional

import httpx

from ...sources.rate_limit import RateLimiter
from .tag_counts import PRESS_MONTHS, MonthCache, TagCounts

logger = logging.getLogger(__name__)

_URL = "https://content.guardianapis.com/search"
# The developer tier allows 1 call a second.
GUARDIAN_RATE_LIMIT = RateLimiter(1.0)


class GuardianClient:
    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None,
                 rate_limit: RateLimiter | None = None, backoff_s: tuple[float, ...] = (30.0, 60.0, 120.0),
                 cache: MonthCache | None = None, timeout: float = 60.0) -> None:
        self._key = api_key
        self._injected = client is not None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        # Looked up here, not bound as defaults, so tests can replace the shared ones.
        self._rate_limit = rate_limit or GUARDIAN_RATE_LIMIT
        self._backoff_s = backoff_s
        self._cache = cache if cache is not None else PRESS_MONTHS

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "GuardianClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def month(self, year: int, month: int) -> TagCounts | None:
        """The month's counts, from PRESS_MONTHS if read lately."""
        key = ("guardian", year, month)
        if (cached := self._cache.get(key)) is not None:
            return cached
        counts = await self._read(year, month)
        if counts is not None:
            self._cache.put(key, counts)
        return counts

    async def _read(self, year: int, month: int) -> TagCounts | None:
        """The art section's articles in one month and their keyword tags. One request a page."""
        last = calendar.monthrange(year, month)[1]
        tags: Counter[str] = Counter()
        articles, page = 0, 1
        while True:
            params = {"section": "artanddesign", "from-date": f"{year}-{month:02d}-01",
                      "to-date": f"{year}-{month:02d}-{last}", "page-size": "200", "page": str(page),
                      "show-tags": "keyword", "api-key": self._key}
            body = await self._get(params, f"{year}-{month:02d} p{page}")
            if body is None:
                return None
            try:
                response = body["response"]
                for result in response["results"]:
                    articles += 1
                    tags.update({t["id"] for t in result.get("tags") or []})
                pages = int(response.get("pages", 1))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Guardian %d-%02d: unexpected response: %s", year, month, exc)
                return None
            if page >= pages:
                return TagCounts(articles=articles, tags=dict(tags))
            page += 1

    async def _get(self, params: dict[str, str], label: str) -> dict | None:
        for backoff in (*self._backoff_s, None):
            await self._rate_limit.wait()
            try:
                resp = await self._client.get(_URL, params=params)
            except httpx.HTTPError as exc:
                reason = f"dropped ({type(exc).__name__})"   # the message would carry the key in the URL
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code not in (429, 500, 502, 503, 504):
                    logger.warning("Guardian %s: HTTP %d", label, resp.status_code)
                    return None
                reason = f"HTTP {resp.status_code}"
            if backoff is None:
                logger.warning("Guardian %s: gave up, %s", label, reason)
                return None
            logger.info("Guardian %s: %s; retrying in %.0f s", label, reason, backoff)
            self._rate_limit.defer(backoff)
        return None
