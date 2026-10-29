"""LLM report read and refresh (hash-gated Fireworks calls)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...runtime.settings import Settings
from .. import context
from .. import narrative
from .. import report as _report
from ..dto import (
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
) -> Any:
    """
    Read-only: return the latest cached report for this domain without
    rebuilding the snapshot or calling the LLM.  Returns found=False when no
    cached report exists so callers can distinguish "never generated" from an
    error.
    """
    key = domain.lower()
    if key not in context.DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'")
    return _read(key, key, _report.PROMPT_VERSION)


@router.post("/v1/report/{domain}/refresh")
async def domain_report_refresh(
    request: Request,
    domain: str,
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
    snapshot_dict = narrative.snapshot_for(request.app.state, key).model_dump()
    return await _refresh(key, key, snapshot_dict, _report.PROMPT_VERSION, _report._PROMPT_PATH)


# ── One trend list's report (D30) ─────────────────────────────────────────────
#
# GET  /v1/trends/{domain}/{list}/report          — cached only, as above
# POST /v1/trends/{domain}/{list}/report/refresh  — hash-gated, its own prompt

def _trend_list(domain: str, name: str) -> dict:
    try:
        return narrative.trend_list_snapshot(domain, name).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/trends/{domain}/{name}/report")
async def trend_report_read(domain: str, name: str) -> Any:
    snap = _trend_list(domain, name)
    return _read(f"{snap['domain']}-trends-{name}", snap["domain"], _report.TREND_PROMPT_VERSION)


@router.post("/v1/trends/{domain}/{name}/report/refresh")
async def trend_report_refresh(domain: str, name: str) -> Any:
    snap = _trend_list(domain, name)
    return await _refresh(f"{snap['domain']}-trends-{name}", snap["domain"], snap,
                          _report.TREND_PROMPT_VERSION, _report.TREND_PROMPT_PATH)


# ── Shared by both kinds of report ────────────────────────────────────────────
# CACHE_KEY names the report's files; DOMAIN is what the response reports.

def _read(cache_key: str, domain: str, version: str) -> Any:
    data_dir = Settings.from_env().data_dir
    stale_path = _report.stale_cache_path(data_dir, cache_key, version)
    cached = _report.load_cache(stale_path) if stale_path else None
    if not cached:
        return DomainReportNotFound(domain=domain)
    return DomainReportOut(**cached, found=True, cached=True, regenerated=False)


async def _refresh(cache_key: str, domain: str, snapshot_dict: dict, version: str, prompt_path) -> Any:
    h = _report.snapshot_hash(snapshot_dict)
    data_dir = Settings.from_env().data_dir
    exact_path = _report.cache_path(data_dir, cache_key, h, version)

    # Cache hit: snapshot unchanged, return immediately without calling LLM.
    exact = _report.load_cache(exact_path)
    if exact:
        logger.debug("Report cache hit %s hash=%s", cache_key, h[:12])
        return DomainReportOut(**exact, found=True, cached=True, regenerated=False)

    def stale_or(exc: HTTPException) -> Any:
        stale_path = _report.stale_cache_path(data_dir, cache_key, version)
        stale = _report.load_cache(stale_path) if stale_path else None
        if stale:
            logger.info("Serving stale report for %s", cache_key)
            return DomainReportOut(**stale, found=True, cached=True, regenerated=False, stale=True)
        raise exc

    # Need to generate.  Fail fast with a clear message if key is absent.
    settings = Settings.from_env()
    api_key = settings.fireworks_api_key
    if not api_key:
        return stale_or(HTTPException(
            status_code=503, detail="FIREWORKS_API_KEY not configured. Set it to enable report generation."))

    try:
        report_text = await _report.generate_report(
            snapshot=snapshot_dict, api_key=api_key, model=settings.fireworks_model, timeout=90.0,
            prompt_path=prompt_path)
    except Exception as exc:
        logger.error("Fireworks generation failed for %s: %s", cache_key, exc, exc_info=True)
        return stale_or(HTTPException(status_code=502, detail=f"Report generation failed: {exc}"))

    data = {
        "domain": domain,
        "generated_at": context.utcnow().isoformat(),
        "snapshot_hash": h,
        "report": report_text,
    }
    _report.save_cache(exact_path, data)
    return DomainReportOut(**data, found=True, cached=False, regenerated=True)
