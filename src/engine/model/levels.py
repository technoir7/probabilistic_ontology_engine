"""
Five ordered levels (REFACTOR_SPEC D20): how far a signal sits from its
threshold, not only which side of it.

A domain's soft evidence gives P(signal past its threshold) = σ(s), where s
is the signal in the domain's own units with the threshold at 0. Read s as
the centre of a standard logistic, and the levels are its mass between the
cut points −2, 0, 2 and 4: each level about one standard deviation of that
logistic (π/√3 ≈ 1.8) wide, so a level is as fine as the evidence can tell
apart. For inflation (s = (CPI − 3.5%) / 0.75) the cuts fall at 2%, 3.5%, 5%
and 6.5%. The three levels past 0 together are exactly
σ(s), the old probability of "true", so the levels are a finer cut of the
same evidence and stay comparable with boolean history.
"""
from __future__ import annotations

import math
from typing import Mapping

LEVELS = ("well_below", "below", "past", "well_past", "extreme")
PAST = LEVELS[2:]
CUTS = (-2.0, 0.0, 2.0, 4.0)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def levels_from_p(p: float) -> dict[str, float]:
    """The level distribution whose past-threshold share is p (0 < p < 1)."""
    s = math.log(p / (1.0 - p))
    edges = [0.0, *(_sigmoid(c - s) for c in CUTS), 1.0]
    return {level: edges[i + 1] - edges[i] for i, level in enumerate(LEVELS)}


def p_past(dist: Mapping) -> float:
    """P(past the threshold): the three upper levels."""
    return float(sum(dist.get(level, 0.0) for level in PAST))
