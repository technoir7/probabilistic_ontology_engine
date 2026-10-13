"""
Wikimedia pageviews: monthly views of English Wikipedia articles.

https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/monthly/{start}/{end}
Free, no key, monthly back to 2015-07. "user" excludes known bots. Wikimedia
asks for a User-Agent that identifies the caller. Any failure returns []
(the pipeline then records the variable as MISSING).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
_USER_AGENT = "probabilistic-ontology-engine/0.1 (art_prestige_regime_v1; https://github.com/technoir7)"


def _months_back(end: date, months: int) -> date:
    """The first day of the month *months - 1* before *end*'s month."""
    index = end.year * 12 + end.month - 1 - (months - 1)
    return date(index // 12, index % 12 + 1, 1)


class WikipediaClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None, timeout: float = 30.0) -> None:
        self._injected = client is not None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "WikipediaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def monthly_views(self, article: str, *, end: date, months: int) -> list[tuple[date, int]]:
        """(first of month, views) for the *months* months ending with *end*'s, oldest first. One request."""
        start = _months_back(end, months)
        url = (
            f"{_BASE_URL}/{quote(article.replace(' ', '_'), safe='')}/monthly/"
            f"{start:%Y%m%d}/{end:%Y%m%d}"
        )
        try:
            resp = await self._client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            items = resp.json()["items"]
            return [(date(int(i["timestamp"][:4]), int(i["timestamp"][4:6]), 1), int(i["views"])) for i in items]
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            logger.warning("Wikipedia pageviews for %r failed: %s", article, exc)
            return []
