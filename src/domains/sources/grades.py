"""
Levels of degree (REFACTOR_SPEC D25). A measured signal is a precise number,
so what it says is how far it lies from the line that names its concept, not
a doubt about which side it is on. Reading it as P(True) through a sigmoid
passed a degree off as a doubt, and counting each such doubt apart from the
others blurred real dependences away.

A signal is a signed distance from its concept's line on the domain's own
scale (z-scores, or a domain-set unit). It is read as one of three levels,
observed exactly: low (more than half a unit below the line), mid (within
half a unit), high (more than half a unit above). Half a unit splits a
standardized signal into three roughly equal bands. Three levels are Kant's
categories of quality: negation, limitation, reality (A80/B106).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Mapping

from ...engine.model.errors import EvidenceUnavailable
from ...engine.schemas import (
    DomainType,
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
    Variable,
)
from ...engine.variable_identity import stable_variable_id
from .soft_evidence import evidence_id_for

LEVELS = ("low", "mid", "high")
_CUT = 0.5


def level_of(signal: float) -> str:
    """The level a signed signal falls in."""
    if signal < -_CUT:
        return "low"
    if signal > _CUT:
        return "high"
    return "mid"


def graded_variables(module_id: str, names: Iterable[str]) -> dict[str, Variable]:
    """Name → ORDINAL Variable over LEVELS, with an id stable across restarts."""
    return {
        name: Variable(
            variable_id=stable_variable_id(module_id, name),
            name=name,
            domain_type=DomainType.ORDINAL,
            support=list(LEVELS),
        )
        for name in names
    }


def build_graded_record(
    *,
    module_id: str,
    variables: Mapping[str, Variable],
    signals: Mapping[str, float],
    confidence: Mapping[str, float],
    target_date: date,
    source_ref: str,
    source_type: SourceType = SourceType.API,
    previous: Mapping[str, float] | None = None,
) -> EvidenceRecord:
    """
    One record dated midnight UTC of *target_date*: each variable with a
    signal observed at its level, each without one MISSING (D10). Raises
    EvidenceUnavailable when no variable has a signal.

    A variable's confidence defaults to 1.0; the record's is their mean.

    *previous* gives some variables' last-period signals, observed on their
    lag companions; the engine keeps a lag a record observes itself and
    fills the rest from the record before (model/temporal.py).
    """
    if not signals:
        raise EvidenceUnavailable(f"{module_id}: no input for any variable on {target_date}")
    assignments = [
        ObservedAssignment(variable_id=v.variable_id, observed_value=level_of(signals[name]),
                           missingness=MissingnessType.OBSERVED, confidence=confidence.get(name, 1.0))
        if name in signals else
        ObservedAssignment(variable_id=v.variable_id, observed_value=None,
                           missingness=MissingnessType.MISSING, confidence=confidence.get(name, 1.0))
        for name, v in variables.items() if not v.lag_of
    ] + [
        ObservedAssignment(variable_id=v.variable_id, observed_value=level_of((previous or {})[v.lag_of]),
                           missingness=MissingnessType.OBSERVED)
        for v in variables.values() if v.lag_of and v.lag_of in (previous or {})
    ]
    timestamp = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    return EvidenceRecord(
        evidence_id=evidence_id_for(module_id, timestamp, source_ref),
        timestamp=timestamp,
        observed_assignments=assignments,
        source_type=source_type,
        source_ref=source_ref,
        confidence=float(sum(confidence.values()) / len(confidence)) if confidence else 1.0,
    )
