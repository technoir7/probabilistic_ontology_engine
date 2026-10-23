"""
The narrative snapshot: the engine's epistemic state for one domain as one
structured object, served by /v1/export/narrative-snapshot and hashed and
handed to the LLM by the report routes.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from ..engine import ProbabilisticOntologyEngine
from ..model.scoring import candidate_score
from ..schemas import InferenceQuery, PopulationAggregation, QueryType
from . import context, poea_dynamic, presenters
from .dto import (
    NarrativeCompetingCandidatesOut,
    NarrativeCompetitorOut,
    NarrativeDominantHypothesisOut,
    NarrativeEdgeOut,
    NarrativeFrontierEdgeOut,
    NarrativeFrontierOut,
    NarrativeMetadataOut,
    NarrativeOntologyCompetitionOut,
    NarrativeRecentShiftOut,
    NarrativeRegimeVariableOut,
    NarrativeSnapshotOut,
)


def snapshot_for(state: Any, domain: str, ontology_mode: str) -> NarrativeSnapshotOut:
    """The snapshot for a domain key; POE-A artifacts when dynamic mode has them."""
    engine, domain_id, display_name = context.resolve_domain(domain, state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_narrative_snapshot(display_name, domain_id)
        if data is not None:
            return NarrativeSnapshotOut.model_validate(data)
    return build_snapshot(engine, domain_id, display_name)


def build_snapshot(
    engine: ProbabilisticOntologyEngine, domain_id: str, display_name: str
) -> NarrativeSnapshotOut:
    pop = engine.get_population(domain_id)
    dom = pop.dominant()
    active = pop.active_candidates()
    summary = pop.summary()

    # ── metadata ──────────────────────────────────────────────────────────────
    evidence_count = engine.evidence_store.count(domain_id)
    metadata = NarrativeMetadataOut(
        domain=display_name,
        domain_module_id=domain_id,
        timestamp=context.utcnow().isoformat(),
        evidence_count=evidence_count,
        current_generation=pop.generation,
    )

    # ── current_regime_state: marginal inference per variable ─────────────────
    # Matches RegimeStatePanel: call inference for each variable and use the
    # real posterior P(var=True) rather than raw soft-evidence weights.
    regime_state: list[NarrativeRegimeVariableOut] = []
    # The regime is this period's signals; last period's are inputs (D19).
    variables = [v for v in pop.candidates[0].variables if not v.lag_of] if pop.candidates else []

    if evidence_count == 0 or not variables:
        # No evidence yet — list variables as unobserved so the LLM knows
        # that scores are prior-only.
        for v in variables:
            regime_state.append(NarrativeRegimeVariableOut(
                name=v.name, boolean_state=None, probability=None
            ))
    else:
        for v in variables:
            iq = InferenceQuery(
                domain_module_id=domain_id,
                target_variables=[v.name],
                query_type=QueryType.MARGINAL,
                population_aggregation=PopulationAggregation.ACTIVE_ONLY,
            )
            raw_inf = engine.inference_service.query(iq, pop)
            dist = raw_inf.get("posteriors", {}).get(v.name, {})
            prob: float = presenters.p_true(dist)
            regime_state.append(NarrativeRegimeVariableOut(
                name=v.name,
                boolean_state=prob > 0.5,
                probability=prob,
            ))

    # ── dominant_hypothesis ───────────────────────────────────────────────────
    dominant_out: Optional[NarrativeDominantHypothesisOut] = None
    if dom:
        dom_edges: list[NarrativeEdgeOut] = []
        for e in dom.get_active_edges():
            pv = dom.get_variable_by_id(e.parent_variable_id)
            cv = dom.get_variable_by_id(e.child_variable_id)
            if pv and cv:
                dom_edges.append(NarrativeEdgeOut(
                    source=pv.name,
                    target=cv.name,
                    existence_probability=e.existence_probability,
                ))
        gens_dominant = max(0, pop.generation - dom.generation)
        dominant_out = NarrativeDominantHypothesisOut(
            name=dom.description or str(dom.candidate_id)[:8],
            candidate_id=str(dom.candidate_id),
            edge_count=len(dom_edges),
            edges=dom_edges,
            generations_dominant=gens_dominant,
            log_score=dom.log_score,
        )

    # ── competing_candidates ──────────────────────────────────────────────────
    avg_fn = candidate_score
    score_map = presenters.normalize_scores(active, avg_fn)
    dom_id = dom.candidate_id if dom else None
    ranked = presenters.ranked_candidates(active, dom_id)
    sorted_cands = [c for c, _ in ranked]

    competitor_list: list[NarrativeCompetitorOut] = []
    for c, cstatus in ranked:
        competitor_list.append(NarrativeCompetitorOut(
            name=presenters.candidate_name(c),
            log_score=c.log_score,
            edge_count=len(c.get_active_edges()),
            status=cstatus,
            score_normalized=score_map.get(c.candidate_id, 0.5),
        ))

    # Score gap: dominant avg score minus second-place avg score
    score_gap: Optional[float] = None
    if len(sorted_cands) >= 2 and dom:
        dom_avg = avg_fn(dom)
        second_cand = sorted_cands[1] if sorted_cands[0].candidate_id == dom_id else sorted_cands[0]
        second_avg = avg_fn(second_cand)
        if math.isfinite(dom_avg) and math.isfinite(second_avg):
            score_gap = dom_avg - second_avg

    competing_out = NarrativeCompetingCandidatesOut(
        candidates=competitor_list,
        score_gap_to_dominant=score_gap,
    )

    # ── ontology_competition ──────────────────────────────────────────────────
    entropy = summary["structure_entropy"]
    if entropy < 0.5:
        entropy_interp = "low"
    elif entropy < 1.5:
        entropy_interp = "medium"
    else:
        entropy_interp = "high"

    shift_events = engine.population_store.load_shift_events(domain_id, last=3)
    total_shifts = engine.population_store.count_shift_events(domain_id)
    recent_shifts = [
        NarrativeRecentShiftOut(
            timestamp=ev["shift_ts"],
            from_name=ev["prev_dominant_name"],
            to_name=ev["new_dominant_name"],
            generation=ev["generation"],
        )
        for ev in shift_events
    ]

    ontology_out = NarrativeOntologyCompetitionOut(
        structure_entropy=entropy,
        entropy_interpretation=entropy_interp,
        active_candidates=len(active),
        paradigm_shifts_total=total_shifts,
        recent_shifts=recent_shifts,
    )

    # ── frontier ──────────────────────────────────────────────────────────────
    thresholds = engine.thresholds(domain_id)
    explore_lo, explore_hi = thresholds.explore_band
    frontier_edges_out: list[NarrativeFrontierEdgeOut] = []
    if dom:
        for e in dom.get_active_edges():
            if explore_lo <= e.existence_probability <= explore_hi:
                pv = dom.get_variable_by_id(e.parent_variable_id)
                cv = dom.get_variable_by_id(e.child_variable_id)
                if pv and cv:
                    frontier_edges_out.append(NarrativeFrontierEdgeOut(
                        source=pv.name,
                        target=cv.name,
                        probability=e.existence_probability,
                        relation=e.explanatory_label or f"{pv.name}→{cv.name}",
                    ))

    frontier_out = NarrativeFrontierOut(
        frontier_edge_count=len(frontier_edges_out),
        frontier_edges=frontier_edges_out,
    )

    # ── interpretation_hints ──────────────────────────────────────────────────
    hints: list[str] = []

    # Entropy
    if entropy_interp == "low":
        hints.append(
            f"structure_entropy is low ({entropy:.3f}): engine has converged on "
            "a single dominant causal story"
        )
    elif entropy_interp == "medium":
        hints.append(
            f"structure_entropy is medium ({entropy:.3f}): engine is converging "
            "but competing hypotheses remain plausible"
        )
    else:
        hints.append(
            f"structure_entropy is high ({entropy:.3f}): engine has not converged; "
            "multiple causal stories remain plausible"
        )

    # Dominant tenure
    if dom:
        gens = max(0, pop.generation - dom.generation)
        if gens == 0:
            hints.append("dominant hypothesis was introduced in the current generation")
        elif gens == 1:
            hints.append("dominant hypothesis has held for 1 generation")
        else:
            hints.append(f"dominant hypothesis has held for {gens} generations")
    else:
        hints.append("no dominant hypothesis has been established yet")

    # Last paradigm shift timing
    if shift_events:
        last_ts_str = shift_events[-1]["shift_ts"]
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            days_ago = (context.utcnow() - last_ts).days
            if days_ago == 0:
                hints.append("last paradigm shift occurred today")
            elif days_ago == 1:
                hints.append("last paradigm shift was 1 day ago")
            else:
                hints.append(f"last paradigm shift was {days_ago} days ago")
        except (ValueError, TypeError):
            hints.append("last paradigm shift timestamp could not be parsed")
    else:
        hints.append("no paradigm shifts recorded since shift logging was enabled")

    # Evidence base size
    if evidence_count == 0:
        hints.append("no evidence has been ingested; scores reflect priors only")
    elif evidence_count < 10:
        hints.append(
            f"evidence base is small ({evidence_count} records); "
            "scores may not yet be reliable"
        )
    else:
        hints.append(f"evidence base: {evidence_count} records ingested")

    # Frontier
    if frontier_edges_out:
        hints.append(
            f"{len(frontier_edges_out)} edge(s) are in the explore band: "
            "causal structure is still being refined in these relations"
        )
    else:
        hints.append(
            "no edges are in the explore band: "
            "dominant causal structure is well-determined"
        )

    return NarrativeSnapshotOut(
        metadata=metadata,
        current_regime_state=regime_state,
        dominant_hypothesis=dominant_out,
        competing_candidates=competing_out,
        ontology_competition=ontology_out,
        frontier=frontier_out,
        interpretation_hints=hints,
    )
