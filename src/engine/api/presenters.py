"""
View logic: how engine state is labelled and scaled for the dashboard.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import UUID

from ..engine import ProbabilisticOntologyEngine
from ..model.scoring import candidate_score
from ..schemas import OntologyCandidate
from . import context
from .dto import (
    DominantHypothesis,
    PopStatusOut,
)


def find_variable_fuzzy(cand: OntologyCandidate, raw_name: str):
    """
    Case/separator-insensitive lookup; suffix matching handles the frontend
    hardcoding 'price_up' for all domains (matches 'CornPriceUp', 'SoyPriceUp', etc.).
    """
    normalized = raw_name.lower().replace("_", "").replace("-", "").replace(" ", "")
    # Exact normalised match
    for v in cand.variables:
        if v.name.lower().replace("_", "").replace("-", "") == normalized:
            return v
    # Suffix match
    for v in cand.variables:
        if v.name.lower().replace("_", "").replace("-", "").endswith(normalized):
            return v
    return None


def time_ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = (context.utcnow() - ts).total_seconds()
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff / 60)}m ago"
        if diff < 86400:
            return f"{int(diff / 3600)}h ago"
        return f"{int(diff / 86400)}d ago"
    except (ValueError, TypeError):
        return "unknown"


def normalize_scores(
    candidates: list[OntologyCandidate],
    avg_fn: Callable[[OntologyCandidate], float],
) -> dict[UUID, float]:
    """Map candidate_id → score in [0.05, 0.95]."""
    scored = [(c.candidate_id, avg_fn(c)) for c in candidates]
    finite_vals = [s for _, s in scored if math.isfinite(s)]
    if not finite_vals or len(set(finite_vals)) == 1:
        # Rank-based when all equal or all -inf
        ranked = sorted(candidates, key=lambda c: avg_fn(c))
        n = len(ranked)
        return {
            c.candidate_id: 0.05 + 0.90 * (i / max(n - 1, 1))
            for i, c in enumerate(ranked)
        }
    min_s, max_s = min(finite_vals), max(finite_vals)
    result: dict[UUID, float] = {}
    for cid, s in scored:
        if not math.isfinite(s):
            result[cid] = 0.05
        else:
            result[cid] = 0.05 + 0.90 * (s - min_s) / (max_s - min_s)
    return result


def edge_status_label(
    prob: float, explore_lo: float, explore_hi: float
) -> Literal["strong", "explore", "weak"]:
    if prob > explore_hi:
        return "strong"
    if prob >= explore_lo:
        return "explore"
    return "weak"


def node_status_label(
    var_name: str,
    target_var_name: str,
    cand: OntologyCandidate,
    explore_lo: float,
    explore_hi: float,
) -> Literal["established", "exploring", "weak", "target"]:
    if var_name == target_var_name:
        return "target"
    var = cand.get_variable_by_name(var_name)
    if var is None:
        return "weak"
    max_ep = max(
        (
            e.existence_probability
            for e in cand.get_active_edges()
            if e.parent_variable_id == var.variable_id
            or e.child_variable_id == var.variable_id
        ),
        default=0.0,
    )
    if max_ep > explore_hi:
        return "established"
    if max_ep >= explore_lo:
        return "exploring"
    return "weak"


def build_population_status(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    display_name: str,
) -> PopStatusOut:
    pop = engine.get_population(domain_id)
    summary = pop.summary()
    dom = pop.dominant()

    thresholds = engine.thresholds(domain_id)
    explore_lo, explore_hi = thresholds.explore_band
    frontier_count = 0
    if dom:
        for edge in dom.get_active_edges():
            if explore_lo <= edge.existence_probability <= explore_hi:
                frontier_count += 1

    last_ts = engine.evidence_store.latest_timestamp(domain_id)

    dom_name = (dom.description or "Hypothesis A") if dom else "none"
    dom_cid = str(dom.candidate_id) if dom else ""
    gens_dominant = engine.generations_led(domain_id) if dom else 0

    return PopStatusOut(
        domain=display_name,
        structure_entropy=summary["structure_entropy"],
        active_candidates=summary["active_candidates"],
        max_candidates=pop.max_population_size,
        current_generation=pop.generation,
        dominant_hypothesis=DominantHypothesis(
            name=dom_name,
            candidate_id=dom_cid,
            generations_dominant=gens_dominant,
        ),
        paradigm_shifts_this_window=pop.paradigm_shift_count,
        frontier_edge_count=frontier_count,
        last_evidence_cycle_ago=time_ago(last_ts),
        engine_status="online",
    )


CandidateLabel = Literal["dominant", "rising", "falling", "neutral"]


def ranked_candidates(
    candidates: list[OntologyCandidate], dominant_id: UUID | None
) -> list[tuple[OntologyCandidate, CandidateLabel]]:
    """
    Best first by candidate_score, each labelled for the dashboard: the top
    third "rising", the bottom third "falling" (candidates with evidence only).
    """
    ranked = sorted(candidates, key=candidate_score, reverse=True)
    n = len(ranked)
    out: list[tuple[OntologyCandidate, CandidateLabel]] = []
    for i, c in enumerate(ranked):
        label: CandidateLabel
        if c.candidate_id == dominant_id:
            label = "dominant"
        elif i < max(1, n // 3) and c.evidence_count > 0:
            label = "rising"
        elif i >= max(1, 2 * n // 3) and c.evidence_count > 0:
            label = "falling"
        else:
            label = "neutral"
        out.append((c, label))
    return out


def candidate_name(c: OntologyCandidate) -> str:
    return c.description or f"Candidate {str(c.candidate_id)[:8]}"


def p_true(dist: dict) -> float:
    """P(True) from a posterior keyed by str(value); the first value for non-boolean variables."""
    return float(dist.get("True", dist.get("true", next(iter(dist.values()), 0.5))))
