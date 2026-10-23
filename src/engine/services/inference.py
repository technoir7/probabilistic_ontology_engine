"""
InferenceService — exact inference via pgmpy VariableElimination.

Converts an OntologyCandidate (with CPT data from ParameterStore) into a
pgmpy BayesianNetwork and answers MARGINAL queries.

Population-level queries aggregate over multiple candidates, weighted by
model.scoring.score_weights.
"""
from __future__ import annotations

import math
from typing import Any


from pgmpy.inference import VariableElimination
from pgmpy.models import DiscreteBayesianNetwork as BayesianNetwork

from ..schemas import (
    InferenceQuery,
    OntologyCandidate,
    OntologyPopulation,
    PopulationAggregation,
)
from ..model.errors import InferenceFailed
from ..model.scoring import candidate_score, score_weights
from ..stores.parameter_store import ParameterStore
from ..model.levels import LEVELS, p_past
from .bn_model import build_network, encode_value

_NEGLIGIBLE_WEIGHT = 1e-9


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
            # Skip structures the data has all but ruled out: with posterior
            # weights most candidates are ~0, and each query is a full VE run.
            weighted = [
                (c, w) for c, w in zip(population.active_candidates(), population.score_weights())
                if w > _NEGLIGIBLE_WEIGHT
            ]
            total = sum(w for _, w in weighted)
            weights = [w / total for _, w in weighted]
            all_results = [self.query_candidate(c, inference_query) for c, _ in weighted]
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
        """
        Posteriors for the query's target variables under this one candidate.

        Raises UnknownValue for evidence outside a variable's support and
        InferenceFailed if pgmpy cannot answer; it does not fall back to a
        uniform distribution, which would read as "maximally uncertain".
        """
        model = self._build_pgmpy_model(candidate)
        ve = VariableElimination(model)

        evidence = {}
        for obs in query.conditioned_on:
            var = candidate.get_variable_by_id(obs.variable_id)
            if var is not None:
                evidence[var.name] = encode_value(obs.observed_value, var.support)

        posteriors = {}
        for vname in query.target_variables:
            var = candidate.get_variable_by_name(vname)
            if var is None:
                continue
            try:
                q = ve.query([vname], evidence=evidence, show_progress=False)
            except Exception as exc:
                raise InferenceFailed(
                    f"inference for {vname!r} failed on candidate {candidate.candidate_id}: {exc}"
                ) from exc
            posteriors[vname] = {str(val): float(q.values[i]) for i, val in enumerate(var.support)}

        result: dict = {"posteriors": posteriors, "candidate_id": str(candidate.candidate_id)}
        if query.explain:
            result["explanations"] = self._explain(candidate, query, posteriors)
        return result

    # ------------------------------------------------------------------
    def leave_one_out(self, candidate: OntologyCandidate, observed: dict[str, Any]) -> dict[str, float]:
        """P(each observed variable is true | every other observed one), or for
        five levels P(past the threshold); one model built for all of them
        (D18 calibration, D20)."""
        ve = VariableElimination(self._build_pgmpy_model(candidate))
        out = {}
        for name, _ in observed.items():
            var = candidate.get_variable_by_name(name)
            if var is None or var.lag_of or not (True in var.support or tuple(var.support) == LEVELS):
                continue
            evidence = {n: encode_value(v, candidate.get_variable_by_name(n).support)
                        for n, v in observed.items() if n != name and candidate.get_variable_by_name(n)}
            q = ve.query([name], evidence=evidence, show_progress=False)
            if True in var.support:
                out[name] = float(q.values[var.support.index(True)])
            else:  # five levels: P(past the threshold) (D20)
                out[name] = p_past({level: float(q.values[i]) for i, level in enumerate(var.support)})
        return out

    def forecast_log_prob(self, candidate: OntologyCandidate, observed: dict[str, Any]) -> float | None:
        """log P(this period's observed values | last period's values only):
        what the candidate would have forecast before seeing the period (D19).
        None if it has no last-period values to go on."""
        lags = {n: v for n, v in observed.items() if (var := candidate.get_variable_by_name(n)) and var.lag_of}
        now = {n: v for n, v in observed.items() if n not in lags and candidate.get_variable_by_name(n)}
        if not lags or not now:
            return None
        ve = VariableElimination(self._build_pgmpy_model(candidate))
        evidence = {n: encode_value(v, candidate.get_variable_by_name(n).support) for n, v in lags.items()}
        joint = ve.query(list(now), evidence=evidence, joint=True, show_progress=False)
        state = {n: encode_value(v, candidate.get_variable_by_name(n).support) for n, v in now.items()}
        p = float(joint.get_value(**state))
        return math.log(max(p, 1e-300))

    # ------------------------------------------------------------------
    def _build_pgmpy_model(self, candidate: OntologyCandidate) -> BayesianNetwork:
        model = build_network(candidate, self.ps)
        try:
            model.check_model()
        except ValueError:
            pass  # CPD columns can miss summing to 1 by float error; inference still works
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
