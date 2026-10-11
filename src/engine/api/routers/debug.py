"""Diagnostics endpoints."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ...config import get_structure_mode_config
from ...services.evidence_diagnostics import build_entropy_diagnostics
from ...services.evidence_geometry import build_evidence_geometry_diagnostics
from ...services.structure_diagnostics import build_structure_diagnostics
from .. import context
from ..dto import (
    EntropyDebugOut,
    LearningPipelineStatusOut,
    LearningDebugOut,
    CandidateDiagOut,
    MutationCycleDiagOut,
    StructureDiagOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/debug/entropy", response_model=EntropyDebugOut)
async def debug_entropy(
    request: Request,
    domain: str = Query("ng"),
    limit: Optional[int] = Query(None, ge=1, description="Only the most recent N records; default all."),
) -> EntropyDebugOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    pop = engine.get_population(domain_id)
    candidates = pop.candidates
    variables = candidates[0].variables if candidates else []
    diagnostics = build_entropy_diagnostics(
        records=engine.evidence_store.load_latest(domain_id, limit),
        variables=variables,
    )

    return EntropyDebugOut(
        domain=display_name,
        domain_key=domain_key,
        domain_module_id=domain_id,
        **diagnostics,
    )


@router.get("/v1/debug/evidence-geometry")
async def debug_evidence_geometry(
    request: Request,
    domain: str = Query("ng"),
    limit: Optional[int] = Query(None, ge=1, description="Only the most recent N records; default all."),
) -> dict[str, Any]:
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)
    pop = engine.get_population(domain_id)
    candidates = pop.candidates
    variables = candidates[0].variables if candidates else []
    diagnostics = build_evidence_geometry_diagnostics(
        records=engine.evidence_store.load_latest(domain_id, limit),
        variables=variables,
    )

    return {
        "domain": display_name,
        "domain_key": domain_key,
        "domain_module_id": domain_id,
        **diagnostics,
    }


@router.get("/v1/debug/learning", response_model=LearningDebugOut)
async def debug_learning(request: Request, domain: str = Query("ng")) -> LearningDebugOut:
    """
    Learning-pipeline diagnostics.

    Returns:
    - Evidence record count vs candidate scoring counts
    - How many times ``engine.learn()`` has been called in the current session
    - Last learn timestamp
    - Mutation cycle stats
    - Pipeline status flags (which code paths call learn)

    Useful for diagnosing the "evidence accumulates but candidates never
    score / evolve" failure mode that occurs when the scheduler calls
    ``engine.ingest()`` without ``engine.learn()``.
    """
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)

    pop = engine.get_population(domain_id)
    dom = pop.dominant()
    active = pop.active_candidates()
    mutation_stats = engine.population_manager.last_mutation_stats(domain_id)

    return LearningDebugOut(
        domain=display_name,
        domain_module_id=domain_id,
        total_evidence_records=engine.evidence_store.count(domain_id),
        active_candidates=len(active),
        dominant_evidence_count=dom.evidence_count if dom else 0,
        dominant_log_score=dom.log_score if dom else 0.0,
        learn_calls_this_session=engine._learn_call_count.get(domain_id, 0),
        last_learn_timestamp=engine._learn_last_ts.get(domain_id),
        records_scored_this_session=engine._learn_records_total.get(domain_id, 0),
        last_mutation_total_attempts=mutation_stats.get("total_attempts", 0),
        last_mutation_introduced=mutation_stats.get("introduced", 0),
        current_generation=pop.generation,
        pipeline_status=LearningPipelineStatusOut(
            # All three scheduler run_once() methods now call engine.learn()
            scheduler_calls_learn=True,
            # startup backfill goes through runtime.ingestion, which calls learn()
            backfill_calls_learn=True,
            # /v1/ingest/trigger uses context.ingest_domain_evidence() which calls learn()
            trigger_calls_learn=True,
        ),
    )


@router.get("/v1/debug/structure", response_model=StructureDiagOut)
async def debug_structure(request: Request, domain: str = Query("ng")) -> StructureDiagOut:
    """
    Per-candidate structure-learning diagnostics.

    Returns BIC scores under both strict (multiplier=1.0) and explore
    (multiplier=0.25) regimes so operators can distinguish genuine graph
    sparsity from over-regularisation.  Also reports mutation-cycle stats
    (attempts, DAG violations, duplicate rejections, introductions) from the
    most recent ``introduce_variants()`` call.

    The ``env_mode`` and ``env_bic_multiplier`` fields reflect the current
    value of the ``POE_STRUCTURE_MODE`` environment variable.  Setting it to
    ``explore`` does **not** change live population management — it only
    controls which multiplier is shown in ``env_bic_multiplier``.
    """
    domain_key = domain.lower()
    engine, domain_id, display_name = context.resolve_domain(domain_key, request.app.state)

    pop = engine.get_population(domain_id)
    mutation_stats = engine.population_manager.last_mutation_stats(domain_id)
    total_evidence = engine.evidence_store.count(domain_id)

    try:
        cfg = get_structure_mode_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    diags = build_structure_diagnostics(
        pop=pop,
        mutation_stats=mutation_stats,
        total_evidence_records=total_evidence,
        env_mode=cfg.mode,
        env_bic_multiplier=cfg.bic_penalty_multiplier,
    )

    return StructureDiagOut(
        domain=display_name,
        domain_module_id=diags.domain_module_id,
        env_mode=diags.env_mode,
        env_bic_multiplier=diags.env_bic_multiplier,
        total_evidence_records=diags.total_evidence_records,
        candidates=[
            CandidateDiagOut(
                candidate_id=cd.candidate_id,
                description=cd.description,
                generation=cd.generation,
                status=cd.status,
                edge_structure=cd.edge_structure,
                active_edge_count=cd.active_edge_count,
                total_edge_count=cd.total_edge_count,
                evidence_count=cd.evidence_count,
                log_score=cd.log_score,
                avg_ll=cd.avg_ll,
                bic_penalty_raw=cd.bic_penalty_raw,
                bic_score_strict=cd.bic_score_strict,
                bic_score_explore=cd.bic_score_explore,
                is_dominant=cd.is_dominant,
            )
            for cd in diags.candidates
        ],
        last_mutation_cycle=MutationCycleDiagOut(
            total_attempts=diags.last_mutation_cycle.total_attempts,
            dag_violations=diags.last_mutation_cycle.dag_violations,
            duplicate_rejections=diags.last_mutation_cycle.duplicate_rejections,
            introduced=diags.last_mutation_cycle.introduced,
        ),
    )
