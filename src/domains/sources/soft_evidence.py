"""
Pure helpers that turn a domain's signals into soft evidence: a signed signal
becomes P(True) through a clamped sigmoid. Shared by every domain pipeline;
were copied identically ten times.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np

from ...engine.model.errors import EvidenceUnavailable
from ...engine.schemas import EvidenceRecord, MissingnessType, ObservedAssignment, SourceType, Variable


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def soft_bool(signal: float, lo: float = 0.01, hi: float = 0.99) -> float:
    """
    P(True) for a signed signal, clamped to [lo, hi] so no single record is
    ever treated as certain. Noisy sources pass a tighter clamp
    (geopolitics: 0.05–0.95).
    """
    return max(lo, min(hi, sigmoid(signal)))


def zscore(current: float, values: list[float]) -> float:
    """(current - mean) / sample std of *values*; 0.0 with < 2 values or std ≈ 0."""
    if len(values) < 2:
        return 0.0
    arr = np.array(values, dtype=float)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    if sigma < 1e-9:
        return 0.0
    return (current - mu) / sigma


def evidence_id_for(module_id: str, timestamp: datetime, source_ref: str) -> UUID:
    """
    Deterministic id: the same domain, date and source give the same id, so
    the store's ON CONFLICT (evidence_id) DO NOTHING drops a re-fetched day.
    """
    return uuid5(NAMESPACE_URL, f"probabilistic-ontology-engine:evidence:{module_id}:{timestamp.isoformat()}:{source_ref}")


def build_soft_record(
    *,
    module_id: str,
    variables: Mapping[str, Variable],
    states: Iterable[tuple[str, bool, float]],
    confidence: Mapping[str, float],
    target_date: date,
    source_ref: str,
    missing: Iterable[str] = (),
    source_type: SourceType = SourceType.API,
) -> EvidenceRecord:
    """
    One record dated midnight UTC of *target_date*.

    *states* gives, per variable name in order, the MAP value and P(True).
    Variables in *missing* had no usable input: they are recorded as MISSING
    (decision D10) rather than as a 50/50 observation, which learning would
    count as real evidence that pulls every CPT toward independence.
    Raises EvidenceUnavailable when every variable is missing.

    A variable's confidence defaults to 1.0; the record's is their mean.
    """
    states = list(states)
    missing = set(missing)
    if states and all(name in missing for name, _, _ in states):
        raise EvidenceUnavailable(f"{module_id}: no input for any variable on {target_date}")
    assignments = [
        ObservedAssignment(
            variable_id=variables[name].variable_id,
            observed_value=None,
            missingness=MissingnessType.MISSING,
            confidence=confidence.get(name, 1.0),
        )
        if name in missing
        else ObservedAssignment(
            variable_id=variables[name].variable_id,
            observed_value=observed,
            missingness=MissingnessType.SOFT_OBSERVED,
            confidence=confidence.get(name, 1.0),
            probabilities={True: p_true, False: 1.0 - p_true},
        )
        for name, observed, p_true in states
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
