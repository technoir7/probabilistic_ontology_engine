"""
Fetch → store → learn, once. Every entry point (scheduler, startup backfill,
manual trigger, manual backfill) goes through ingest_and_learn and backfill,
so dedup, skipping and failure handling are defined in one place.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Iterable

from ..engine import ProbabilisticOntologyEngine
from ..model.errors import EvidenceUnavailable
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
    # By date and source, not evidence_id: natural-gas still issues a fresh
    # uuid4 per fetch, and records stored before ids became deterministic
    # have random ones. Re-running a day must not store and learn it twice.
    if engine.has_evidence_at(record.timestamp, record.source_ref, domain_id):
        logger.info("Skipping %s: evidence for %s already stored", domain_id, record.timestamp.date())
        return 0
    if skip_unchanged_state and _same_state_as_latest(engine, domain_id, record):
        logger.info("Skipping duplicate %s state for %s", domain_id, target)
        return 0
    with engine.db.transaction():
        engine.ingest(record)
        engine.learn([record], domain_id)
    return 1


def learn_new_records(engine: ProbabilisticOntologyEngine, domain_id: str, records: Iterable[EvidenceRecord]) -> int:
    """
    Store and learn each record not already stored (by evidence_id), oldest
    first, one transaction per record as ingest_and_learn does. For evidence
    that is supplied rather than fetched (art reports). Returns how many were new.
    The caller holds the domain's lock.
    """
    learned = 0
    for record in sorted(records, key=lambda r: r.timestamp):
        if engine.has_evidence(record.evidence_id):
            continue
        with engine.db.transaction():
            engine.ingest(record)
            engine.learn([record], domain_id)
        learned += 1
    return learned


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


# Unchanged-state check: was the latest stored record the same observations?
# Compares parsed records, not stored JSON, so it does not depend on how the
# store encodes probabilities (that encoding changed in REFACTOR_SPEC 3.4).

def _state_signature(record: EvidenceRecord) -> tuple[Any, ...]:
    """Observations only: ignores record id, source and timestamp."""
    return tuple(
        (
            str(a.variable_id),
            a.observed_value,
            a.missingness.value,
            tuple(sorted(a.probabilities.items(), key=lambda kv: str(kv[0]))) if a.probabilities else None,
        )
        for a in record.observed_assignments
    )


def _same_state_as_latest(engine: ProbabilisticOntologyEngine, domain_id: str, record: EvidenceRecord) -> bool:
    latest = engine.evidence_store.load_latest(domain_id, 1)
    return bool(latest) and _state_signature(latest[0]) == _state_signature(record)


@dataclass(frozen=True)
class RebuildResult:
    learned: int
    missed: list[date]  # targets with no record: no data to give, or still failing after a retry


async def rebuild(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    fetch: Fetch,
    targets: Iterable[date],
    supplied: Iterable[EvidenceRecord],
    *,
    pause_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> RebuildResult:
    """
    Forget the domain and relearn it from scratch: fetch every target, add the
    supplied records, and learn them all oldest first. Order matters, since
    scores weight recent evidence (REFACTOR_SPEC D14), so fetched and supplied
    records are merged before learning rather than learned source by source.

    Everything is fetched before the reset, so the domain keeps its state
    until there is something to replace it with. A target whose fetch fails
    is tried once more after the rest, since upstream errors are often
    momentary; one that is EvidenceUnavailable is not. Targets still without
    a record are returned as missed. The caller holds the lock.
    """
    fetched: list[EvidenceRecord] = []
    unavailable: list[date] = []
    failed: list[date] = []

    async def attempt(target: date) -> bool:
        try:
            fetched.append(await fetch(target))
            return True
        except EvidenceUnavailable as exc:
            logger.warning("%s rebuild: no evidence for %s: %s", domain_id, target, exc)
            unavailable.append(target)
            return True
        except Exception as exc:  # noqa: BLE001 — one bad period must not stop a rebuild
            logger.error("%s rebuild: fetch failed for %s: %s", domain_id, target, exc, exc_info=True)
            return False
        finally:
            await sleep(pause_s)

    for target in targets:
        if not await attempt(target):
            failed.append(target)
    still_failed = [t for t in failed if not await attempt(t)]

    supplied = list(supplied)
    if not fetched and not supplied:
        # Nothing to replace it with: keep what the domain has.
        raise RuntimeError(f"{domain_id} rebuild: nothing fetched, domain kept as it was")
    engine.reset_domain(domain_id)
    learned = learn_new_records(engine, domain_id, [*fetched, *supplied])
    return RebuildResult(learned=learned, missed=sorted([*unavailable, *still_failed]))
