"""
Candidate + CPTs → pgmpy DiscreteBayesianNetwork.

One builder for every pgmpy consumer (inference, EM learning), so column
ordering and the uniform fallback for variables without a CPT are defined once.
"""
from __future__ import annotations

from itertools import product
from typing import Any

import numpy as np
from pgmpy.factors.discrete import TabularCPD
from pgmpy.models import DiscreteBayesianNetwork

from ..model.cpt import CPTData
from ..model.errors import UnknownValue
from ..schemas import OntologyCandidate
from ..stores.parameter_store import ParameterStore


def build_network(candidate: OntologyCandidate, parameter_store: ParameterStore) -> DiscreteBayesianNetwork:
    """Network over the candidate's active edges; does not call check_model()."""
    edges = []
    for e in candidate.get_active_edges():
        pv = candidate.get_variable_by_id(e.parent_variable_id)
        cv = candidate.get_variable_by_id(e.child_variable_id)
        if pv and cv:
            edges.append((pv.name, cv.name))

    model = DiscreteBayesianNetwork(edges)
    # Ensure all variables are nodes even if isolated
    for v in candidate.variables:
        if v.name not in model.nodes():
            model.add_node(v.name)

    for var in candidate.topological_order():
        parent_vars = candidate.get_parents(var.variable_id)
        if parameter_store.has(candidate.candidate_id, var.name):
            cpd = tabular_cpd(var, parent_vars, parameter_store.get(candidate.candidate_id, var.name))
        else:
            cpd = _uniform_cpd(var, parent_vars)
        model.add_cpds(cpd)
    return model


def _uniform_cpd(var, parent_vars) -> TabularCPD:
    n = len(var.support)
    total_cols = 1
    for pv in parent_vars:
        total_cols *= len(pv.support)
    return TabularCPD(
        variable=var.name,
        variable_card=n,
        values=np.full((n, total_cols), 1.0 / n),
        evidence=[pv.name for pv in parent_vars] if parent_vars else None,
        evidence_card=[len(pv.support) for pv in parent_vars] if parent_vars else None,
    )


def encode_value(value: Any, support: list) -> int:
    """Index of *value* in the support (pgmpy uses 0-based int states)."""
    for i, s in enumerate(support):
        if s == value or str(s) == str(value):
            return i
    raise UnknownValue(f"{value!r} is not one of {support!r}")


def tabular_cpd(var, parent_vars, cpt_data: CPTData) -> TabularCPD:
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
    parent_value_combos = list(product(*[pv.support for pv in parent_vars]))

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
