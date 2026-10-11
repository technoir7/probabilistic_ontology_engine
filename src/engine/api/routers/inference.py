"""Posterior queries against one candidate."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ...schemas import InferenceQuery, PopulationAggregation, QueryType
from .. import context, poea_dynamic, presenters
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

    if (
        body.ontology_mode == "dynamic"
        and poea_dynamic.is_dynamic_available(body.domain.lower())
    ):
        data = poea_dynamic.build_inference(body.target_variable)
        if data is not None:
            return InferenceOut.model_validate(data)

    pop = engine.get_population(domain_id)

    cand = context.resolve_query_candidate(pop, body.candidate_id)

    # Fuzzy-resolve target variable
    target_var = presenters.find_variable_fuzzy(cand, body.target_variable)
    if target_var is None:
        raise HTTPException(
            status_code=422,
            detail=f"Variable '{body.target_variable}' not found in domain '{body.domain}'",
        )

    # Query the resolved candidate itself; population-level ACTIVE_ONLY always
    # answers for the dominant one, whatever candidate the caller asked about.
    iq = InferenceQuery(
        domain_module_id=domain_id,
        target_variables=[target_var.name],
        query_type=QueryType.MARGINAL,
        population_aggregation=PopulationAggregation.ACTIVE_ONLY,
    )
    raw = engine.inference_service.query_candidate(cand, iq)
    posteriors = raw.get("posteriors", {})
    dist = posteriors.get(target_var.name, {})
    # P(True) for BOOLEAN variables; first value otherwise
    target_prob = presenters.p_true(dist)

    # Build graph
    thresholds = engine.thresholds(domain_id)
    explore_lo, explore_hi = thresholds.explore_band

    nodes: list[GraphNodeOut] = []
    for v in cand.variables:
        node_status = presenters.node_status_label(v.name, target_var.name, cand, explore_lo, explore_hi)
        prob: float | None = None
        if v.name == target_var.name:
            prob = target_prob
        nodes.append(GraphNodeOut(
            id=v.name,
            label=v.name,
            probability=prob,
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
        target_probability=target_prob,
        nodes=nodes,
        edges=edges,
        frontier_edges=frontier,
    )
