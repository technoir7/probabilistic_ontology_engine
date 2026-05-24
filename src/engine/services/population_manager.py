"""
PopulationManager — Level 3 belief management.  Novel component.

Responsibilities:
  - Maintains OntologyPopulation for each active domain.
  - Scores candidates after each learning cycle.
  - Introduces new candidates as variants of high-scoring survivors.
  - Prunes low-scoring candidates (bottom quartile after min evidence).
  - Enforces max_population_size.
  - Tracks dominant (highest-scoring) candidate.
  - Tracks paradigm_shift_count.
"""
from __future__ import annotations

import copy
import math
import random
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import networkx as nx

from ..schemas import (
    CandidateStatus,
    DependencyEdge,
    DependencyKind,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
    OntologyPopulation,
    Variable,
)
from ..stores.parameter_store import ParameterStore
from ..stores.population_store import PopulationStore


# Minimum number of batches before pruning is considered
_MIN_BATCHES_FOR_PRUNING = 3


class PopulationManager:

    def __init__(
        self,
        parameter_store: ParameterStore,
        population_store: PopulationStore,
        thresholds: EdgeExistenceThresholdConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.ps = parameter_store
        self.pop_store = population_store
        self.thresholds = thresholds or EdgeExistenceThresholdConfig()
        self.rng = rng or random.Random(42)

        # In-memory populations: {domain_module_id: OntologyPopulation}
        self._populations: dict[str, OntologyPopulation] = {}
        # Admissible edge pairs per domain: {domain_id: set of (parent_name, child_name)}
        self._admissible_edges: dict[str, set[tuple[str, str]]] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(
        self,
        domain_module_id: str,
        initial_candidates: list[OntologyCandidate],
        max_population_size: int = 10,
        admissible_edges: set[tuple[str, str]] | None = None,
        thresholds: EdgeExistenceThresholdConfig | None = None,
    ) -> OntologyPopulation:
        if thresholds:
            self.thresholds = thresholds

        pop = OntologyPopulation(
            domain_module_id=domain_module_id,
            max_population_size=max_population_size,
            candidates=list(initial_candidates),
        )
        pop.update_dominant()
        self._populations[domain_module_id] = pop
        self._admissible_edges[domain_module_id] = admissible_edges or set()
        self.pop_store.save_population(pop)
        for c in initial_candidates:
            self.pop_store.save_candidate(c)
        return pop

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_population(self, domain_module_id: str) -> OntologyPopulation:
        return self._populations[domain_module_id]

    def dominant(self, domain_module_id: str) -> OntologyCandidate | None:
        """Return highest average-score active candidate (fair to late-arrivals)."""
        pop = self._populations[domain_module_id]
        active = pop.active_candidates()
        if not active:
            return None
        return max(active, key=lambda c: self._avg_score(c))

    def dominant_matches_structure(
        self, domain_module_id: str, target_signature: frozenset[tuple[str, str]]
    ) -> bool:
        dom = self.dominant(domain_module_id)
        if dom is None:
            return False
        return dom.edge_structure_signature() == target_signature

    def summary(self, domain_module_id: str) -> dict:
        return self._populations[domain_module_id].summary()

    # ------------------------------------------------------------------
    # Score update
    # ------------------------------------------------------------------

    def update_score(
        self,
        domain_module_id: str,
        candidate_id: UUID,
        log_likelihood: float,
        batch_index: int = 0,
        batch_size: int = 1,
    ) -> None:
        pop = self._populations[domain_module_id]
        for c in pop.candidates:
            if c.candidate_id == candidate_id:
                c.log_score += log_likelihood
                c.evidence_count += batch_size   # count actual records
                self.pop_store.update_score(c.candidate_id, c.log_score, c.evidence_count)
                self.pop_store.append_score_record(c.candidate_id, log_likelihood, batch_index)
                break

    def _avg_score(self, candidate: OntologyCandidate) -> float:
        """
        BIC-corrected average log-likelihood (for fair cross-candidate comparison).

        BIC = log_lik - 0.5 * k * log(N)
        where k = total free parameters in the model.

        For BOOLEAN variables with boolean parents:
          free_params_per_var = 2^(num_parents)

        We count ALL edges (including disabled/pruned ones) when computing k.
        This penalizes candidates that explored extra edges even if later pruned,
        preventing warm-started variants from gaming the score by adding then
        pruning spurious edges.
        """
        n = candidate.evidence_count
        if n == 0:
            return float("-inf")
        avg_ll = candidate.log_score / n
        # Count total free parameters — include disabled edges in parent count
        k = 0
        for v in candidate.variables:
            n_parents = sum(
                1 for e in candidate.edges
                if e.child_variable_id == v.variable_id
            )
            k += 2 ** n_parents
        bic_penalty = 0.5 * k * math.log(max(n, 2)) / n
        return avg_ll - bic_penalty

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune_low_scorers(self, domain_module_id: str) -> list[OntologyCandidate]:
        """
        Mark bottom-quartile candidates as PRUNED if they have accumulated
        enough evidence.  Returns list of pruned candidates.
        """
        pop = self._populations[domain_module_id]
        active = pop.active_candidates()
        if len(active) < 2:
            return []

        # Only prune if enough evidence processed (at least 3 batches of any candidate)
        if not any(c.evidence_count >= _MIN_BATCHES_FOR_PRUNING for c in active):
            return []

        # Rank by average score (fair across candidates with different evidence counts)
        ranked = sorted(active, key=lambda c: self._avg_score(c))
        n_prune = max(1, len(active) // 4)

        pruned = []
        for c in ranked[:n_prune]:
            # Don't prune the dominant candidate
            if c.candidate_id == pop.active_candidate_id:
                continue
            c.status = CandidateStatus.PRUNED
            c.pruned_at = datetime.utcnow()
            c.pruning_reason = "bottom_quartile_log_score"
            self.pop_store.mark_pruned(c.candidate_id, c.pruning_reason)
            pruned.append(c)

        return pruned

    # ------------------------------------------------------------------
    # Variant introduction
    # ------------------------------------------------------------------

    def introduce_variants(
        self,
        domain_module_id: str,
        learning_service=None,
    ) -> list[OntologyCandidate]:
        """
        Introduce new candidates as variants of the top survivors.
        Variants are: add one edge OR remove one edge.
        All variants must be valid DAGs.
        Population is kept bounded at max_population_size.
        """
        pop = self._populations[domain_module_id]
        active = pop.active_candidates()

        slots = pop.max_population_size - len(active)
        if slots <= 0:
            return []

        # Sort survivors by score (best first)
        survivors = sorted(active, key=lambda c: c.log_score, reverse=True)
        admissible = self._admissible_edges.get(domain_module_id, set())

        new_candidates: list[OntologyCandidate] = []
        attempts = 0
        max_attempts = slots * 10

        while len(new_candidates) < slots and attempts < max_attempts:
            attempts += 1
            parent_cand = survivors[attempts % len(survivors)]
            variant = self._make_variant(domain_module_id, parent_cand, admissible)
            if variant is None:
                continue
            if not variant.is_dag():
                continue
            # Avoid duplicates
            sig = variant.edge_structure_signature()
            existing_sigs = {c.edge_structure_signature() for c in active + new_candidates}
            if sig in existing_sigs:
                continue

            pop.candidates.append(variant)
            pop.generation += 1
            self.pop_store.save_candidate(variant)

            # Initialize CPTs for the new candidate (clone from parent)
            self.ps.clone_candidate(parent_cand.candidate_id, variant.candidate_id)

            # If learning_service provided, re-initialize new edges
            if learning_service is not None:
                for var in variant.variables:
                    parent_vars = variant.get_parents(var.variable_id)
                    parent_names = sorted(pv.name for pv in parent_vars)
                    old_parents = (
                        self.ps.get(variant.candidate_id, var.name).parents
                        if self.ps.has(variant.candidate_id, var.name)
                        else []
                    )
                    if set(parent_names) != set(old_parents):
                        self.ps.update_parents(variant.candidate_id, var.name, parent_names)

            new_candidates.append(variant)

        return new_candidates

    def _make_variant(
        self,
        domain_module_id: str,
        parent: OntologyCandidate,
        admissible: set[tuple[str, str]],
    ) -> OntologyCandidate | None:
        """Create one structural variant of `parent` by add/remove one edge."""
        strategy = self.rng.choice(["add", "remove"])
        active_edges = parent.get_active_edges()
        edge_sigs = {
            (
                parent.get_variable_by_id(e.parent_variable_id).name,
                parent.get_variable_by_id(e.child_variable_id).name,
            )
            for e in active_edges
            if parent.get_variable_by_id(e.parent_variable_id)
            and parent.get_variable_by_id(e.child_variable_id)
        }

        if strategy == "remove" and not active_edges:
            strategy = "add"
        if strategy == "add" and admissible:
            # Pick a random admissible edge not currently present.
            # Sort to ensure deterministic order regardless of PYTHONHASHSEED.
            candidates_to_add = sorted(admissible - edge_sigs)
            if not candidates_to_add:
                strategy = "remove"

        # Clone the parent candidate
        variant_id = uuid4()
        variant_edges = [
            DependencyEdge(
                edge_id=uuid4(),
                parent_variable_id=e.parent_variable_id,
                child_variable_id=e.child_variable_id,
                dependency_kind=e.dependency_kind,
                existence_prior=e.existence_prior,
                existence_probability=e.existence_probability,
                existence_update_count=e.existence_update_count,
                explore_weight=e.explore_weight,
                explanatory_label=e.explanatory_label,
                learnable=e.learnable,
                enabled=e.enabled,
            )
            for e in parent.edges
        ]

        if strategy == "add" and admissible:
            candidates_to_add = sorted(admissible - edge_sigs)
            if not candidates_to_add:
                return None
            pname, cname = self.rng.choice(candidates_to_add)
            pvar = parent.get_variable_by_name(pname)
            cvar = parent.get_variable_by_name(cname)
            if pvar is None or cvar is None:
                return None
            new_edge = DependencyEdge(
                edge_id=uuid4(),
                parent_variable_id=pvar.variable_id,
                child_variable_id=cvar.variable_id,
                dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
                existence_prior=0.5,
                existence_probability=0.5,
                learnable=True,
                enabled=True,
            )
            variant_edges.append(new_edge)
            description = f"variant_add_{pname}->{cname}"
        elif strategy == "remove" and active_edges:
            # Pick a random active edge to remove
            edge_to_remove = self.rng.choice(active_edges)
            variant_edges = [
                e for e in variant_edges if e.edge_id != edge_to_remove.edge_id
            ]
            pvar = parent.get_variable_by_id(edge_to_remove.parent_variable_id)
            cvar = parent.get_variable_by_id(edge_to_remove.child_variable_id)
            pname = pvar.name if pvar else "?"
            cname = cvar.name if cvar else "?"
            description = f"variant_remove_{pname}->{cname}"
        else:
            return None

        # Warm-start: inherit parent's score history so cross-candidate
        # comparison is fair.  Future batches will differentiate the variant.
        variant = OntologyCandidate(
            candidate_id=variant_id,
            domain_module_id=domain_module_id,
            generation=parent.generation + 1,
            parent_candidate_id=parent.candidate_id,
            variables=parent.variables,  # shared; immutable at engine level
            edges=variant_edges,
            log_score=parent.log_score,
            evidence_count=parent.evidence_count,
            status=CandidateStatus.ACTIVE,
            description=description,
        )
        return variant

    # ------------------------------------------------------------------
    # Post-cycle bookkeeping
    # ------------------------------------------------------------------

    def end_cycle(self, domain_module_id: str) -> dict:
        """
        Call at end of each learning cycle:
          1. Update dominant candidate.
          2. Save population metadata.
        Returns summary dict.
        """
        pop = self._populations[domain_module_id]
        pop.update_dominant()
        self.pop_store.save_population(pop)
        return pop.summary()
