"""
Constructors for a domain's concepts: its BOOLEAN variables and their
last-period companions. Every domain built these the same way; the domain
still decides which variables it has. It gives no edges: the engine forms
its own hypotheses (REFACTOR_SPEC D24).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from ...engine.schemas import DomainType, Variable
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

