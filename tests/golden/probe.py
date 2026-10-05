"""
Adapters that read engine state for golden tests.

This is the only golden-test module that touches engine APIs. When a refactor
step renames or moves something (e.g. CPTData leaves the parameter store, or
ProbabilisticOntologyEngine becomes DomainEngine), update these functions so
they return the same data; the snapshots must stay byte-identical.
"""
from __future__ import annotations

from itertools import product
from typing import Any

from src.engine.schemas import (
    EvidenceRecord,
    InferenceQuery,
    MissingnessType,
    ObservedAssignment,
    OntologyCandidate,
    PopulationAggregation,
)


def edge_label(cand: OntologyCandidate, edge) -> str:
    parent = cand.get_variable_by_id(edge.parent_variable_id)
    child = cand.get_variable_by_id(edge.child_variable_id)
    return f"{parent.name}->{child.name}"


def signature(cand: OntologyCandidate) -> list[str]:
    return sorted(f"{p}->{c}" for p, c in cand.edge_structure_signature())


def candidate_state(cand: OntologyCandidate) -> dict[str, Any]:
    return {
        "description": cand.description,
        "generation": cand.generation,
        "status": cand.status.value,
        "pruning_reason": cand.pruning_reason,
        "log_score": cand.log_score,
        "evidence_count": cand.evidence_count,
        "active_signature": signature(cand),
        "edges": {
            edge_label(cand, e): {
                "enabled": e.enabled,
                "existence_probability": e.existence_probability,
                "existence_update_count": e.existence_update_count,
                "explore_weight": e.explore_weight,
            }
            for e in cand.edges
        },
    }


def candidate_brief(cand: OntologyCandidate) -> list[Any]:
    return [
        cand.description, cand.status.value, cand.log_score, cand.evidence_count,
        ",".join(signature(cand)),
    ]


def population_state(engine, domain_id: str, *, detail: bool = False) -> dict[str, Any]:
    """Per-batch summary; ``detail=True`` adds every edge of every candidate."""
    pop = engine.get_population(domain_id)
    summary = pop.summary()
    dom = pop.dominant()
    state = {
        "generation": pop.generation,
        "paradigm_shift_count": pop.paradigm_shift_count,
        "active_candidates": summary["active_candidates"],
        "structure_entropy": summary["structure_entropy"],
        "dominant_signature": signature(dom) if dom else None,
        "mutation_stats": engine.population_manager.last_mutation_stats(domain_id),
        # Population order is append order, which is deterministic.
        "candidates": [
            candidate_state(c) if detail else candidate_brief(c) for c in pop.candidates
        ],
    }
    return state


def cpt_table(engine, cand: OntologyCandidate) -> dict[str, dict[str, float]]:
    """P(var=True | parents) for every parent configuration, read through the CPT API."""
    ps = engine.parameter_store
    supports = {v.name: v.support for v in cand.variables}
    table: dict[str, dict[str, float]] = {}
    for var in cand.variables:
        if not ps.has(cand.candidate_id, var.name):
            continue
        cpt = ps.get(cand.candidate_id, var.name)
        rows = {}
        for combo in product(*(supports[p] for p in cpt.parents)):
            assignment = dict(zip(cpt.parents, combo))
            key = ",".join(f"{p}={v}" for p, v in assignment.items()) or "()"
            rows[key] = cpt.get_probability(True, assignment)
        table[var.name] = rows
    return table


def marginals(engine, domain_id: str, aggregation: PopulationAggregation) -> dict[str, Any]:
    pop = engine.get_population(domain_id)
    names = [v.name for v in pop.candidates[0].variables]
    result = engine.query(InferenceQuery(
        domain_module_id=domain_id,
        target_variables=names,
        population_aggregation=aggregation,
    ))
    return {"posteriors": result.get("posteriors"), "error": result.get("error")}


def to_soft(record: EvidenceRecord, confidence: float = 0.85) -> EvidenceRecord:
    """Turn hard observations into soft ones, the way live domains report evidence."""
    assignments = []
    for a in record.observed_assignments:
        if a.missingness != MissingnessType.OBSERVED:
            assignments.append(a)
            continue
        p_true = confidence if a.observed_value else 1.0 - confidence
        assignments.append(ObservedAssignment(
            variable_id=a.variable_id,
            observed_value=a.observed_value,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: p_true, False: round(1.0 - p_true, 10)},
        ))
    return record.model_copy(update={"observed_assignments": assignments})
