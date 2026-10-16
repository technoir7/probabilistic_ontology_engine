"""
GDELT DOC 2.0 timeline client, shared by every domain that reads GDELT.

https://api.gdeltproject.org/api/v2/doc/doc, mode=timelinevol: daily volume
of matching articles as a share of all monitored coverage, 2017 onward. Free,
no key. A domain says which queries it runs; request, rate limit and parsing
live here once.

GDELT allows one request every 5 seconds per IP and answers faster callers
with HTTP 200 and a plain-text notice. The limit is per IP, so every client
in the process shares GDELT_RATE_LIMIT by default (B17): geopolitics and art
each open their own clients, and each fetch opens new ones.

In practice GDELT throttles harder than its stated rule: live runs from a dev
machine and from Railway (2026-10-16) had most requests answered 429 even at
one per 5 s. A throttled request is retried after THROTTLE_BACKOFF_S, and the
backoff holds every client on the shared limiter, since the penalty is the IP's.

On any other failure, or once the backoffs run out, fetch_timeline returns []
(the pipeline then records the variables that needed it as MISSING).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# About 3.5 minutes at worst per request: fine for schedulers and the
# background rebuild, which are the only callers.
THROTTLE_BACKOFF_S: tuple[float, ...] = (30.0, 60.0, 120.0)


class RateLimiter:
    """At most one call per *interval_s*, across every caller sharing it."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._next_slot: float | None = None

    async def wait(self) -> None:
        # Reserve the slot before awaiting, so concurrent callers queue in turn.
        now = self._clock()
        slot = now if self._next_slot is None else max(now, self._next_slot)
        self._next_slot = slot + self._interval
        if slot > now:
            await self._sleep(slot - now)

    def defer(self, seconds: float) -> None:
        """Hold every caller sharing this limiter for at least *seconds* from now."""
        until = self._clock() + seconds
        self._next_slot = until if self._next_slot is None else max(self._next_slot, until)


GDELT_RATE_LIMIT = RateLimiter(5.0)


@dataclass(frozen=True)
class GDELTObs:
    """A single GDELT timeline observation."""
    obs_date: date
    value: float    # share of all monitored articles, in percent
    query_label: str


class GDELTClient:
    BASE_URL = _BASE_URL

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
        rate_limit: RateLimiter | None = None,
        throttle_backoff_s: Sequence[float] = THROTTLE_BACKOFF_S,
    ) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        # Looked up at construction, not import, so tests can swap the shared one.
        self._rate_limit = rate_limit or GDELT_RATE_LIMIT
        self._backoff_s = tuple(throttle_backoff_s)

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
        """Daily volume for *query* over the window ending *end_date*, newest first. Retries throttled requests."""
        end_date = end_date or datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)
        params = {
            "query": query,
            "mode": "timelinevol",
            "format": "json",
            "startdatetime": start_date.strftime("%Y%m%d") + "000000",
            "enddatetime": end_date.strftime("%Y%m%d") + "235959",
        }
        try:
            resp = await self._get_unthrottled(params, label)
            if resp is None:
                logger.warning("GDELT fetch_timeline(%s) still throttled after %d attempts", label, len(self._backoff_s) + 1)
                return []
            resp.raise_for_status()
            timeline = resp.json().get("timeline") or []
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            logger.warning("GDELT fetch_timeline(%s) failed: %s", label, exc)
            return []
        if not timeline:
            logger.debug("GDELT: empty timeline for query %r", query)
            return []

        # {"series": "<name>", "data": [{"date": "20260930T000000Z", "value": 0.0027}, ...]}
        result: list[GDELTObs] = []
        for point in timeline[0].get("data") or []:
            try:
                raw = str(point["date"])
                result.append(GDELTObs(
                    obs_date=date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])),
                    value=float(point["value"]),
                    query_label=label,
                ))
            except (KeyError, TypeError, ValueError):
                continue
        result.sort(key=lambda o: o.obs_date, reverse=True)
        logger.debug("GDELT %s: %d obs", label, len(result))
        return result

    async def _get_unthrottled(self, params: dict[str, str], label: str) -> httpx.Response | None:
        """The first response that is not a throttle, or None once every backoff is spent."""
        for backoff in (*self._backoff_s, None):
            await self._rate_limit.wait()
            resp = await self._client.get(self.BASE_URL, params=params)
            if not _throttled(resp):
                return resp
            if backoff is None:
                return None
            delay = max(backoff, _retry_after_s(resp))
            logger.info("GDELT throttled %s; retrying in %.0f s", label, delay)
            self._rate_limit.defer(delay)
        return None


def _throttled(resp: httpx.Response) -> bool:
    return resp.status_code == 429 or (resp.status_code == 200 and "limit requests" in resp.text[:200].lower())


def _retry_after_s(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("Retry-After", 0))
    except ValueError:  # an HTTP date: rare, and the backoff covers it
        return 0.0
