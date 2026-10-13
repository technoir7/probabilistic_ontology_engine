"""Manual ingestion: trigger, backfill, art manual ingest."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from ...runtime.art import import_art_module
from ...runtime.ingestion import backfill
from ...runtime.registry import BY_KEY
from ...runtime.settings import Settings
from .. import context, presenters
from ..auth import require_admin
from ..dto import (
    IngestTriggerOut,
    IngestBackfillOut,
    ManualArtIngestOut,
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


@router.post("/v1/ingest/art/manual", response_model=ManualArtIngestOut, dependencies=[Depends(require_admin)])
async def ingest_art_manual(
    request: Request,
    path: Optional[str] = Query(None),
    force: bool = Query(False),
    append: bool = Query(False),
) -> ManualArtIngestOut:
    domain_key = "art"
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    lock = context.ingest_lock(request.app.state, domain_key)
    manual_ingest = import_art_module("manual_ingest")
    root = Settings.from_env().art_manual_dir or context.default_art_manual_dir(manual_ingest)
    input_path = Path(path) if path else root
    # Unauthenticated route: never read outside the manual-ingest directory.
    if not input_path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(
            status_code=400,
            detail=f"path must be inside the manual-ingest directory ({root})",
        )

    async with lock:
        try:
            collection = manual_ingest.collect_manual_path(input_path)
        except (OSError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        records = collection.records
        before = engine.evidence_store.count(domain_id)
        rebuild_mode = not append
        causal_prior_result = {
            "weight": 0.0,
            "candidates_scored": 0,
            "total_prior_applied": 0.0,
            "dominant_changed": False,
        }
        if rebuild_mode:
            records_replaced, records_removed_stale, records_learned = (
                manual_ingest.rebuild_art_evidence_state(engine, records, domain_id)
            )
            causal_prior_result = getattr(engine, "_art_causal_prior_result", causal_prior_result)
            skipped_duplicates = 0
            after = engine.evidence_store.count(domain_id)
            records_ingested = records_replaced
        else:
            records_to_ingest, skipped_duplicates = manual_ingest.filter_duplicate_records(
                records,
                manual_ingest.existing_fingerprints(engine),
                force=force,
            )
            if records_to_ingest:
                engine.ingest_batch(records_to_ingest)
            after = engine.evidence_store.count(domain_id)
            records_replaced = 0
            records_removed_stale = 0
            records_ingested = after - before
            if records_to_ingest and not manual_ingest.learning_state_uninitialized(
                engine,
                domain_id,
            ):
                engine.learn(records_to_ingest, domain_id)
                records_learned = len(records_to_ingest)
            else:
                records_learned = manual_ingest.ensure_learning_for_existing_evidence(
                    engine,
                    domain_id,
                    force=force and not records_to_ingest,
                )
                causal_prior_result = getattr(engine, "_art_causal_prior_result", causal_prior_result)

    return ManualArtIngestOut(
        domain=display_name,
        domain_key=domain_key,
        domain_module_id=domain_id,
        input_path=str(input_path),
        db_path=engine.evidence_store.db_path,
        rebuild_mode=rebuild_mode,
        files_scanned=collection.files_scanned,
        objects_found=collection.objects_found,
        records_loaded_from_files=len(records),
        records_replaced=records_replaced,
        records_removed_stale=records_removed_stale,
        records_found=collection.objects_found,
        records_ingested=records_ingested,
        records_skipped_duplicates=skipped_duplicates,
        records_failed=len(collection.errors),
        records_learned=records_learned,
        causal_prior_weight=float(causal_prior_result.get("weight", 0.0)),
        causal_prior_candidates_scored=int(causal_prior_result.get("candidates_scored", 0)),
        causal_prior_total_applied=float(causal_prior_result.get("total_prior_applied", 0.0)),
        causal_prior_dominant_changed=bool(causal_prior_result.get("dominant_changed", False)),
        evidence_count_before=before,
        evidence_count_after=after,
        verification_endpoint="/v1/debug/learning?domain=art",
    )
