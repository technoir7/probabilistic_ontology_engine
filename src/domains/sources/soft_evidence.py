"""
Pure helpers shared by every domain pipeline: a value's z-score against its
own history, and a record's deterministic id. (The module once also turned
signals into P(True); since D25 every domain reads levels, sources/grades.py.)
"""
from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np



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
