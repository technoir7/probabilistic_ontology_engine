"""LLM report read and refresh (hash-gated Fireworks calls)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ...runtime.settings import Settings
from .. import context
from .. import narrative
from .. import report as _report
from ..dto import (
    OntologyMode,
    DomainReportOut,
    DomainReportNotFound,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Report endpoints ──────────────────────────────────────────────────────────
#
# GET  /v1/report/{domain}          — read-only; returns latest cached report or
#                                     {"found": false} if none exists. Never calls LLM.
# POST /v1/report/{domain}/refresh  — builds snapshot, checks hash, calls Fireworks
#                                     only when snapshot has changed.


@router.get("/v1/report/{domain}")
async def domain_report_read(
    request: Request,
    domain: str,
    ontology_mode: OntologyMode = Query("apriori"),
) -> Any:
    """
    Read-only: return the latest cached report for this domain/mode without
    rebuilding the snapshot or calling the LLM.  Returns found=False when no
    cached report exists so callers can distinguish "never generated" from an
    error.
    """
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")

    data_dir = Settings.from_env().data_dir
    stale_path = _report.stale_cache_path(data_dir, key, ontology_mode)
    if not stale_path:
        return DomainReportNotFound(domain=key, ontology_mode=ontology_mode)

    cached = _report.load_cache(stale_path)
    if not cached:
        return DomainReportNotFound(domain=key, ontology_mode=ontology_mode)

    return DomainReportOut(**cached, found=True, cached=True, regenerated=False)


@router.post("/v1/report/{domain}/refresh")
async def domain_report_refresh(
    request: Request,
    domain: str,
    ontology_mode: OntologyMode = Query("apriori"),
) -> Any:
    """
    Build the current snapshot, compute its hash, and return a report.

    - If the snapshot hash matches the latest cached report, return that
      cached report immediately (cached=True, regenerated=False).
    - If the hash has changed (new evidence, changed beliefs, new frontier),
      call Fireworks AI, persist the new report, and return it
      (cached=False, regenerated=True).
    - On Fireworks failure: serve matching or stale cached report with
      stale=True; return 502 only if no cached report exists at all.

    Requires FIREWORKS_API_KEY to be set when generation is needed.
    """
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")

    # Build snapshot once — only here in the POST path, never in GET.
    snapshot_out = narrative.snapshot_for(request.app.state, key, ontology_mode)
    snapshot_dict = snapshot_out.model_dump()
    h = _report.snapshot_hash(snapshot_dict)

    data_dir = Settings.from_env().data_dir
    exact_path = _report.cache_path(data_dir, key, ontology_mode, h)

    # Cache hit: snapshot unchanged, return immediately without calling LLM.
    exact = _report.load_cache(exact_path)
    if exact:
        logger.debug("Report cache hit %s/%s hash=%s", key, ontology_mode, h[:12])
        return DomainReportOut(**exact, found=True, cached=True, regenerated=False)

    # Need to generate.  Fail fast with a clear message if key is absent.
    settings = Settings.from_env()
    api_key = settings.fireworks_api_key
    if not api_key:
        stale_path = _report.stale_cache_path(data_dir, key, ontology_mode)
        if stale_path:
            stale = _report.load_cache(stale_path)
            if stale:
                logger.info("Serving stale report for %s (FIREWORKS_API_KEY not set)", key)
                return DomainReportOut(**stale, found=True, cached=True, regenerated=False, stale=True)
        raise HTTPException(
            status_code=503,
            detail=(
                "FIREWORKS_API_KEY not configured. "
                "Set it to enable report generation."
            ),
        )

    try:
        report_text = await _report.generate_report(
            snapshot=snapshot_dict,
            api_key=api_key,
            model=settings.fireworks_model,
            timeout=90.0,
        )
    except Exception as exc:
        logger.error("Fireworks generation failed for %s: %s", key, exc, exc_info=True)
        stale_path = _report.stale_cache_path(data_dir, key, ontology_mode)
        if stale_path:
            stale = _report.load_cache(stale_path)
            if stale:
                logger.info("Serving stale report for %s after generation failure", key)
                return DomainReportOut(**stale, found=True, cached=True, regenerated=False, stale=True)
        raise HTTPException(
            status_code=502,
            detail=f"Report generation failed: {exc}",
        ) from exc

    data = {
        "domain": key,
        "ontology_mode": ontology_mode,
        "generated_at": context.utcnow().isoformat(),
        "snapshot_hash": h,
        "report": report_text,
    }
    _report.save_cache(exact_path, data)
    return DomainReportOut(**data, found=True, cached=False, regenerated=True)
