"""
Beliefs about change (REFACTOR_SPEC D19).

A domain may give each variable a companion holding its value last period.
Records are stored as observed; when they are learned, each is given its
predecessor's values for those companions, so a structure can hold that
this week follows from last. Last period's values are inputs: never a
child, and never scored again.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..schemas import EvidenceRecord, MissingnessType, ObservedAssignment, Variable


def lag_name(name: str) -> str:
    return f"{name}_prev"


def lagged(records: Sequence[EvidenceRecord], previous: Optional[EvidenceRecord],
           variables: Sequence[Variable]) -> list[EvidenceRecord]:
    """Each record with last period's values from the one before it (the
    first from `previous`, MISSING if there is none)."""
    lags = [v for v in variables if v.lag_of]
    if not lags:
        return list(records)
    current_id = {v.name: v.variable_id for v in variables}
    out = []
    for record in records:
        before = {a.variable_id: a for a in previous.observed_assignments} if previous else {}
        own = [a for a in record.observed_assignments if a.variable_id not in {v.variable_id for v in lags}]
        added = []
        for lag in lags:
            source = before.get(current_id.get(lag.lag_of))
            added.append(source.model_copy(update={"variable_id": lag.variable_id}) if source is not None else
                         ObservedAssignment(variable_id=lag.variable_id, observed_value=None,
                                            missingness=MissingnessType.MISSING))
        out.append(record.model_copy(update={"observed_assignments": own + added}))
        previous = record
    return out
