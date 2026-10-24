"""Narrative snapshot export (input to LLM reports)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request

from .. import narrative
from ..dto import NarrativeSnapshotOut

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/export/narrative-snapshot", response_model=NarrativeSnapshotOut)
async def narrative_snapshot(
    request: Request,
    domain: str = Query("ng"),
) -> NarrativeSnapshotOut:
    """
    Structured epistemic-state snapshot designed to be passed to an LLM for
    prose interpretation.  Returns the full current state of the probabilistic
    engine for a domain: regime variables, dominant hypothesis, population
    competition, causal frontier, and machine-readable interpretation hints.
    """
    return narrative.snapshot_for(request.app.state, domain)
