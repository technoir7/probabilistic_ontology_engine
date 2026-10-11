"""
Pure helpers that turn a domain's signals into soft evidence: a signed signal
becomes P(True) through a clamped sigmoid. Shared by every domain pipeline;
were copied identically ten times.
"""
from __future__ import annotations

import math

import numpy as np


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
