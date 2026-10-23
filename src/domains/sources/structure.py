"""
Constructors for a domain's ontology: its BOOLEAN variables and seed edges.
Every domain built these the same way; the domain still decides which
variables, edges and priors it has.
"""
from __future__ import annotations

from typing import Iterable, Mapping
from uuid import uuid4

from ...engine.schemas import DependencyEdge, DependencyKind, DomainType, Variable
from ...engine.variable_identity import stable_variable_id


def boolean_variables(module_id: str, names: Iterable[str]) -> dict[str, Variable]:
    """Name → BOOLEAN Variable with an id stable across restarts (stable_variable_id)."""
    return {
        name: Variable(
            variable_id=stable_variable_id(module_id, name),
            name=name,
            domain_type=DomainType.BOOLEAN,
            support=[True, False],
        )
        for name in names
    }


def with_lags(module_id: str, variables: Mapping[str, Variable]) -> dict[str, Variable]:
    """The variables and, for each, a companion holding last period's value
    (REFACTOR_SPEC D19), with an id as stable as the variable's."""
    out = dict(variables)
    for name, v in variables.items():
        lag = f"{name}_prev"
        out[lag] = Variable(variable_id=stable_variable_id(module_id, lag), name=lag,
                            domain_type=v.domain_type, support=list(v.support), time_indexed=True, lag_of=name)
    return out


def seed_edge(
    variables: Mapping[str, Variable], parent: str, child: str, prior: float, label: str = ""
) -> DependencyEdge:
    """A learnable directed edge whose existence starts at *prior*."""
    return DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=variables[parent].variable_id,
        child_variable_id=variables[child].variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
        existence_prior=prior,
        existence_probability=prior,
        learnable=True,
        enabled=True,
        explanatory_label=label or f"{parent}→{child}",
    )
