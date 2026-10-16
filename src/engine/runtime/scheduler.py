"""
One scheduler loop for every domain: backfill on first start, then ingest on
the domain's cadence. Replaces ten copied per-domain scheduler classes.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Awaitable, Callable

from ..engine import ProbabilisticOntologyEngine
from ..model.cadence import Cadence
from .ingestion import Fetch, backfill, ingest_and_learn

logger = logging.getLogger(__name__)


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
    cadence: Cadence,
    *,
    run_hour_utc: int,
    startup_window_days: int,
    pause_s: float,
    lock: asyncio.Lock,
    skip_unchanged_state: bool = False,
    clock: Callable[[], datetime] = _utcnow,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Backfill if empty, then ingest on *cadence* forever. Runs until cancelled."""
    targets = cadence.window_targets(startup_window_days, clock().date())
    await backfill_if_empty(
        engine, domain_id, fetch, targets,
        pause_s=pause_s, lock=lock, skip_unchanged_state=skip_unchanged_state, sleep=sleep,
    )
    while True:
        now = clock()
        next_run = cadence.next_run(now, run_hour_utc)
        logger.info("Next %s run at %s UTC", domain_id, next_run.strftime("%Y-%m-%d %H:%M"))
        await sleep((next_run - now).total_seconds())
        target = cadence.default_target(clock().date())
        async with lock:
            try:
                await ingest_and_learn(
                    engine, domain_id, fetch, target, skip_unchanged_state=skip_unchanged_state
                )
            except Exception as exc:  # noqa: BLE001 — a failed run must not end the loop
                logger.error("Scheduled %s ingest failed for %s: %s", domain_id, target, exc, exc_info=True)
