"""Read-only bridge: load POE-A artifacts → old POE response payload dicts.

Serves the ``ontology_mode=dynamic`` view for the art domain.  All public
functions return plain dicts so app.py can construct Pydantic models via
``model_validate()`` without creating circular imports.

Artifact discovery order:
  1. POEA_ARTIFACTS_DIR env var (absolute path)
  2. Sibling repo: <suite-root>/probabilistic_ontology_engine_abductive/artifacts/
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_EXPLORE_LO = 0.3
_EXPLORE_HI = 0.7


# ── Artifact discovery ─────────────────────────────────────────────────────────

def _artifacts_dir() -> Path:
    env = os.environ.get("POEA_ARTIFACTS_DIR")
    if env:
        return Path(env)
    # this file → api/ → engine/ → src/ → probabilistic_ontology_engine/ → suite root
    here = Path(__file__).resolve()
    return here.parents[4] / "probabilistic_ontology_engine_abductive" / "artifacts"


def _art_artifact(name: str) -> Path:
    return _artifacts_dir() / name


# ── Low-level loaders ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_graph() -> dict[str, Any]:
    p = _art_artifact("poea_graph.json")
    return _load_json(p) if p.exists() else {}


def _load_canonical_concepts() -> dict[str, Any]:
    p = _art_artifact("canonical_concepts.json")
    return _load_json(p) if p.exists() else {"concepts": []}


def _load_scored_evidence() -> dict[str, Any]:
    p = _art_artifact("scored_evidence.json")
    return _load_json(p) if p.exists() else {"scored_records": [], "metadata": {}}


def _load_evidence() -> list[dict[str, Any]]:
    p = _art_artifact("evidence.json")
    return _load_json(p) if p.exists() else []


# ── Availability check ────────────────────────────────────────────────────────

def is_dynamic_available(domain_key: str) -> bool:
    """Dynamic artifacts exist only for the art domain."""
    return domain_key == "art" and _art_artifact("poea_graph.json").exists()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _time_ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - ts).total_seconds()
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff / 60)}m ago"
        if diff < 86400:
            return f"{int(diff / 3600)}h ago"
        return f"{int(diff / 86400)}d ago"
    except Exception:
        return "unknown"


def _compute_entropy(log_scores: list[float]) -> float:
    finite = [s for s in log_scores if math.isfinite(s)]
    if not finite:
        return 0.0
    max_s = max(finite)
    exps = [math.exp(s - max_s) for s in finite]
    total = sum(exps)
    if total == 0:
        return 0.0
    probs = [e / total for e in exps]
    return -sum(p * math.log(p + 1e-12) for p in probs)


def _normalize_log_scores(log_scores: list[float]) -> list[float]:
    finite = [s for s in log_scores if math.isfinite(s)]
    n = len(log_scores)
    if not finite or len(set(finite)) == 1:
        return [0.05 + 0.90 * (i / max(n - 1, 1)) for i in range(n)]
    min_s, max_s = min(finite), max(finite)
    result = []
    for s in log_scores:
        if not math.isfinite(s):
            result.append(0.05)
        else:
            result.append(0.05 + 0.90 * (s - min_s) / (max_s - min_s + 1e-12))
    return result


def _concept_confidence(name: str, concepts: list[dict[str, Any]]) -> float:
    for c in concepts:
        if c.get("name") == name:
            return float(c.get("confidence", 0.5))
    return 0.5


def _normalize_name(s: str) -> str:
    return s.lower().replace("_", "").replace("-", "").replace(" ", "")


def _fuzzy_find_concept(
    target: str, concepts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    t = _normalize_name(target)
    for c in concepts:
        n = _normalize_name(c.get("name", ""))
        if n == t or n.endswith(t) or t.endswith(n):
            return c
    return concepts[0] if concepts else None


# ── Public response builders ──────────────────────────────────────────────────

def build_population_status(display_name: str) -> dict[str, Any] | None:
    """Return dict compatible with PopStatusOut, or None if artifacts missing."""
    graph = _load_graph()
    if not graph:
        return None

    candidates = graph.get("candidate_summaries", [])
    population = graph.get("population", {})
    metadata = graph.get("metadata", {})
    edges = graph.get("edges", [])

    log_scores = [c.get("log_score", float("-inf")) for c in candidates]
    entropy = _compute_entropy(log_scores)

    dominant = candidates[0] if candidates else {}
    frontier_count = sum(
        1 for e in edges
        if _EXPLORE_LO <= e.get("existence_probability", 0.0) <= _EXPLORE_HI
    )

    return {
        "domain": display_name,
        "structure_entropy": entropy,
        "active_candidates": int(population.get("active_count", len(candidates))),
        "max_candidates": int(population.get("candidate_count", len(candidates))),
        "current_generation": int(metadata.get("evidence_count", 0)),
        "dominant_hypothesis": {
            "name": "POE-A Induced Dominant",
            "candidate_id": dominant.get("candidate_id", ""),
            "generations_dominant": 0,
        },
        "paradigm_shifts_this_window": 0,
        "frontier_edge_count": frontier_count,
        "last_evidence_cycle_ago": _time_ago(metadata.get("created_at")),
        "engine_status": "online",
    }


def build_candidates(display_name: str) -> dict[str, Any] | None:
    """Return dict compatible with CandidatesOut, or None if artifacts missing."""
    graph = _load_graph()
    if not graph:
        return None

    candidates = graph.get("candidate_summaries", [])
    metadata = graph.get("metadata", {})
    n = len(candidates)

    log_scores = [c.get("log_score", float("-inf")) for c in candidates]
    norm_scores = _normalize_log_scores(log_scores)

    out: list[dict[str, Any]] = []
    for i, (c, ns) in enumerate(zip(candidates, norm_scores)):
        if i == 0:
            status = "dominant"
        elif i < max(1, n // 3):
            status = "rising"
        elif i >= max(1, 2 * n // 3):
            status = "falling"
        else:
            status = "neutral"

        out.append({
            "id": c.get("candidate_id", ""),
            "name": f"POE-A Candidate {i + 1}",
            "log_score": float(c.get("log_score", 0.0)),
            "evidence_count": int(c.get("evidence_count", 0)),
            "generation_introduced": 0,
            "edge_count": int(c.get("active_edge_count", 0)),
            "status": status,
            "score_normalized": ns,
        })

    return {
        "domain": display_name,
        "generation": int(metadata.get("evidence_count", 0)),
        "candidates": out,
    }


def build_inference(target_variable: str) -> dict[str, Any] | None:
    """Return dict compatible with InferenceOut, or None if artifacts missing."""
    graph = _load_graph()
    if not graph:
        return None

    concepts = _load_canonical_concepts().get("concepts", [])
    candidates = graph.get("candidate_summaries", [])
    nodes_raw = graph.get("nodes", [])
    edges_raw = graph.get("edges", [])

    target_concept = _fuzzy_find_concept(target_variable, concepts)
    if target_concept is None:
        return None

    target_name = target_concept.get("name", target_variable)
    target_prob = _concept_confidence(target_name, concepts)
    dom_id = candidates[0].get("candidate_id", "") if candidates else ""

    out_nodes: list[dict[str, Any]] = []
    for node in nodes_raw:
        nname = node.get("name", "")
        max_ep = max(
            (
                e.get("existence_probability", 0.0)
                for e in edges_raw
                if e.get("parent") == nname or e.get("child") == nname
            ),
            default=0.0,
        )
        if nname == target_name:
            nstatus = "target"
        elif max_ep > _EXPLORE_HI:
            nstatus = "established"
        elif max_ep >= _EXPLORE_LO:
            nstatus = "exploring"
        else:
            nstatus = "weak"
        out_nodes.append({
            "id": nname,
            "label": nname,
            "probability": target_prob if nname == target_name else None,
            "observation": None,
            "status": nstatus,
        })

    out_edges: list[dict[str, Any]] = []
    out_frontier: list[dict[str, Any]] = []
    for e in edges_raw:
        ep = float(e.get("existence_probability", 0.0))
        src = e.get("parent", "")
        tgt = e.get("child", "")
        if ep > _EXPLORE_HI:
            estatus = "strong"
        elif ep >= _EXPLORE_LO:
            estatus = "explore"
        else:
            estatus = "weak"
        out_edges.append({"source": src, "target": tgt, "probability": ep, "status": estatus})
        if _EXPLORE_LO <= ep <= _EXPLORE_HI:
            out_frontier.append({
                "relation": f"{src}→{tgt}",
                "source": src,
                "target": tgt,
                "probability": ep,
                "note": (
                    f"existence_probability={ep:.3f} in explore band "
                    f"[{_EXPLORE_LO}, {_EXPLORE_HI}]"
                ),
                "explore_weight": None,
            })

    return {
        "candidate_id": dom_id,
        "target_variable": target_name,
        "target_probability": target_prob,
        "nodes": out_nodes,
        "edges": out_edges,
        "frontier_edges": out_frontier,
    }


def build_lineage(candidate_id: str, display_name: str) -> dict[str, Any] | None:
    """Return dict compatible with LineageOut, or None if candidate not found."""
    graph = _load_graph()
    if not graph:
        return None

    candidates = graph.get("candidate_summaries", [])
    metadata = graph.get("metadata", {})

    found = next((c for c in candidates if c.get("candidate_id") == candidate_id), None)
    if found is None:
        return None

    idx = candidates.index(found)
    events: list[dict[str, Any]] = [
        {
            "generation": 0,
            "event_type": "introduce",
            "description": (
                f"POE-A Candidate {idx + 1} induced from "
                f"{found.get('evidence_count', 0)} evidence records"
            ),
            "dominant_after": None,
        }
    ]
    if idx == 0:
        events.append({
            "generation": int(metadata.get("evidence_count", 0)),
            "event_type": "current",
            "description": "Current dominant induced candidate",
            "dominant_after": f"POE-A Candidate {idx + 1}",
        })

    return {"domain": display_name, "candidate_id": candidate_id, "events": events}


def build_shifts(display_name: str, domain_module_id: str) -> dict[str, Any]:
    """Return dict compatible with ParadigmShiftsOut (always empty for POE-A)."""
    return {
        "domain": display_name,
        "domain_module_id": domain_module_id,
        "total_shifts": 0,
        "events": [],
    }


def build_narrative_snapshot(display_name: str, domain_module_id: str) -> dict[str, Any] | None:
    """Return dict compatible with NarrativeSnapshotOut, or None if artifacts missing.

    Values sourced entirely from POE-A artifacts.  Concept 'probability' fields
    are LLM-derived support confidence scores, NOT posterior probabilities.
    interpretation_hints make this explicit.
    """
    graph = _load_graph()
    if not graph:
        return None

    concepts = _load_canonical_concepts().get("concepts", [])
    candidates = graph.get("candidate_summaries", [])
    population = graph.get("population", {})
    metadata = graph.get("metadata", {})
    nodes_raw = graph.get("nodes", [])
    edges_raw = graph.get("edges", [])

    evidence_count = int(metadata.get("evidence_count", 0))
    n = len(candidates)

    # ── metadata ──────────────────────────────────────────────────────────────
    meta_out = {
        "domain": display_name,
        "domain_module_id": domain_module_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evidence_count": evidence_count,
        "current_generation": evidence_count,
    }

    # ── current_regime_state: induced concepts with support confidence ─────────
    # These are NOT posterior probabilities. confidence is a concept support
    # score from LLM scoring during POE-A induction.
    concept_confidence_map = {
        c.get("name"): float(c.get("confidence", 0.5)) for c in concepts
    }
    regime_state: list[dict[str, Any]] = []
    for node in nodes_raw:
        name = node.get("name", "")
        confidence = concept_confidence_map.get(
            name, float(node.get("prior_probability", 0.5))
        )
        regime_state.append({
            "name": name,
            "boolean_state": node.get("boolean_state"),
            "probability": confidence,
        })

    # ── dominant_hypothesis ───────────────────────────────────────────────────
    dominant_out = None
    if candidates:
        dom = candidates[0]
        dom_edges = [
            {
                "source": e.get("parent", ""),
                "target": e.get("child", ""),
                "existence_probability": float(e.get("existence_probability", 0.0)),
            }
            for e in edges_raw
        ]
        dominant_out = {
            "name": "POE-A Candidate 1",
            "candidate_id": dom.get("candidate_id", ""),
            "edge_count": int(dom.get("active_edge_count", 0)),
            "edges": dom_edges,
            "generations_dominant": 0,
            "log_score": float(dom.get("log_score", 0.0)),
        }

    # ── competing_candidates ──────────────────────────────────────────────────
    log_scores = [c.get("log_score", float("-inf")) for c in candidates]
    norm_scores = _normalize_log_scores(log_scores)

    competitor_list: list[dict[str, Any]] = []
    for i, (c, ns) in enumerate(zip(candidates, norm_scores)):
        if i == 0:
            cstatus = "dominant"
        elif i < max(1, n // 3):
            cstatus = "rising"
        elif i >= max(1, 2 * n // 3):
            cstatus = "falling"
        else:
            cstatus = "neutral"
        competitor_list.append({
            "name": f"POE-A Candidate {i + 1}",
            "log_score": float(c.get("log_score", 0.0)),
            "edge_count": int(c.get("active_edge_count", 0)),
            "status": cstatus,
            "score_normalized": ns,
        })

    score_gap: float | None = None
    if len(log_scores) >= 2 and math.isfinite(log_scores[0]) and math.isfinite(log_scores[1]):
        score_gap = log_scores[0] - log_scores[1]

    competing_out = {
        "candidates": competitor_list,
        "score_gap_to_dominant": score_gap,
    }

    # ── ontology_competition ──────────────────────────────────────────────────
    entropy = _compute_entropy(log_scores)
    if entropy < 0.5:
        entropy_interp = "low"
    elif entropy < 1.5:
        entropy_interp = "medium"
    else:
        entropy_interp = "high"

    ontology_out = {
        "structure_entropy": entropy,
        "entropy_interpretation": entropy_interp,
        "active_candidates": int(population.get("active_count", n)),
        "paradigm_shifts_total": 0,
        "recent_shifts": [],
    }

    # ── frontier ──────────────────────────────────────────────────────────────
    frontier_edges: list[dict[str, Any]] = []
    for e in edges_raw:
        ep = float(e.get("existence_probability", 0.0))
        if _EXPLORE_LO <= ep <= _EXPLORE_HI:
            src = e.get("parent", "")
            tgt = e.get("child", "")
            frontier_edges.append({
                "source": src,
                "target": tgt,
                "probability": ep,
                "relation": f"{src}→{tgt}",
            })

    frontier_out = {
        "frontier_edge_count": len(frontier_edges),
        "frontier_edges": frontier_edges,
    }

    # ── interpretation_hints ──────────────────────────────────────────────────
    hints: list[str] = [
        "DYNAMIC MODE: snapshot reflects POE-A abductive induction artifacts, not old POE posterior inference",
        "probability values in current_regime_state are LLM-derived concept support scores, NOT posterior probabilities",
        f"ontology_mode=dynamic: {n} POE-A candidates induced from {evidence_count} evidence records",
    ]

    if entropy_interp == "low":
        hints.append(
            f"structure_entropy is low ({entropy:.3f}): "
            "induced candidates converge on similar causal structures"
        )
    elif entropy_interp == "medium":
        hints.append(
            f"structure_entropy is medium ({entropy:.3f}): "
            "induced candidate structures show moderate diversity"
        )
    else:
        hints.append(
            f"structure_entropy is high ({entropy:.3f}): "
            "induced candidates span diverse structural hypotheses"
        )

    if evidence_count == 0:
        hints.append("no evidence has been ingested into the dynamic pipeline")
    elif evidence_count < 10:
        hints.append(
            f"dynamic evidence base is small ({evidence_count} records); "
            "concept induction may be unreliable"
        )
    else:
        hints.append(
            f"dynamic evidence base: {evidence_count} records ingested into POE-A induction pipeline"
        )

    if frontier_edges:
        hints.append(
            f"{len(frontier_edges)} edge(s) in explore band [{_EXPLORE_LO}, {_EXPLORE_HI}]: "
            "causal structure is uncertain in these relations"
        )
    else:
        hints.append(
            "no edges in explore band: induced causal structure is either sparse or well-determined"
        )

    return {
        "metadata": meta_out,
        "current_regime_state": regime_state,
        "dominant_hypothesis": dominant_out,
        "competing_candidates": competing_out,
        "ontology_competition": ontology_out,
        "frontier": frontier_out,
        "interpretation_hints": hints,
    }


def build_recent_evidence(display_name: str, limit: int) -> dict[str, Any]:
    """Return dict compatible with EvidenceOut from scored POE-A evidence."""
    scored = _load_scored_evidence()
    evidence_units = _load_evidence()

    ev_lookup: dict[str, dict[str, Any]] = {
        e["evidence_id"]: e for e in evidence_units
    }

    scored_records: list[dict[str, Any]] = scored.get("scored_records", [])
    recent = scored_records[-limit:]

    records_out: list[dict[str, Any]] = []
    for rec in recent:
        eid = rec.get("evidence_id", "")
        ev_info = ev_lookup.get(eid, {})
        title = ev_info.get("title") or f"Evidence record {eid[:8]}"

        published = ev_info.get("published_at", "")
        try:
            dt = datetime.fromisoformat(published) if published else None
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamp = dt.isoformat() if dt else scored.get("metadata", {}).get("scored_at", "")
        except Exception:
            timestamp = scored.get("metadata", {}).get("scored_at", "")

        assignments: list[dict[str, Any]] = rec.get("assignments", [])
        observed = [
            a for a in assignments
            if a.get("missingness") in ("OBSERVED", "SOFT_OBSERVED")
        ]
        max_confidence = max((a.get("confidence", 0.0) for a in observed), default=0.0)

        if max_confidence > 0.8:
            strength = "strong"
        elif max_confidence > 0.4:
            strength = "shift"
        else:
            strength = "weak"

        records_out.append({
            "id": eid,
            "timestamp": timestamp,
            "description": title,
            "impact_delta": max_confidence,
            "strength": strength,
            "variables_updated": len(observed) if observed else None,
        })

    return {"domain": display_name, "records": records_out}
