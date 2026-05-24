"""
LearningService — Level 1 parameter update.

Two accumulation modes:
  1. accumulate()     — fast forward-pass mean-field (works well for fully-observed data)
  2. accumulate_em()  — proper EM using pgmpy posterior inference for missing variables

Both modes write to the same CPTData count tables.
"""
from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from ..schemas import EvidenceRecord, MissingnessType, OntologyCandidate
from ..stores.parameter_store import CPTData, ParameterStore


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
    ) -> None:
        """
        Update count tables from a batch.

        Fully-observed records → exact update.
        Partially-observed records → forward mean-field imputation (single pass).
        """
        vid_to_name = {str(v.variable_id): v.name for v in candidate.variables}
        topo_order = candidate.topological_order()
        all_names = {v.name for v in candidate.variables}

        for record in batch:
            observed: dict[str, Any] = {}
            missing_names: list[str] = []

            for assignment in record.observed_assignments:
                vid = str(assignment.variable_id)
                if vid not in vid_to_name:
                    continue
                vname = vid_to_name[vid]
                if assignment.missingness == MissingnessType.OBSERVED:
                    observed[vname] = assignment.observed_value
                else:
                    missing_names.append(vname)

            # Variables in candidate but absent from evidence are treated as missing
            for vname in all_names:
                if vname not in observed and vname not in missing_names:
                    missing_names.append(vname)

            if not missing_names:
                self._accumulate_fully_observed(candidate, observed)
            else:
                self._accumulate_mean_field(candidate, observed, topo_order)

    def _accumulate_fully_observed(
        self,
        candidate: OntologyCandidate,
        observed: dict[str, Any],
    ) -> None:
        for var in candidate.variables:
            if var.name not in observed:
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
            cpt_data.increment(observed[var.name], parent_assignment)

    def _accumulate_mean_field(
        self,
        candidate: OntologyCandidate,
        observed: dict[str, Any],
        topo_order: list,
    ) -> None:
        """
        Single-pass forward imputation.
        Computes soft distributions for unobserved variables in topological order,
        then accumulates fractional counts.
        """
        # Initialize soft_obs with hard observations
        soft_obs: dict[str, dict[Any, float]] = {
            vname: {val: 1.0} for vname, val in observed.items()
        }

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
                row = cpt_data.counts.get((), {})
                n_q = sum(row.values())
                r = len(var.support)
                dist = {
                    v: (row.get(v, 0) + cpt_data.alpha) / (n_q + cpt_data.alpha * r)
                    for v in var.support
                }
            else:
                dist = {v: 0.0 for v in var.support}
                from itertools import product as iproduct
                parent_names = [pv.name for pv in parent_vars]
                parent_value_lists = [
                    list(soft_obs.get(pn, {v: 1.0 / len(pv.support) for v in pv.support}).keys())
                    for pn, pv in zip(parent_names, parent_vars)
                ]
                for combo in iproduct(*parent_value_lists):
                    weight = 1.0
                    for pn, pv_val, pv in zip(parent_names, combo, parent_vars):
                        pn_soft = soft_obs.get(pn, {v: 1.0 / len(pv.support) for v in pv.support})
                        weight *= pn_soft.get(pv_val, 0.0)
                    if weight < 1e-14:
                        continue
                    pa = dict(zip(parent_names, combo))
                    for v in var.support:
                        dist[v] += weight * cpt_data.get_probability(v, pa)

            total = sum(dist.values()) or 1.0
            soft_obs[var.name] = {v: dist[v] / total for v in dist}

        # Accumulate fractional counts
        from itertools import product as iproduct
        for var in candidate.variables:
            if not self.ps.has(candidate.candidate_id, var.name):
                continue
            if var.name not in soft_obs:
                continue
            cpt_data = self.ps.get(candidate.candidate_id, var.name)
            parent_vars = candidate.get_parents(var.variable_id)

            if not parent_vars:
                parent_config = ()
                if parent_config not in cpt_data.counts:
                    cpt_data.counts[parent_config] = {v: 0.0 for v in var.support}
                for val, prob in soft_obs[var.name].items():
                    if prob < 1e-12:
                        continue
                    cpt_data.counts[parent_config][val] = (
                        cpt_data.counts[parent_config].get(val, 0.0) + prob
                    )
            else:
                parent_names = [pv.name for pv in parent_vars]
                parent_value_lists = [
                    list(soft_obs.get(pn, {v: 1.0 / 2 for v in pv.support}).keys())
                    for pn, pv in zip(parent_names, parent_vars)
                ]
                for combo in iproduct(*parent_value_lists):
                    weight = 1.0
                    for pn, pv_val, pv in zip(parent_names, combo, parent_vars):
                        pn_soft = soft_obs.get(pn, {})
                        weight *= pn_soft.get(pv_val, 0.0)
                    if weight < 1e-12:
                        continue
                    pa = dict(zip(parent_names, combo))
                    parent_config = tuple(sorted(pa.items()))
                    if parent_config not in cpt_data.counts:
                        cpt_data.counts[parent_config] = {v: 0.0 for v in var.support}
                    for val, vprob in soft_obs[var.name].items():
                        combined = weight * vprob
                        if combined < 1e-12:
                            continue
                        cpt_data.counts[parent_config][val] = (
                            cpt_data.counts[parent_config].get(val, 0.0) + combined
                        )

    # ------------------------------------------------------------------
    # Proper EM with pgmpy posterior inference
    # ------------------------------------------------------------------

    def accumulate_em(
        self,
        batch: list[EvidenceRecord],
        candidate: OntologyCandidate,
        n_iterations: int = 5,
    ) -> None:
        """
        Proper EM for partially-observed data.

        Uses pgmpy VariableElimination in the E-step to compute exact posteriors
        of missing variables given observed ones.  Iterates n_iterations times,
        reusing updated CPT parameters on each E-step.

        Accumulates the final expected sufficient statistics into the CPT counts.
        """
        vid_to_name = {str(v.variable_id): v.name for v in candidate.variables}
        all_names = {v.name for v in candidate.variables}

        # Split records into fully-observed and partially-observed
        fully_obs_list: list[dict[str, Any]] = []
        partial_obs_list: list[dict[str, Any]] = []  # only observed parts

        for record in batch:
            observed: dict[str, Any] = {}
            has_missing = False
            for assignment in record.observed_assignments:
                vid = str(assignment.variable_id)
                if vid not in vid_to_name:
                    continue
                vname = vid_to_name[vid]
                if assignment.missingness == MissingnessType.OBSERVED:
                    observed[vname] = assignment.observed_value
                else:
                    has_missing = True

            absent = [v for v in candidate.variables if v.name not in observed]
            if absent:
                has_missing = True

            if has_missing:
                partial_obs_list.append(observed)
            else:
                fully_obs_list.append(observed)

        # Step 1: accumulate fully observed (exact, done once)
        for obs in fully_obs_list:
            self._accumulate_fully_observed(candidate, obs)

        if not partial_obs_list:
            return

        # Step 2: EM iterations over partially-observed records.
        # Pattern: build model with CURRENT counts → E-step → new delta →
        #          remove OLD delta → add NEW delta.
        from .inference import _build_tabular_cpd, _encode_value
        from pgmpy.models import DiscreteBayesianNetwork as BayesianNetwork
        from pgmpy.inference import VariableElimination
        from pgmpy.factors.discrete import TabularCPD

        prev_delta: dict[str, dict] = {}  # delta from previous iteration

        for iteration in range(n_iterations):
            # ---- build pgmpy model from CURRENT CPT counts ----
            use_pgmpy = False
            ve = None
            try:
                pgmpy_edges = []
                for e in candidate.get_active_edges():
                    pv = candidate.get_variable_by_id(e.parent_variable_id)
                    cv = candidate.get_variable_by_id(e.child_variable_id)
                    if pv and cv:
                        pgmpy_edges.append((pv.name, cv.name))
                pgmpy_model = BayesianNetwork(pgmpy_edges)
                for v in candidate.variables:
                    if v.name not in pgmpy_model.nodes():
                        pgmpy_model.add_node(v.name)
                for var in candidate.topological_order():
                    pv_list = candidate.get_parents(var.variable_id)
                    if self.ps.has(candidate.candidate_id, var.name):
                        cpd_data = self.ps.get(candidate.candidate_id, var.name)
                        cpd = _build_tabular_cpd(var, pv_list, cpd_data)
                    else:
                        n = len(var.support)
                        n_cols = max(1, 2 ** len(pv_list))
                        cpd = TabularCPD(
                            var.name, n,
                            [[1.0 / n] * n_cols for _ in range(n)],
                            evidence=[pv.name for pv in pv_list] if pv_list else None,
                            evidence_card=[len(pv.support) for pv in pv_list] if pv_list else None,
                        )
                    pgmpy_model.add_cpds(cpd)
                pgmpy_model.check_model()
                ve = VariableElimination(pgmpy_model)
                use_pgmpy = True
            except Exception:
                pass

            # ---- E-step: compute new delta ----
            new_delta: dict[str, dict] = {v.name: {} for v in candidate.variables}
            from itertools import product as iproduct

            for obs in partial_obs_list:
                missing_vnames = [v.name for v in candidate.variables if v.name not in obs]

                if use_pgmpy and ve is not None:
                    evidence_int: dict[str, int] = {}
                    for vname, val in obs.items():
                        var = candidate.get_variable_by_name(vname)
                        if var:
                            evidence_int[vname] = _encode_value(val, var.support)

                    soft: dict[str, dict[Any, float]] = {
                        vname: {val: 1.0} for vname, val in obs.items()
                    }
                    for mv_name in missing_vnames:
                        mv = candidate.get_variable_by_name(mv_name)
                        if mv is None:
                            continue
                        try:
                            q = ve.query([mv_name], evidence=evidence_int, show_progress=False)
                            soft[mv_name] = {
                                mv.support[i]: float(q.values[i])
                                for i in range(len(mv.support))
                            }
                        except Exception:
                            soft[mv_name] = {v: 1.0 / len(mv.support) for v in mv.support}
                else:
                    soft = {vname: {val: 1.0} for vname, val in obs.items()}
                    for var in candidate.topological_order():
                        if var.name not in soft:
                            soft[var.name] = {v: 1.0 / len(var.support) for v in var.support}

                # Accumulate into new_delta
                for var in candidate.variables:
                    if var.name not in soft:
                        continue
                    pvars = candidate.get_parents(var.variable_id)
                    if not pvars:
                        cfg = ()
                        if cfg not in new_delta[var.name]:
                            new_delta[var.name][cfg] = {v: 0.0 for v in var.support}
                        for val, prob in soft[var.name].items():
                            new_delta[var.name][cfg][val] = new_delta[var.name][cfg].get(val, 0.0) + prob
                    else:
                        pnames = [pv.name for pv in pvars]
                        pa_val_lists = [list(soft.get(pn, {}).keys()) for pn in pnames]
                        if any(not lst for lst in pa_val_lists):
                            continue
                        for combo in iproduct(*pa_val_lists):
                            wt = 1.0
                            for pn, pv_val in zip(pnames, combo):
                                wt *= soft.get(pn, {}).get(pv_val, 0.0)
                            if wt < 1e-12:
                                continue
                            cfg = tuple(sorted(zip(pnames, combo)))
                            if cfg not in new_delta[var.name]:
                                new_delta[var.name][cfg] = {v: 0.0 for v in var.support}
                            for val, vp in soft[var.name].items():
                                new_delta[var.name][cfg][val] = (
                                    new_delta[var.name][cfg].get(val, 0.0) + wt * vp
                                )

            # ---- M-step: swap delta (remove prev, add new) ----
            for vname, config_map in prev_delta.items():
                if not self.ps.has(candidate.candidate_id, vname):
                    continue
                cpt = self.ps.get(candidate.candidate_id, vname)
                for cfg, val_map in config_map.items():
                    if cfg in cpt.counts:
                        for val, cnt in val_map.items():
                            cpt.counts[cfg][val] = cpt.counts[cfg].get(val, 0.0) - cnt

            for vname, config_map in new_delta.items():
                if not self.ps.has(candidate.candidate_id, vname):
                    continue
                cpt = self.ps.get(candidate.candidate_id, vname)
                for cfg, val_map in config_map.items():
                    if cfg not in cpt.counts:
                        cpt.counts[cfg] = {v: 0.0 for v in val_map}
                    for val, cnt in val_map.items():
                        cpt.counts[cfg][val] = cpt.counts[cfg].get(val, 0.0) + cnt

            prev_delta = new_delta

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    def compute_log_likelihood(
        self,
        batch: list[EvidenceRecord],
        candidate: OntologyCandidate,
    ) -> float:
        """
        Compute sum_{record} sum_{observed X} log P(X=x | Pa(X)).
        Uses smoothed CPT probabilities.
        """
        vid_to_name = {str(v.variable_id): v.name for v in candidate.variables}
        total_ll = 0.0

        for record in batch:
            observed: dict[str, Any] = {}
            for assignment in record.observed_assignments:
                vid = str(assignment.variable_id)
                if vid not in vid_to_name:
                    continue
                if assignment.missingness == MissingnessType.OBSERVED:
                    observed[vid_to_name[vid]] = assignment.observed_value

            for var in candidate.variables:
                if var.name not in observed:
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
                total_ll += cpt_data.log_prob(observed[var.name], parent_assignment)

        return total_ll
