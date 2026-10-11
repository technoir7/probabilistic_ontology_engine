"""
Fetch → store → learn, once. Every entry point (scheduler, startup backfill,
manual trigger, manual backfill) goes through ingest_and_learn and backfill,
so dedup, skipping and failure handling are defined in one place.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Awaitable, Callable, Iterable

from ...domains.agriculture_weekly import is_duplicate_recent_state
from ..engine import ProbabilisticOntologyEngine
from ..schemas import EvidenceRecord

logger = logging.getLogger(__name__)

Fetch = Callable[[date], Awaitable[EvidenceRecord]]


async def ingest_and_learn(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    fetch: Fetch,
    target: date,
    *,
    skip_unchanged_state: bool = False,
) -> int:
    """
    Fetch the evidence for *target*, store it and run one learning cycle.
    Returns 1 if a record was learned, 0 if it was skipped as already stored
    or (with *skip_unchanged_state*) identical to the latest stored state.

    Storing and learning are one transaction: if learning fails the record is
    not kept either, so a retry can learn it instead of skipping it as stored.
    The caller holds the domain's lock.
    """
    record = await fetch(target)
    # evidence_id is a fresh uuid4 per fetch, so the store's evidence_id dedup
    # never fires; re-running a day would store and learn it twice.
    if engine.has_evidence_at(record.timestamp, domain_id):
        logger.info("Skipping %s: evidence for %s already stored", domain_id, record.timestamp.date())
        return 0
    if skip_unchanged_state and is_duplicate_recent_state(
        record, engine.evidence_store.load_recent(domain_id, limit=1)
    ):
        logger.info("Skipping duplicate %s state for %s", domain_id, target)
        return 0
    with engine.db.transaction():
        engine.ingest(record)
        engine.learn([record], domain_id)
    return 1


async def backfill(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    fetch: Fetch,
    targets: Iterable[date],
    *,
    pause_s: float,
    skip_unchanged_state: bool = False,
    abort_on: tuple[type[BaseException], ...] = (),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """
    ingest_and_learn each target in order, pausing between requests to be
    polite to upstream APIs. A failed target is logged and skipped; the rest
    still run, except for *abort_on* errors (e.g. a missing API key, which
    every target would hit), which propagate. Returns how many were learned.
    """
    learned = 0
    for target in targets:
        try:
            learned += await ingest_and_learn(
                engine, domain_id, fetch, target, skip_unchanged_state=skip_unchanged_state
            )
        except abort_on:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad day must not stop a backfill
            logger.error("%s backfill failed for %s: %s", domain_id, target, exc, exc_info=True)
        await sleep(pause_s)
    return learned
