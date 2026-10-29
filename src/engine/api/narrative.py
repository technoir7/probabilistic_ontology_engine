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
from ..model.trends import TrendLists
from ..runtime.cases import compute_case_reports
from ..runtime.trends import current_trends
from ..services.cases import CaseReport
from ..model.scoring import candidate_score
from ..schemas import InferenceQuery, PopulationAggregation, QueryType
from . import context, presenters
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
    NarrativeCaseForecastOut,
    NarrativeCaseMechanismOut,
    NarrativeCaseSetOut,
    NarrativeTrendOut,
    NarrativeTrendsOut,
)

FORECAST_ROWS = 5
CASES_HINT = (
    "this domain is judged by cases: its monthly totals show no lasting links, so the hypotheses, "
    "competing candidates and frontier above are a search that has found nothing. Lead the report "
    "with case_mechanisms: what the leading mechanism predicts for each kind of "
    "case, its evidence over each case's own past (gain_nats; 3 is strong), which mechanisms failed "
    "(negative gain), when the belief changed, and the cases the leader makes more likely next year"
)


TRENDS_HINT = (
    "trends lists the broad ideas critics wrote about this year: new ones, growing, fading, and the most "
    "argued over (critics split between approval and disapproval). They describe the present, not a "
    "forecast: in case_mechanisms, no sign in how critics write about a trend has predicted whether it "
    "grows. Say what the trends are, in plain words"
)
TREND_ROWS = 8


def snapshot_for(state: Any, domain: str) -> NarrativeSnapshotOut:
    """The snapshot for a domain key."""
    engine, domain_id, display_name = context.resolve_domain(domain, state)
    key = domain.lower()
    return build_snapshot(engine, domain_id, display_name, compute_case_reports(key), current_trends(key))


def _trends(t: TrendLists) -> NarrativeTrendsOut:
    def row(x) -> NarrativeTrendOut:
        return NarrativeTrendOut(
            trend=x.name, broad_since=x.start, writers_this_year=x.writers[t.years.index(t.year)],
            share_this_year_pct=round(100 * t.share(x.key, t.year), 2),
            share_before_pct=round(100 * t.share_before(x.key), 2),
            papers=list(x.papers), approvals=x.verdicts[0], disapprovals=x.verdicts[1])

    def rows(name: str) -> list[NarrativeTrendOut]:
        return [row(x) for x in t.listed(name)[:TREND_ROWS]]

    return NarrativeTrendsOut(
        period=f"October {t.year - 1} to September {t.year}",
        compared_with=f"the {t.before} years to September before",
        note="writers are critics; a share is of every critic writing in either paper that year",
        new=rows("new"), growing=rows("growing"), fading=rows("fading"), argued_over=rows("argued"))


def _case_set(r: CaseReport) -> NarrativeCaseSetOut:
    since = r.shifts[-1].year + 1 if r.shifts else (r.years[0].year if r.years else None)
    return NarrativeCaseSetOut(
        title=r.title, outcome=r.outcome, leader=r.describe(r.leader), leader_since=since,
        gain_nats_over_own_past=round(r.gain, 1),
        mechanisms=[NarrativeCaseMechanismOut(mechanism=r.describe(m.features), gain_nats=round(m.gain, 1))
                    for m in r.mechanisms],
        belief_changes=[f"from {s.year + 1}: {r.describe(s.to)}" for s in r.shifts],
        forecast_for=r.forecast_year + 1 if r.forecast_year is not None else None,
        most_raised=[NarrativeCaseForecastOut(case=f.label, own_past_chance=round(1 - f.own_past[0], 3),
                                              with_leader_chance=round(1 - f.with_leader[0], 3))
                     for f in r.most_raised[:FORECAST_ROWS]],
    )


def build_snapshot(
    engine: ProbabilisticOntologyEngine, domain_id: str, display_name: str,
    case_reports: tuple[CaseReport, ...] = (),
    trends: Optional[TrendLists] = None,
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
    # Matches RegimeStatePanel: call inference for each variable and read its
    # posterior (presenters.reading) rather than the raw evidence.
    regime_state: list[NarrativeRegimeVariableOut] = []
    # The regime is this period's signals; last period's are inputs (D19).
    variables = [v for v in pop.candidates[0].variables if not v.lag_of] if pop.candidates else []

    if evidence_count == 0 or not variables:
        # No evidence yet — list variables as unobserved so the LLM knows
        # that scores are prior-only.
        for v in variables:
            regime_state.append(NarrativeRegimeVariableOut(
                name=v.name, level=None, degree=None
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
            level, degree = presenters.reading(dist, v)
            regime_state.append(NarrativeRegimeVariableOut(name=v.name, level=level, degree=degree))

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
        gens_dominant = engine.generations_led(domain_id)
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
            evidence_date=ev["evidence_ts"][:10] if ev["evidence_ts"] else None,
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

    if case_reports:
        hints.append(CASES_HINT)
    if trends is not None:
        hints.append(TRENDS_HINT)

    return NarrativeSnapshotOut(
        metadata=metadata,
        current_regime_state=regime_state,
        dominant_hypothesis=dominant_out,
        competing_candidates=competing_out,
        ontology_competition=ontology_out,
        frontier=frontier_out,
        interpretation_hints=hints,
        case_mechanisms=[_case_set(r) for r in case_reports],
        trends=_trends(trends) if trends is not None else None,
    )
