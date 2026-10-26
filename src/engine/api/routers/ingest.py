"""Manual ingestion: trigger, backfill, replace and rebuild."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...runtime.ingestion import backfill, learn_new_records, rebuild
from ...runtime.registry import BY_KEY
from ...schemas import EvidenceRecord, MissingnessType, Variable
from .. import context, presenters
from ..auth import require_admin
from ..dto import (
    IngestTriggerOut,
    IngestBackfillOut,
    IngestReplaceOut,
    DomainRebuildOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/v1/ingest/trigger", response_model=IngestTriggerOut)
async def ingest_trigger(request: Request, domain: str = Query("ng")) -> IngestTriggerOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    lock = context.ingest_lock(request.app.state, domain_key)

    async with lock:
        try:
            ingested = await context.ingest_domain_evidence(
                domain_key=domain_key,
                engine=engine,
                domain_id=domain_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "Manual ingestion trigger failed for %s: %s",
                display_name,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Ingestion failed for domain '{domain_key}'",
            ) from exc

    return IngestTriggerOut(
        domain=display_name,
        evidence_records_ingested=ingested,
        population_status=presenters.build_population_status(engine, domain_id, display_name),
    )


@router.post("/v1/ingest/backfill", response_model=IngestBackfillOut, dependencies=[Depends(require_admin)])
async def ingest_backfill(
    request: Request,
    domain: str = Query("ng"),
    # Bounded: each day is one upstream request per data source.
    days: int = Query(90, ge=1, le=1825),
) -> IngestBackfillOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    lock = context.ingest_lock(request.app.state, domain_key)

    targets = BY_KEY[domain_key].cadence.window_targets(days, context.utcnow().date())
    async with lock:
        try:
            successes = await backfill(
                engine,
                domain_id,
                context.fetcher(domain_key),
                targets,
                pause_s=0.0,
                skip_unchanged_state=BY_KEY[domain_key].skip_unchanged_state,
                abort_on=(RuntimeError,),  # missing API key: every target would fail
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return IngestBackfillOut(
        domain=display_name,
        days_requested=days,
        days_successfully_ingested=successes,
    )


@router.post("/v1/ingest/replace", response_model=IngestReplaceOut, dependencies=[Depends(require_admin)])
async def ingest_replace(request: Request, domain: str = Query(...)) -> IngestReplaceOut:
    """
    Forget everything learned for *domain* and relearn it from the evidence
    records in the body (a JSON list), oldest first: for replacing a history
    with a clean one built elsewhere, such as a replay as first published.
    """
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    body = await request.json()
    if not isinstance(body, list):
        raise HTTPException(status_code=422, detail="the body must be a JSON list of evidence records")
    try:
        records = [EvidenceRecord.model_validate(r) for r in body]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    unfit = _values_outside_support(records, engine.get_population(domain_id).candidates[0].variables)
    if unfit:
        raise HTTPException(status_code=422, detail="values the variables cannot take: " + "; ".join(unfit[:10]))
    async with context.ingest_lock(request.app.state, domain_key):
        engine.reset_domain(domain_id)
        learned = learn_new_records(engine, domain_id, records)
    return IngestReplaceOut(domain=display_name, records_supplied=len(records), records_learned=learned)


@dataclass
class _DomainRebuild:
    days_requested: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    records_learned: Optional[int] = None
    targets_missed: list[date] = field(default_factory=list)
    error: Optional[str] = None
    state: Literal["running", "done", "failed"] = "running"

    def out(self, display_name: str) -> DomainRebuildOut:
        return DomainRebuildOut(domain=display_name, state=self.state, days_requested=self.days_requested,
                                started_at=self.started_at, finished_at=self.finished_at,
                                records_learned=self.records_learned, targets_missed=self.targets_missed,
                                error=self.error)


@router.post("/v1/ingest/rebuild", response_model=DomainRebuildOut, status_code=202,
             dependencies=[Depends(require_admin)])
async def rebuild_domain(request: Request, domain: str = Query(...),
                         days: int = Query(730, ge=1, le=1825)) -> DomainRebuildOut:
    """
    Start forgetting everything learned for *domain* and relearning it from
    *days* of history refetched from its own sources with the current code,
    in the background; GET this route for progress. For histories written
    before unavailable inputs were recorded as MISSING (D10). 409 while one
    is running.
    """
    domain_key = domain.lower()
    state = request.app.state
    engine, domain_id, display_name = context.resolve_domain(domain_key, state)
    current = state.rebuilds.get(domain_key)
    if current is not None and current.finished_at is None:
        raise HTTPException(status_code=409, detail=f"a {domain_key} rebuild started at {current.started_at} is still running")
    reg = BY_KEY[domain_key]
    targets = reg.cadence.window_targets(days, context.utcnow().date())
    job = _DomainRebuild(days_requested=days, started_at=context.utcnow())
    state.rebuilds[domain_key] = job

    async def run() -> None:
        try:
            async with context.ingest_lock(state, domain_key):
                result = await rebuild(engine, domain_id, context.fetcher(domain_key), targets,
                                       pause_s=reg.backfill_pause_s)
            job.records_learned, job.targets_missed = result.learned, result.missed
            job.state = "done"
        except asyncio.CancelledError:
            job.error, job.state = "cancelled: the service stopped", "failed"
            raise
        except Exception as exc:  # noqa: BLE001 — no caller to raise to; reported by the status route
            logger.error("%s rebuild failed: %s", domain_key, exc, exc_info=True)
            job.error, job.state = f"{type(exc).__name__}: {exc}", "failed"
        finally:
            job.finished_at = context.utcnow()

    task = asyncio.create_task(run(), name=f"{domain_key}-rebuild")
    state.background_tasks.append(task)
    task.add_done_callback(state.background_tasks.remove)
    return job.out(display_name)


@router.get("/v1/ingest/rebuild", response_model=DomainRebuildOut, dependencies=[Depends(require_admin)])
async def domain_rebuild_status(request: Request, domain: str = Query(...)) -> DomainRebuildOut:
    domain_key = domain.lower()
    _, _, display_name = context.resolve_domain(domain_key, request.app.state)
    job = request.app.state.rebuilds.get(domain_key)
    return DomainRebuildOut(domain=display_name, state="idle") if job is None else job.out(display_name)


def _values_outside_support(records: list[EvidenceRecord], variables: list[Variable]) -> list[str]:
    """Each observed value, or soft-evidence key, that its variable cannot
    take: checked before a replace forgets the domain, since learning would
    fail on it only after the reset."""
    support = {v.variable_id: (v.name, v.support) for v in variables}
    out = []
    for r in records:
        for a in r.observed_assignments:
            if a.variable_id not in support or a.missingness == MissingnessType.MISSING:
                continue
            name, allowed = support[a.variable_id]
            values = list(a.probabilities) if a.probabilities else [a.observed_value]
            out += [f"{name}={v!r} at {r.timestamp.date()}" for v in values if v not in allowed]
    return out
