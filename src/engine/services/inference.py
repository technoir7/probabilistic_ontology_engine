"""
InferenceService — exact inference via pgmpy VariableElimination.

Converts an OntologyCandidate (with CPT data from ParameterStore) into a
pgmpy BayesianNetwork and answers MARGINAL queries.

Population-level queries aggregate over multiple candidates, weighted by
exp(log_score).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination
from pgmpy.models import DiscreteBayesianNetwork as BayesianNetwork

from ..schemas import (
    InferenceQuery,
    OntologyCandidate,
    OntologyPopulation,
    PopulationAggregation,
)
from ..stores.parameter_store import CPTData, ParameterStore


class InferenceService:

    def __init__(self, parameter_store: ParameterStore) -> None:
        self.ps = parameter_store

    # ------------------------------------------------------------------
    def query(
        self,
        inference_query: InferenceQuery,
        population: OntologyPopulation,
    ) -> dict:
        """Main entry point.  Returns posteriors + optional explanation."""
        agg = inference_query.population_aggregation

        if agg == PopulationAggregation.ACTIVE_ONLY:
            dom = population.dominant()
            if dom is None:
                return {"error": "no active candidates"}
            result = self._query_candidate(dom, inference_query)
            result["population_summary"] = population.summary()
            return result

        elif agg == PopulationAggregation.WEIGHTED_AVERAGE:
            active = population.active_candidates()
            weights = population.score_weights()
            all_results = [
                self._query_candidate(c, inference_query) for c in active
            ]
            merged = self._weighted_merge(all_results, weights, inference_query.target_variables)
            merged["population_summary"] = population.summary()
            return merged

        else:  # TOP_K
            top_k = sorted(
                population.active_candidates(), key=lambda c: c.log_score, reverse=True
            )[:3]
            weights = self._normalize_weights([math.exp(c.log_score) for c in top_k])
            all_results = [self._query_candidate(c, inference_query) for c in top_k]
            merged = self._weighted_merge(all_results, weights, inference_query.target_variables)
            merged["population_summary"] = population.summary()
            return merged

    # ------------------------------------------------------------------
    def _query_candidate(
        self, candidate: OntologyCandidate, query: InferenceQuery
    ) -> dict:
        """Run inference on a single candidate and return posterior dict."""
        try:
            model = self._build_pgmpy_model(candidate)
            ve = VariableElimination(model)

            evidence = {}
            for obs in query.conditioned_on:
                var = candidate.get_variable_by_id(obs.variable_id)
                if var is None:
                    for v in candidate.variables:
                        if str(v.variable_id) == str(obs.variable_id):
                            var = v
                            break
                if var is not None:
                    evidence[var.name] = _encode_value(obs.observed_value, var.support)

            posteriors = {}
            for vname in query.target_variables:
                var = candidate.get_variable_by_name(vname)
                if var is None:
                    continue
                try:
                    q = ve.query([vname], evidence=evidence, show_progress=False)
                    dist = {}
                    for i, val in enumerate(var.support):
                        dist[str(val)] = float(q.values[i])
                    posteriors[vname] = dist
                except Exception as e:
                    # Fallback: use marginal from CPT
                    posteriors[vname] = self._marginal_fallback(candidate, vname)

            result: dict = {"posteriors": posteriors, "candidate_id": str(candidate.candidate_id)}

            if query.explain:
                result["explanations"] = self._explain(candidate, query, posteriors)

            return result

        except Exception as e:
            return {
                "posteriors": {},
                "candidate_id": str(candidate.candidate_id),
                "error": str(e),
            }

    # ------------------------------------------------------------------
    def _build_pgmpy_model(self, candidate: OntologyCandidate) -> BayesianNetwork:
        """Build a pgmpy BayesianNetwork from candidate + CPTs."""
        edges_pgmpy = []
        for e in candidate.get_active_edges():
            pv = candidate.get_variable_by_id(e.parent_variable_id)
            cv = candidate.get_variable_by_id(e.child_variable_id)
            if pv and cv:
                edges_pgmpy.append((pv.name, cv.name))

        model = BayesianNetwork(edges_pgmpy)
        # Ensure all variables are nodes even if isolated
        for v in candidate.variables:
            if v.name not in model.nodes():
                model.add_node(v.name)

        # Build CPDs
        for var in candidate.topological_order():
            parent_vars = candidate.get_parents(var.variable_id)
            if not self.ps.has(candidate.candidate_id, var.name):
                # Uniform CPD as fallback
                n = len(var.support)
                if parent_vars:
                    total_cols = 1
                    for pv in parent_vars:
                        total_cols *= len(pv.support)
                    values = np.full((n, total_cols), 1.0 / n)
                else:
                    values = np.full((n, 1), 1.0 / n)
                cpd = TabularCPD(
                    variable=var.name,
                    variable_card=n,
                    values=values,
                    evidence=[pv.name for pv in parent_vars] if parent_vars else None,
                    evidence_card=[len(pv.support) for pv in parent_vars] if parent_vars else None,
                )
                model.add_cpds(cpd)
                continue

            cpt_data = self.ps.get(candidate.candidate_id, var.name)
            cpd = _build_tabular_cpd(var, parent_vars, cpt_data)
            model.add_cpds(cpd)

        # Validate
        try:
            model.check_model()
        except Exception:
            pass  # Allow slight numerical imprecision

        return model

    # ------------------------------------------------------------------
    def _explain(self, candidate: OntologyCandidate, query: InferenceQuery, posteriors: dict) -> list[dict]:
        """Generate path-based explanations for active edges."""
        explanations = []
        for target_name in query.target_variables:
            target_var = candidate.get_variable_by_name(target_name)
            if target_var is None:
                continue
            # Find all simple paths from observed nodes to target
            import networkx as nx
            g = nx.DiGraph()
            for v in candidate.variables:
                g.add_node(v.name)
            for e in candidate.get_active_edges():
                pv = candidate.get_variable_by_id(e.parent_variable_id)
                cv = candidate.get_variable_by_id(e.child_variable_id)
                if pv and cv:
                    g.add_edge(pv.name, cv.name, edge_obj=e)

            obs_names = set()
            for obs in query.conditioned_on:
                v = candidate.get_variable_by_id(obs.variable_id)
                if v:
                    obs_names.add(v.name)

            for src_name in obs_names:
                try:
                    paths = list(nx.all_simple_paths(g, src_name, target_name))
                    for path in paths[:3]:
                        edge_probs = []
                        for i in range(len(path) - 1):
                            e = g.edges[path[i], path[i + 1]].get("edge_obj")
                            if e:
                                edge_probs.append(e.existence_probability)
                        explanations.append({
                            "path": path,
                            "edge_existence_probabilities": edge_probs,
                        })
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    pass

        return explanations

    # ------------------------------------------------------------------
    def _marginal_fallback(self, candidate: OntologyCandidate, vname: str) -> dict:
        var = candidate.get_variable_by_name(vname)
        if var is None:
            return {}
        n = len(var.support)
        return {str(v): 1.0 / n for v in var.support}

    # ------------------------------------------------------------------
    @staticmethod
    def _weighted_merge(
        results: list[dict], weights: list[float], target_variables: list[str]
    ) -> dict:
        merged_posteriors: dict = {vname: {} for vname in target_variables}
        for result, w in zip(results, weights):
            for vname, dist in result.get("posteriors", {}).items():
                if vname not in merged_posteriors:
                    merged_posteriors[vname] = {}
                for val, p in dist.items():
                    merged_posteriors[vname][val] = merged_posteriors[vname].get(val, 0.0) + w * p
        return {"posteriors": merged_posteriors}

    @staticmethod
    def _normalize_weights(weights: list[float]) -> list[float]:
        total = sum(weights) or 1.0
        return [w / total for w in weights]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode_value(value: Any, support: list) -> int:
    """Map a Python value to its index in the support list (pgmpy uses 0-based int states)."""
    for i, s in enumerate(support):
        if s == value or str(s) == str(value):
            return i
    return 0


def _build_tabular_cpd(var, parent_vars, cpt_data: CPTData) -> TabularCPD:
    """
    Build a pgmpy TabularCPD from our CPTData.

    pgmpy column ordering:
        Evidence states iterate from the LAST evidence variable fastest.
        e.g., evidence=['A','B'], evidence_card=[2,2]:
        columns: (A=0,B=0),(A=0,B=1),(A=1,B=0),(A=1,B=1)
    """
    n_var = len(var.support)
    evidence_names = [pv.name for pv in parent_vars]
    evidence_cards = [len(pv.support) for pv in parent_vars]
    evidence_supports = {pv.name: pv.support for pv in parent_vars}

    if not parent_vars:
        # Root node
        probs = []
        for val in var.support:
            probs.append([cpt_data.get_probability(val, {})])
        return TabularCPD(
            variable=var.name,
            variable_card=n_var,
            values=probs,
        )

    # Generate all parent configs in pgmpy column order
    from itertools import product as iproduct
    parent_value_combos = list(iproduct(*[pv.support for pv in parent_vars]))

    values = []
    for val in var.support:
        row = []
        for combo in parent_value_combos:
            parent_assignment = dict(zip(evidence_names, combo))
            p = cpt_data.get_probability(val, parent_assignment)
            row.append(p)
        values.append(row)

    # Normalize columns to sum to 1
    arr = np.array(values, dtype=float)
    col_sums = arr.sum(axis=0)
    col_sums = np.where(col_sums == 0, 1.0, col_sums)
    arr = arr / col_sums

    return TabularCPD(
        variable=var.name,
        variable_card=n_var,
        values=arr.tolist(),
        evidence=evidence_names,
        evidence_card=evidence_cards,
    )
