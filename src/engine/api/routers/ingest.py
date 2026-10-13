"""Manual ingestion: trigger, backfill, art reports and rebuild."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...runtime import art
from ...runtime.ingestion import backfill, learn_new_records, rebuild
from ...runtime.registry import BY_KEY
from ...runtime.settings import Settings
from .. import context, presenters
from ..auth import require_admin
from ..dto import (
    IngestTriggerOut,
    IngestBackfillOut,
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


@router.post("/v1/ingest/art/rebuild", response_model=ArtRebuildOut, dependencies=[Depends(require_admin)])
async def rebuild_art(
    request: Request,
    # Bounded: one upstream fetch per month.
    months: int = Query(60, ge=1, le=240),
) -> ArtRebuildOut:
    """
    Forget everything learned for art and relearn it from *months* of fetched
    evidence plus every report in the reports directory, oldest first. Slow:
    one fetch per month, with the domain's backfill pause between them.
    """
    engine, domain_id, display_name = context.resolve_domain("art", request.app.state)
    reg = BY_KEY["art"]
    today = context.utcnow().date()
    targets = reg.cadence.window_targets(round(months * 31), today)[-months:]
    batch = art.load_reports(art.reports_dir(Settings.from_env()))
    async with context.ingest_lock(request.app.state, "art"):
        learned = await rebuild(
            engine, domain_id, context.fetcher("art"), targets, batch.records, pause_s=reg.backfill_pause_s,
        )
    return ArtRebuildOut(
        domain=display_name,
        months_requested=months,
        reports_found=len(batch.records),
        records_learned=learned,
        failed_reports=batch.failed,
    )
