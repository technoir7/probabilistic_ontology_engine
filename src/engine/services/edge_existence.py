"""
EdgeExistenceService — Level 2 belief update.

Uses the BIC (Bayesian Information Criterion) score to compare a model
with an edge vs. without it.  BIC penalizes extra parameters logarithmically,
providing an Occam's razor effect that correctly rejects spurious edges.

Update rule:
    log_lr  = BIC(X, Pa_with_Y) - BIC(X, Pa_without_Y)
    log_odds = logit(existence_prior) + log_lr   [using cumulative counts]
    existence_probability = sigmoid(log_odds)

Explore weight decays as existence_probability converges toward 0 or 1.
"""
from __future__ import annotations

import math
from uuid import UUID

from ..schemas import DependencyEdge, EdgeExistenceThresholdConfig, OntologyCandidate
from ..stores.parameter_store import ParameterStore


def _sigmoid(x: float) -> float:
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = max(1e-9, min(1 - 1e-9, p))
    return math.log(p / (1.0 - p))


class EdgeExistenceService:

    def __init__(
        self,
        parameter_store: ParameterStore,
        thresholds: EdgeExistenceThresholdConfig | None = None,
    ) -> None:
        self.ps = parameter_store
        self.thresholds = thresholds or EdgeExistenceThresholdConfig()

    # ------------------------------------------------------------------
    def update(self, candidate: OntologyCandidate) -> None:
        """
        Recompute existence_probability for every learnable edge in `candidate`
        using accumulated sufficient statistics (cumulative counts).

        Call this AFTER LearningService.accumulate() has updated the counts.
        """
        for edge in candidate.edges:
            if not edge.learnable:
                continue
            self._update_edge(candidate, edge)

    def _update_edge(
        self, candidate: OntologyCandidate, edge: DependencyEdge
    ) -> None:
        parent_var = candidate.get_variable_by_id(edge.parent_variable_id)
        child_var = candidate.get_variable_by_id(edge.child_variable_id)
        if parent_var is None or child_var is None:
            return
        if not self.ps.has(candidate.candidate_id, child_var.name):
            return

        cpt_data = self.ps.get(candidate.candidate_id, child_var.name)

        # BIC with edge (full current parent set)
        score_with = cpt_data.bic_score()

        # BIC without this edge (marginalise out parent_var)
        if parent_var.name not in cpt_data.parents:
            # Edge not in active parent list (already pruned from CPT) → skip
            return
        score_without = cpt_data.bic_score_without_parent(parent_var.name)

        log_lr = score_with - score_without

        # Sequential Bayesian update from existence_prior (applied once via logit)
        # On first update: log_odds = logit(prior) + log_lr
        # On subsequent updates: we refresh from prior each time but with
        # full cumulative data, so this IS the correct posterior.
        log_odds = _logit(edge.existence_prior) + log_lr
        edge.existence_probability = _sigmoid(log_odds)
        edge.existence_update_count += 1

        # Update explore_weight: decay as existence resolves away from 0.5
        lo, hi = self.thresholds.explore_band
        if edge.existence_probability < lo or edge.existence_probability > hi:
            # Resolved — decay explore weight
            distance_from_mid = abs(edge.existence_probability - 0.5) * 2  # [0,1]
            edge.explore_weight = max(0.05, edge.explore_weight * (1.0 - 0.3 * distance_from_mid))
        else:
            # Still uncertain — maintain or raise explore weight
            edge.explore_weight = min(2.0, edge.explore_weight * 1.05)

    # ------------------------------------------------------------------
    def prune_below_threshold(
        self, candidate: OntologyCandidate, parameter_store: ParameterStore
    ) -> list[DependencyEdge]:
        """
        Mark edges with existence_probability < prune_below as disabled (pruned).
        Also updates the CPT parents for the affected child variable.
        Returns list of pruned edges.
        """
        pruned = []
        for edge in candidate.edges:
            if not edge.enabled:
                continue
            if edge.existence_probability < self.thresholds.prune_below:
                edge.enabled = False
                pruned.append(edge)
                # Remove parent from child's CPT
                parent_var = candidate.get_variable_by_id(edge.parent_variable_id)
                child_var = candidate.get_variable_by_id(edge.child_variable_id)
                if parent_var and child_var and parameter_store.has(candidate.candidate_id, child_var.name):
                    cpt = parameter_store.get(candidate.candidate_id, child_var.name)
                    if parent_var.name in cpt.parents:
                        new_parents = [p for p in cpt.parents if p != parent_var.name]
                        parameter_store.update_parents(
                            candidate.candidate_id, child_var.name, new_parents
                        )
        return pruned

    # ------------------------------------------------------------------
    def get_uncertain_edges(
        self, candidate: OntologyCandidate
    ) -> list[DependencyEdge]:
        """Return edges within the explore_band (uncertain existence)."""
        lo, hi = self.thresholds.explore_band
        return [
            e for e in candidate.edges
            if e.enabled and lo <= e.existence_probability <= hi
        ]
