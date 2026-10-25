"""Posterior queries against one candidate."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ...schemas import InferenceQuery, PopulationAggregation, QueryType
from .. import context, presenters
from ..dto import (
    GraphNodeOut,
    GraphEdgeOut,
    FrontierEdgeOut,
    InferenceOut,
    QueryBodyIn,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/v1/inference/query", response_model=InferenceOut)
async def inference_query(request: Request, body: QueryBodyIn) -> InferenceOut:
    engine, domain_id, display_name = context.resolve_domain(body.domain, request.app.state)

    pop = engine.get_population(domain_id)

    cand = context.resolve_query_candidate(pop, body.candidate_id)

    # Fuzzy-resolve target variable
    target_var = presenters.find_variable_fuzzy(cand, body.target_variable)
    if target_var is None:
        raise HTTPException(
            status_code=422,
            detail=f"Variable '{body.target_variable}' not found in domain '{body.domain}'",
        )

    weighted = body.aggregation == "weighted_avg"
    iq = InferenceQuery(
        domain_module_id=domain_id,
        target_variables=[target_var.name],
        query_type=QueryType.MARGINAL,
        population_aggregation=(
            PopulationAggregation.WEIGHTED_AVERAGE if weighted else PopulationAggregation.ACTIVE_ONLY
        ),
    )
    # weighted_avg is the population's answer, weighted by structure posterior
    # (one inference per candidate with non-negligible weight). Otherwise query
    # the resolved candidate itself: population-level ACTIVE_ONLY answers for
    # the dominant one, whatever was asked. The graph is the candidate's either way.
    raw = engine.query(iq) if weighted else engine.inference_service.query_candidate(cand, iq)
    dist = raw.get("posteriors", {}).get(target_var.name, {})
    target_level, target_degree = presenters.reading(dist, target_var)

    # Build graph
    thresholds = engine.thresholds(domain_id)
    explore_lo, explore_hi = thresholds.explore_band

    nodes: list[GraphNodeOut] = []
    for v in cand.variables:
        node_status = presenters.node_status_label(v.name, target_var.name, cand, explore_lo, explore_hi)
        nodes.append(GraphNodeOut(
            id=v.name,
            label=v.name,
            degree=target_degree if v.name == target_var.name else None,
            status=node_status,
        ))

    edges: list[GraphEdgeOut] = []
    frontier: list[FrontierEdgeOut] = []
    for e in cand.get_active_edges():
        pv = cand.get_variable_by_id(e.parent_variable_id)
        cv = cand.get_variable_by_id(e.child_variable_id)
        if not pv or not cv:
            continue
        ep = e.existence_probability
        estatus = presenters.edge_status_label(ep, explore_lo, explore_hi)
        edges.append(GraphEdgeOut(
            source=pv.name,
            target=cv.name,
            probability=ep,
            status=estatus,
        ))
        if explore_lo <= ep <= explore_hi:
            frontier.append(FrontierEdgeOut(
                relation=e.explanatory_label or f"{pv.name}→{cv.name}",
                source=pv.name,
                target=cv.name,
                probability=ep,
                note=f"existence_probability={ep:.3f} in explore band [{explore_lo}, {explore_hi}]",
                explore_weight=e.explore_weight,
            ))

    return InferenceOut(
        candidate_id=str(cand.candidate_id),
        target_variable=target_var.name,
        target_level=target_level,
        target_degree=target_degree,
        target_distribution={str(k): float(p) for k, p in dist.items()},
        nodes=nodes,
        edges=edges,
        frontier_edges=frontier,
    )
