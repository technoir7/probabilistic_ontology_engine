"""Population state: status, candidates, lineage, paradigm shifts."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ...engine import ProbabilisticOntologyEngine
from ...model.scoring import candidate_score
from ...schemas import OntologyCandidate
from .. import context, poea_dynamic, presenters
from ..dto import (
    PopStatusOut,
    CandidateOut,
    CandidatesOut,
    LineageEventOut,
    LineageOut,
    ParadigmShiftEventOut,
    ParadigmShiftsOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/population/status", response_model=PopStatusOut)
async def population_status(
    request: Request,
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> PopStatusOut:
    engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_population_status(display_name)
        if data is not None:
            return PopStatusOut.model_validate(data)
    return presenters.build_population_status(engine, domain_id, display_name)


@router.get("/v1/population/candidates", response_model=CandidatesOut)
async def population_candidates(
    request: Request,
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> CandidatesOut:
    engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_candidates(display_name)
        if data is not None:
            return CandidatesOut.model_validate(data)
    pop = engine.get_population(domain_id)
    active = pop.active_candidates()
    dom = pop.dominant()
    dom_id = dom.candidate_id if dom else None

    avg_fn = candidate_score
    score_map = presenters.normalize_scores(active, avg_fn)

    # Sort best-first
    sorted_cands = sorted(active, key=avg_fn, reverse=True)
    n = len(sorted_cands)

    out: list[CandidateOut] = []
    for i, c in enumerate(sorted_cands):
        if c.candidate_id == dom_id:
            status: Literal["dominant", "rising", "falling", "neutral"] = "dominant"
        elif i < max(1, n // 3) and c.evidence_count > 0:
            status = "rising"
        elif i >= max(1, 2 * n // 3) and c.evidence_count > 0:
            status = "falling"
        else:
            status = "neutral"

        out.append(CandidateOut(
            id=str(c.candidate_id),
            name=c.description or f"Candidate {str(c.candidate_id)[:8]}",
            log_score=c.log_score,
            evidence_count=c.evidence_count,
            generation_introduced=c.generation,
            edge_count=len(c.get_active_edges()),
            status=status,
            score_normalized=score_map.get(c.candidate_id, 0.5),
        ))

    return CandidatesOut(
        domain=display_name,
        generation=pop.generation,
        candidates=out,
    )


@router.get("/v1/population/lineage/{candidate_id}", response_model=LineageOut)
async def population_lineage(
    request: Request,
    candidate_id: str,
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> LineageOut:
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        _, _, display_name = context.resolve_domain(domain, request.app.state)
        data = poea_dynamic.build_lineage(candidate_id, display_name)
        if data is not None:
            return LineageOut.model_validate(data)
        raise HTTPException(
            status_code=404,
            detail=f"Dynamic candidate '{candidate_id}' not found in POE-A artifacts",
        )
    engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
    pop = engine.get_population(domain_id)

    # Find the requested candidate (active or pruned) in the specified domain first.
    all_cands = {str(c.candidate_id): c for c in pop.candidates}

    # Cross-domain fallback: if the candidate isn't in the specified domain's
    # population, search all other loaded engines.  This handles the common
    # case where the caller omits ?domain=<key> or passes the wrong one
    # (e.g. calling lineage with an MR UUID while domain defaults to "ng").
    if candidate_id not in all_cands:
        engines_map: dict[str, ProbabilisticOntologyEngine] = getattr(
            request.app.state, "engines", {}
        )
        found = False
        for dk, alt_engine in engines_map.items():
            if dk == domain.lower():
                continue  # already searched this one
            alt_dm_id, alt_display = context.DOMAIN_MAP[dk]
            alt_pop = alt_engine.get_population(alt_dm_id)
            alt_cands = {str(c.candidate_id): c for c in alt_pop.candidates}
            if candidate_id in alt_cands:
                pop = alt_pop
                all_cands = alt_cands
                domain_id = alt_dm_id
                display_name = alt_display
                found = True
                break
        if not found:
            raise HTTPException(
                status_code=404, detail=f"Candidate '{candidate_id}' not found"
            )

    target_cand = all_cands[candidate_id]

    # Walk the parent chain (oldest ancestor first)
    chain: list[OntologyCandidate] = []
    cur: OntologyCandidate | None = target_cand
    visited: set[str] = set()
    while cur is not None:
        cid = str(cur.candidate_id)
        if cid in visited:
            break
        visited.add(cid)
        chain.append(cur)
        parent_id = str(cur.parent_candidate_id) if cur.parent_candidate_id else None
        cur = all_cands.get(parent_id) if parent_id else None

    chain.reverse()  # oldest first

    dom = pop.dominant()
    dom_id = str(dom.candidate_id) if dom else None

    events: list[LineageEventOut] = []
    for i, c in enumerate(chain):
        cid_str = str(c.candidate_id)
        if cid_str == candidate_id:
            event_type: Literal["shift", "introduce", "milestone", "current"] = "current"
        elif i == 0:
            event_type = "introduce"
        else:
            event_type = "introduce"

        dominant_after: str | None = None
        if cid_str == dom_id:
            dominant_after = c.description or cid_str

        events.append(LineageEventOut(
            generation=c.generation,
            event_type=event_type,
            description=c.description or f"Candidate introduced at generation {c.generation}",
            dominant_after=dominant_after,
        ))

    # Add a 'shift' event if the target is (or was) dominant
    if dom_id and dom_id == candidate_id and pop.paradigm_shift_count > 0:
        events.append(LineageEventOut(
            generation=pop.generation,
            event_type="shift",
            description=f"Became dominant candidate after {pop.paradigm_shift_count} paradigm shift(s)",
            dominant_after=target_cand.description or candidate_id,
        ))

    return LineageOut(
        domain=display_name,
        candidate_id=candidate_id,
        events=events,
    )


@router.get("/v1/population/shifts", response_model=ParadigmShiftsOut)
async def population_shifts(
    request: Request,
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> ParadigmShiftsOut:
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
        return ParadigmShiftsOut.model_validate(
            poea_dynamic.build_shifts(display_name, domain_id)
        )
    """
    Return the full chronological history of paradigm shifts for a domain.

    A paradigm shift is recorded each time the dominant candidate changes
    during a learning cycle.  Events are written by PopulationManager.end_cycle()
    and persisted to the ``paradigm_shifts`` SQLite table.

    Note: Events are only available from the point when shift logging was first
    enabled.  Older engines that ran before this feature was introduced will
    return an empty list even if shifts occurred historically — the
    ``dominant_hypothesis.candidate_id`` in /v1/population/status still reflects
    the current dominant, and ``paradigm_shifts_this_window`` in that response
    gives the cumulative shift count since startup.
    """
    engine, domain_id, display_name = context.resolve_domain(domain, request.app.state)
    raw = engine.population_store.load_shift_events(domain_id)

    events = [
        ParadigmShiftEventOut(
            shift_id=row["shift_id"],
            generation=row["generation"],
            timestamp=row["shift_ts"],
            previous_dominant_id=row["prev_dominant_id"],
            previous_dominant_name=row["prev_dominant_name"],
            new_dominant_id=row["new_dominant_id"],
            new_dominant_name=row["new_dominant_name"],
            evidence_count_at_shift=row["evidence_count_at_shift"],
        )
        for row in raw
    ]

    return ParadigmShiftsOut(
        domain=display_name,
        domain_module_id=domain_id,
        total_shifts=len(events),
        events=events,
    )
