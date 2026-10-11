"""
Pure helpers that turn a domain's signals into soft evidence: a signed signal
becomes P(True) through a clamped sigmoid. Shared by every domain pipeline;
were copied identically ten times.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Iterable, Mapping
from uuid import uuid4

import numpy as np

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


def build_soft_record(
    *,
    module_id: str,
    variables: Mapping[str, Variable],
    states: Iterable[tuple[str, bool, float]],
    confidence: Mapping[str, float],
    target_date: date,
    source_ref: str,
) -> EvidenceRecord:
    """
    One SOFT_OBSERVED record dated midnight UTC of *target_date*.

    *states* gives, per variable name in order, the MAP value and P(True).
    A variable's confidence defaults to 1.0; the record's is their mean.
    """
    assignments = [
        ObservedAssignment(
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
        evidence_id=uuid4(),
        timestamp=timestamp,
        observed_assignments=assignments,
        source_type=SourceType.API,
        source_ref=source_ref,
        confidence=float(sum(confidence.values()) / len(confidence)) if confidence else 1.0,
    )
