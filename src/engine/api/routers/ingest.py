"""Manual ingestion: trigger, backfill, art reports and rebuild."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...runtime import art
from ...runtime.ingestion import backfill, learn_new_records, rebuild
from ...runtime.registry import BY_KEY
from ...runtime.settings import Settings
from ...engine import ProbabilisticOntologyEngine
from ...schemas import EvidenceRecord
from .. import context, presenters
from ..auth import require_admin
from ..dto import (
    IngestTriggerOut,
    IngestBackfillOut,
    IngestReplaceOut,
    ArtReportIngestOut,
    ArtRebuildOut,
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
    async with context.ingest_lock(request.app.state, domain_key):
        engine.reset_domain(domain_id)
        learned = learn_new_records(engine, domain_id, records)
    return IngestReplaceOut(domain=display_name, records_supplied=len(records), records_learned=learned)


@router.post("/v1/ingest/art/manual", response_model=ArtReportIngestOut, dependencies=[Depends(require_admin)])
async def ingest_art_reports(request: Request, path: Optional[str] = Query(None)) -> ArtReportIngestOut:
    """Learn the report files under *path* (default: the reports directory) not yet stored."""
    engine, domain_id, display_name = context.resolve_domain("art", request.app.state)
    root = art.reports_dir(Settings.from_env())
    input_path = Path(path) if path else root
    if not input_path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(status_code=400, detail=f"path must be inside the manual-ingest directory ({root})")

    batch = art.load_reports(input_path)
    async with context.ingest_lock(request.app.state, "art"):
        learned = learn_new_records(engine, domain_id, batch.records)
    return ArtReportIngestOut(
        domain=display_name,
        input_path=str(input_path),
        files_scanned=batch.files_scanned,
        items_found=batch.items_found,
        records_found=len(batch.records),
        records_learned=learned,
        records_skipped_duplicates=len(batch.records) - learned,
        failed=batch.failed,
    )


@dataclass
class _RebuildJob:
    months_requested: int
    started_at: datetime
    reports_found: int
    failed_reports: list[str]
    finished_at: Optional[datetime] = None
    records_learned: Optional[int] = None
    error: Optional[str] = None
    state: Literal["running", "done", "failed"] = "running"

    def out(self, display_name: str) -> ArtRebuildOut:
        return ArtRebuildOut(
            domain=display_name,
            state=self.state,
            months_requested=self.months_requested,
            started_at=self.started_at,
            finished_at=self.finished_at,
            reports_found=self.reports_found,
            records_learned=self.records_learned,
            failed_reports=self.failed_reports,
            error=self.error,
        )


@router.post(
    "/v1/ingest/art/rebuild", response_model=ArtRebuildOut, status_code=202, dependencies=[Depends(require_admin)],
)
async def rebuild_art(
    request: Request,
    # Bounded: the museum years are a few AIC requests each, and the
    # domain's backfill pause runs between months.
    months: int = Query(36, ge=1, le=120),
) -> ArtRebuildOut:
    """
    Start forgetting everything learned for art and relearning it from
    *months* of fetched evidence plus every report in the reports directory,
    oldest first. Runs in the background, since it outlasts any request
    timeout; GET this route for its progress. 409 while one is running.
    """
    state = request.app.state
    engine, domain_id, display_name = context.resolve_domain("art", state)
    current: Optional[_RebuildJob] = state.art_rebuild
    if current is not None and current.finished_at is None:
        raise HTTPException(status_code=409, detail=f"an art rebuild started at {current.started_at} is still running")

    reg = BY_KEY["art"]
    targets = reg.cadence.window_targets(round(months * 31), context.utcnow().date())[-months:]
    batch = art.load_reports(art.reports_dir(Settings.from_env()))
    job = _RebuildJob(
        months_requested=months,
        started_at=context.utcnow(),
        reports_found=len(batch.records),
        failed_reports=batch.failed,
    )
    state.art_rebuild = job
    task = asyncio.create_task(
        _run_rebuild(job, state, engine, domain_id, targets, batch.records, reg.backfill_pause_s),
        name="art-rebuild",
    )
    state.background_tasks.append(task)
    task.add_done_callback(state.background_tasks.remove)
    return job.out(display_name)


@router.get("/v1/ingest/art/rebuild", response_model=ArtRebuildOut, dependencies=[Depends(require_admin)])
async def art_rebuild_status(request: Request) -> ArtRebuildOut:
    """The latest art rebuild since the service started."""
    _, _, display_name = context.resolve_domain("art", request.app.state)
    job: Optional[_RebuildJob] = request.app.state.art_rebuild
    return ArtRebuildOut(domain=display_name, state="idle") if job is None else job.out(display_name)


async def _run_rebuild(
    job: _RebuildJob,
    state: Any,
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    targets: list[date],
    reports: list[EvidenceRecord],
    pause_s: float,
) -> None:
    try:
        async with context.ingest_lock(state, "art"):
            job.records_learned = await rebuild(engine, domain_id, context.fetcher("art"), targets, reports, pause_s=pause_s)
        job.state = "done"
    except asyncio.CancelledError:
        job.error, job.state = "cancelled: the service stopped", "failed"
        raise
    except Exception as exc:  # noqa: BLE001 — no caller to raise to; logged and reported by the status route
        logger.error("art rebuild failed: %s", exc, exc_info=True)
        job.error, job.state = f"{type(exc).__name__}: {exc}", "failed"
    finally:
        job.finished_at = context.utcnow()
