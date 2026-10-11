"""
One scheduler loop for every domain: backfill on first start, then ingest on
the domain's schedule. Replaces ten copied per-domain scheduler classes.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Protocol

from ..engine import ProbabilisticOntologyEngine
from .ingestion import Fetch, backfill, ingest_and_learn

logger = logging.getLogger(__name__)


class Schedule(Protocol):
    pause_s: float

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime: ...
    def target(self, now: datetime) -> date: ...
    def startup_targets(self, today: date, *, days: int, weeks: int) -> list[date]: ...


@dataclass(frozen=True)
class DailySchedule:
    """Every day at the run hour, for yesterday."""

    pause_s: float = 1.0

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime:
        nxt = now.replace(hour=run_hour_utc, minute=0, second=0, microsecond=0)
        return nxt if nxt > now else nxt + timedelta(days=1)

    def target(self, now: datetime) -> date:
        return (now - timedelta(days=1)).date()

    def startup_targets(self, today: date, *, days: int, weeks: int) -> list[date]:
        return [today - timedelta(days=delta) for delta in range(days, 0, -1)]


@dataclass(frozen=True)
class WeeklySchedule:
    """Mondays at the run hour, for the week ending the previous Friday."""

    pause_s: float = 2.0

    def next_run(self, now: datetime, run_hour_utc: int) -> datetime:
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= run_hour_utc:
            days_until_monday = 7
        return (now + timedelta(days=days_until_monday)).replace(
            hour=run_hour_utc, minute=0, second=0, microsecond=0
        )

    def target(self, now: datetime) -> date:
        today = now.date()
        return today - timedelta(days=(today.weekday() - 4) % 7)

    def startup_targets(self, today: date, *, days: int, weeks: int) -> list[date]:
        return sorted(
            today - timedelta(days=delta)
            for delta in range(weeks * 7, 0, -1)
            if (today - timedelta(days=delta)).weekday() == 4
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def backfill_if_empty(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    fetch: Fetch,
    targets: list[date],
    *,
    pause_s: float,
    lock: asyncio.Lock,
    skip_unchanged_state: bool = False,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Backfill *targets* only if the domain has no evidence yet (first start)."""
    async with lock:
        existing = engine.evidence_store.count(domain_id)
        if existing > 0 or not targets:
            logger.info("Skipping %s startup backfill; evidence_count=%d", domain_id, existing)
            return 0
        logger.info("Running %s startup backfill over %d targets", domain_id, len(targets))
        learned = await backfill(
            engine, domain_id, fetch, targets,
            pause_s=pause_s, skip_unchanged_state=skip_unchanged_state, sleep=sleep,
        )
    logger.info("%s startup backfill complete: %d learned", domain_id, learned)
    return learned


async def run_scheduler(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    fetch: Fetch,
    schedule: Schedule,
    *,
    run_hour_utc: int,
    startup_days: int,
    startup_weeks: int,
    lock: asyncio.Lock,
    skip_unchanged_state: bool = False,
    clock: Callable[[], datetime] = _utcnow,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Backfill if empty, then ingest on *schedule* forever. Runs until cancelled."""
    targets = schedule.startup_targets(clock().date(), days=startup_days, weeks=startup_weeks)
    await backfill_if_empty(
        engine, domain_id, fetch, targets,
        pause_s=schedule.pause_s, lock=lock, skip_unchanged_state=skip_unchanged_state, sleep=sleep,
    )
    while True:
        now = clock()
        next_run = schedule.next_run(now, run_hour_utc)
        logger.info("Next %s run at %s UTC", domain_id, next_run.strftime("%Y-%m-%d %H:%M"))
        await sleep((next_run - now).total_seconds())
        target = schedule.target(clock())
        async with lock:
            try:
                await ingest_and_learn(
                    engine, domain_id, fetch, target, skip_unchanged_state=skip_unchanged_state
                )
            except Exception as exc:  # noqa: BLE001 — a failed run must not end the loop
                logger.error("Scheduled %s ingest failed for %s: %s", domain_id, target, exc, exc_info=True)
