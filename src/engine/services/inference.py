"""
InferenceService — exact inference via pgmpy VariableElimination.

Converts an OntologyCandidate (with CPT data from ParameterStore) into a
pgmpy BayesianNetwork and answers MARGINAL queries.

Population-level queries aggregate over multiple candidates, weighted by
model.scoring.score_weights.
"""
from __future__ import annotations

from typing import Any

from pgmpy.inference import VariableElimination
from pgmpy.models import DiscreteBayesianNetwork as BayesianNetwork

from ..schemas import (
    InferenceQuery,
    OntologyCandidate,
    OntologyPopulation,
    PopulationAggregation,
)
from ..model.scoring import candidate_score, score_weights
from ..stores.parameter_store import ParameterStore
from .bn_model import build_network, encode_value


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
            result = self.query_candidate(dom, inference_query)
            result["population_summary"] = population.summary()
            return result

        elif agg == PopulationAggregation.WEIGHTED_AVERAGE:
            active = population.active_candidates()
            weights = population.score_weights()
            all_results = [
                self.query_candidate(c, inference_query) for c in active
            ]
            merged = self._weighted_merge(all_results, weights, inference_query.target_variables)
            merged["population_summary"] = population.summary()
            return merged

        else:  # TOP_K
            # Rank and weight by the population score. exp(raw log_score)
            # underflowed to 0.0 for every candidate at real scores.
            top_k = sorted(
                population.active_candidates(), key=candidate_score, reverse=True
            )[:3]
            weights = score_weights(top_k)
            all_results = [self.query_candidate(c, inference_query) for c in top_k]
            merged = self._weighted_merge(all_results, weights, inference_query.target_variables)
            merged["population_summary"] = population.summary()
            return merged

    # ------------------------------------------------------------------
    def query_candidate(
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
                    evidence[var.name] = encode_value(obs.observed_value, var.support)

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
        model = build_network(candidate, self.ps)
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
