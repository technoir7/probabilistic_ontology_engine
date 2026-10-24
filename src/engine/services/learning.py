"""
LearningService — Level 1 parameter update.

accumulate() is a forward-pass mean-field update: missing variables are
imputed from their parents under the current CPTs, then counted
fractionally. It does not condition a missing parent on its observed
children, so dependencies weaken when parents are missing (REFACTOR_SPEC B20).
"""
from __future__ import annotations

from itertools import product
import math
from typing import Any

from ..schemas import EvidenceRecord, MissingnessType, OntologyCandidate

_SOFT = MissingnessType.SOFT_OBSERVED
_HARD = MissingnessType.OBSERVED
from ..stores.parameter_store import ParameterStore


class LearningService:

    def __init__(self, parameter_store: ParameterStore) -> None:
        self.ps = parameter_store

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize_candidate(
        self,
        candidate: OntologyCandidate,
        alpha: float = 1.0,
    ) -> None:
        """Set up CPTData for every variable in the candidate."""
        for var in candidate.variables:
            parent_vars = candidate.get_parents(var.variable_id)
            parent_names = sorted(pv.name for pv in parent_vars)
            self.ps.initialize_candidate(
                candidate_id=candidate.candidate_id,
                variable_name=var.name,
                parents=parent_names,
                support=var.support,
                alpha=alpha,
            )

    # ------------------------------------------------------------------
    # Fast accumulation (fully-observed fast path + forward imputation)
    # ------------------------------------------------------------------

    def accumulate(
        self,
        batch: list[EvidenceRecord],
        candidate: OntologyCandidate,
        only: set[str] | None = None,
    ) -> None:
        """
        Update count tables from a batch: every variable's, or ONLY these.

        Fully-observed records → exact update.
        Partially-observed records → forward mean-field imputation (single pass).
        """
        vid_to_name = {str(v.variable_id): v.name for v in candidate.variables}
        topo_order = candidate.topological_order()
        all_names = {v.name for v in candidate.variables}

        for record in batch:
            observed: dict[str, Any] = {}        # hard (OBSERVED) assignments
            soft_evidence: dict[str, dict[Any, float]] = {}  # SOFT_OBSERVED dists
            missing_names: list[str] = []

            for assignment in record.observed_assignments:
                vid = str(assignment.variable_id)
                if vid not in vid_to_name:
                    continue
                vname = vid_to_name[vid]
                if assignment.missingness == _HARD:
                    observed[vname] = assignment.observed_value
                elif assignment.missingness == _SOFT:
                    if assignment.probabilities:
                        soft_evidence[vname] = dict(assignment.probabilities)
                    else:
                        # Probabilities absent → degrade to hard observation
                        observed[vname] = assignment.observed_value
                else:
                    # MISSING / IMPUTED / REDACTED
                    missing_names.append(vname)

            # Variables in candidate but absent from evidence are treated as missing
            for vname in all_names:
                if vname not in observed and vname not in soft_evidence and vname not in missing_names:
                    missing_names.append(vname)

            if not missing_names and not soft_evidence:
                # All variables are hard-observed → fast exact path
                self._accumulate_fully_observed(candidate, observed, only)
            else:
                # Some variables are soft-observed or missing → mean-field path
                self._accumulate_mean_field(
                    candidate, observed, topo_order, soft_evidence or None, only
                )

    def _accumulate_fully_observed(
        self,
        candidate: OntologyCandidate,
        observed: dict[str, Any],
        only: set[str] | None = None,
    ) -> None:
        for var in candidate.variables:
            if var.name not in observed or (only is not None and var.name not in only):
                continue
            if not self.ps.has(candidate.candidate_id, var.name):
                continue
            cpt_data = self.ps.get(candidate.candidate_id, var.name)
            parent_vars = candidate.get_parents(var.variable_id)
            parent_assignment: dict[str, Any] = {}
            all_obs = True
            for pv in parent_vars:
                if pv.name not in observed:
                    all_obs = False
                    break
                parent_assignment[pv.name] = observed[pv.name]
            if not all_obs:
                continue
            cpt_data.add(observed[var.name], parent_assignment)

    def _accumulate_mean_field(
        self,
        candidate: OntologyCandidate,
        observed: dict[str, Any],
        topo_order: list,
        soft_by_name: dict[str, dict[Any, float]] | None = None,
        only: set[str] | None = None,
    ) -> None:
        """
        Single-pass forward imputation.

        Initialises soft_obs from hard observations and (when provided) from
        pre-computed soft distributions for SOFT_OBSERVED variables.  Then
        computes soft distributions for any remaining unobserved variables in
        topological order, and accumulates fractional counts.

        Parameters
        ----------
        soft_by_name:
            Pre-seeded soft distributions for SOFT_OBSERVED variables.
            These override any imputed distribution for that variable.
        """
        # Initialize soft_obs with hard observations
        soft_obs: dict[str, dict[Any, float]] = {
            vname: {val: 1.0} for vname, val in observed.items()
        }
        # Inject soft evidence — already normalised upstream
        if soft_by_name:
            for vname, probs in soft_by_name.items():
                soft_obs[vname] = dict(probs)

        # Forward pass: compute soft distributions for unobserved variables
        for var in topo_order:
            if var.name in soft_obs:
                continue
            if not self.ps.has(candidate.candidate_id, var.name):
                soft_obs[var.name] = {v: 1.0 / len(var.support) for v in var.support}
                continue

            cpt_data = self.ps.get(candidate.candidate_id, var.name)
            parent_vars = candidate.get_parents(var.variable_id)

            if not parent_vars:
                # Root node: use marginal from CPT
                dist = {v: cpt_data.get_probability(v, {}) for v in var.support}
            else:
                # Parents precede var in topological order, so soft_obs has them.
                dist = {v: 0.0 for v in var.support}
                parent_names = [pv.name for pv in parent_vars]
                for combo in product(*(soft_obs[pn].keys() for pn in parent_names)):
                    weight = 1.0
                    for pn, pv_val in zip(parent_names, combo):
                        weight *= soft_obs[pn].get(pv_val, 0.0)
                    if weight < 1e-14:
                        continue
                    pa = dict(zip(parent_names, combo))
                    for v in var.support:
                        dist[v] += weight * cpt_data.get_probability(v, pa)

            total = sum(dist.values()) or 1.0
            soft_obs[var.name] = {v: dist[v] / total for v in dist}

        # Accumulate fractional counts. Every variable is in soft_obs after the
        # forward pass; a root has one (empty) parent configuration.
        for var in candidate.variables:
            if not self.ps.has(candidate.candidate_id, var.name) or (only is not None and var.name not in only):
                continue
            cpt_data = self.ps.get(candidate.candidate_id, var.name)
            parent_names = [pv.name for pv in candidate.get_parents(var.variable_id)]
            for combo in product(*(soft_obs[pn].keys() for pn in parent_names)):
                weight = 1.0
                for pn, pv_val in zip(parent_names, combo):
                    weight *= soft_obs[pn].get(pv_val, 0.0)
                if weight < 1e-12:
                    continue
                pa = dict(zip(parent_names, combo))
                cpt_data.ensure_row(pa)
                for val, vprob in soft_obs[var.name].items():
                    combined = weight * vprob
                    if combined >= 1e-12:
                        cpt_data.add(val, pa, combined)

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    def compute_log_likelihood(
        self,
        batch: list[EvidenceRecord],
        candidate: OntologyCandidate,
    ) -> float:
        """
        Compute the expected log-likelihood over a batch.

        Hard evidence (OBSERVED):
            contrib = log P(X=x | Pa(X))

        Soft evidence (SOFT_OBSERVED):
            contrib = Σ_x  P_obs(X=x) * log P_model(X=x | Pa(X))

        For hard parents the exact parent configuration is used.
        For soft parents the MAP value (argmax of the observation distribution)
        is used as a first-order approximation. A missing parent is averaged
        over as the data has seen it (CPTData.get_probability_given, D23):
        skipping the variable would score it as certain.

        Uses Laplace-smoothed CPT probabilities.
        """
        vid_to_name = {str(v.variable_id): v.name for v in candidate.variables}
        total_ll = 0.0

        for record in batch:
            # Build per-variable distributions for this record.
            # var_dists[vname] = {value → probability}
            var_dists: dict[str, dict[Any, float]] = {}

            for assignment in record.observed_assignments:
                vid = str(assignment.variable_id)
                if vid not in vid_to_name:
                    continue
                vname = vid_to_name[vid]
                if assignment.missingness == _HARD:
                    var_dists[vname] = {assignment.observed_value: 1.0}
                elif assignment.missingness == _SOFT:
                    if assignment.probabilities:
                        var_dists[vname] = dict(assignment.probabilities)
                    else:
                        # Degrade to hard observation
                        var_dists[vname] = {assignment.observed_value: 1.0}
                # MISSING / IMPUTED / REDACTED → not added; skipped below

            for var in candidate.variables:
                if var.lag_of or var.name not in var_dists:
                    continue  # last period's values were scored last period (D19)
                if not self.ps.has(candidate.candidate_id, var.name):
                    continue
                cpt_data = self.ps.get(candidate.candidate_id, var.name)
                parent_vars = candidate.get_parents(var.variable_id)

                # Observed parents at their MAP value (exact for hard; approx for soft).
                known = {pv.name: max(var_dists[pv.name].items(), key=lambda kv: kv[1])[0]
                         for pv in parent_vars if pv.name in var_dists}

                # Expected log-likelihood: Σ_x P_obs(x) * log P_model(x | Pa)
                for val, p_obs in var_dists[var.name].items():
                    if p_obs > 1e-12:
                        total_ll += p_obs * math.log(max(cpt_data.get_probability_given(val, known), 1e-12))

        return total_ll
