"""
Structure-learning diagnostics.

Provides ``build_structure_diagnostics()`` — a pure, synchronous function that
produces a per-candidate breakdown of:

  * edge structure
  * raw average log-likelihood (avg_ll = log_score / evidence_count)
  * strict BIC score   (avg_ll − penalty × 1.00)
  * explore BIC score  (avg_ll − penalty × 0.25)
  * mutation-cycle diagnostics from the most recent introduce_variants() call

The function is backend-only and has no side effects.  It is called by the
``GET /v1/debug/structure`` FastAPI endpoint.

Why two BIC columns?
--------------------
The BIC penalty at small N is large enough to suppress richer graph structures
even when they fit the data better.  By showing both columns side-by-side the
operator can distinguish:
  (a) genuine sparsity — explore score also prefers the simpler graph, and
  (b) over-regularisation — explore score would prefer a denser graph, but
      strict BIC suppresses it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..schemas import OntologyCandidate, OntologyPopulation


# ---------------------------------------------------------------------------
# Dataclasses (plain Python — NOT Pydantic — so they stay out of the ORM layer)
# ---------------------------------------------------------------------------

@dataclass
class CandidateDiagnostic:
    candidate_id: str
    description: str
    generation: int
    status: str                          # "ACTIVE" | "PRUNED" | "ARCHIVED"
    edge_structure: list[tuple[str, str]]  # sorted (parent, child) name pairs
    active_edge_count: int
    total_edge_count: int                # includes disabled edges
    evidence_count: int
    log_score: float

    # Score decomposition
    avg_ll: float                        # log_score / evidence_count (or -inf)
    bic_penalty_raw: float               # 0.5 * k * log(N) / N  (before multiplier)
    bic_score_strict: float              # avg_ll - bic_penalty_raw * 1.00
    bic_score_explore: float             # avg_ll - bic_penalty_raw * 0.25

    is_dominant: bool


@dataclass
class MutationCycleDiagnostic:
    total_attempts: int
    dag_violations: int
    duplicate_rejections: int
    introduced: int


@dataclass
class StructureDiagnostics:
    domain_module_id: str

    # Environment / config context
    env_mode: str                        # "strict" | "explore" from POE_STRUCTURE_MODE
    env_bic_multiplier: float            # the explore multiplier from config

    total_evidence_records: int
    candidates: list[CandidateDiagnostic]
    last_mutation_cycle: MutationCycleDiagnostic


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_structure_diagnostics(
    *,
    pop: OntologyPopulation,
    mutation_stats: dict[str, int],
    total_evidence_records: int,
    env_mode: str,
    env_bic_multiplier: float,
) -> StructureDiagnostics:
    """
    Compute structure-learning diagnostics for a population.

    Parameters
    ----------
    pop
        The ``OntologyPopulation`` to analyse.
    mutation_stats
        Output of ``PopulationManager.last_mutation_stats(domain_id)``.
        May be empty if no learning cycle has run yet.
    total_evidence_records
        Count from ``EvidenceStore.count(domain_id)``.
    env_mode
        ``"strict"`` or ``"explore"`` — from ``get_structure_mode_config()``.
    env_bic_multiplier
        The ``bic_penalty_multiplier`` from ``get_structure_mode_config()``.
    """
    dom = pop.dominant()
    dom_id = dom.candidate_id if dom else None

    candidate_diags: list[CandidateDiagnostic] = []

    for c in pop.candidates:
        cd = _candidate_diagnostic(c, is_dominant=(c.candidate_id == dom_id))
        candidate_diags.append(cd)

    # Sort: active first, then by bic_score_strict descending
    candidate_diags.sort(
        key=lambda cd: (
            0 if cd.status == "ACTIVE" else 1,
            -cd.bic_score_strict if math.isfinite(cd.bic_score_strict) else float("inf"),
        )
    )

    mut = MutationCycleDiagnostic(
        total_attempts=mutation_stats.get("total_attempts", 0),
        dag_violations=mutation_stats.get("dag_violations", 0),
        duplicate_rejections=mutation_stats.get("duplicate_rejections", 0),
        introduced=mutation_stats.get("introduced", 0),
    )

    return StructureDiagnostics(
        domain_module_id=pop.domain_module_id,
        env_mode=env_mode,
        env_bic_multiplier=env_bic_multiplier,
        total_evidence_records=total_evidence_records,
        candidates=candidate_diags,
        last_mutation_cycle=mut,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _candidate_diagnostic(
    c: OntologyCandidate,
    *,
    is_dominant: bool,
) -> CandidateDiagnostic:
    """Compute per-candidate BIC decomposition and edge summary."""
    n = c.evidence_count

    # Use -1e300 / 1e300 as JSON-safe sentinels for "no data / undefined".
    # Python's float("-inf") would serialise to JSON null which loses information.
    _NO_DATA_LL    = -1e300
    _NO_DATA_PEN   =  1e300

    # Raw average log-likelihood
    if n == 0:
        avg_ll = _NO_DATA_LL
    else:
        avg_ll = c.log_score / n

    # k = total free parameters (ALL edges, including disabled)
    k = 0
    for v in c.variables:
        n_parents = sum(1 for e in c.edges if e.child_variable_id == v.variable_id)
        k += 2 ** n_parents

    # BIC penalty before multiplier
    if n > 0:
        bic_penalty_raw = 0.5 * k * math.log(max(n, 2)) / n
    else:
        bic_penalty_raw = _NO_DATA_PEN

    bic_score_strict = (
        avg_ll - bic_penalty_raw * 1.00
        if avg_ll > _NO_DATA_LL and bic_penalty_raw < _NO_DATA_PEN
        else _NO_DATA_LL
    )
    bic_score_explore = (
        avg_ll - bic_penalty_raw * 0.25
        if avg_ll > _NO_DATA_LL and bic_penalty_raw < _NO_DATA_PEN
        else _NO_DATA_LL
    )

    # Edge structure (names, sorted, active edges only)
    active_edge_pairs: list[tuple[str, str]] = []
    for e in c.get_active_edges():
        pv = c.get_variable_by_id(e.parent_variable_id)
        cv = c.get_variable_by_id(e.child_variable_id)
        if pv and cv:
            active_edge_pairs.append((pv.name, cv.name))
    active_edge_pairs.sort()

    return CandidateDiagnostic(
        candidate_id=str(c.candidate_id),
        description=c.description or "",
        generation=c.generation,
        status=c.status.value,
        edge_structure=active_edge_pairs,
        active_edge_count=len(active_edge_pairs),
        total_edge_count=len(c.edges),
        evidence_count=n,
        log_score=c.log_score,
        avg_ll=avg_ll,
        bic_penalty_raw=bic_penalty_raw,
        bic_score_strict=bic_score_strict,
        bic_score_explore=bic_score_explore,
        is_dominant=is_dominant,
    )
