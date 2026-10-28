"""
Cases (REFACTOR_SPEC D29): many small histories judged together. A case is
an artist or a debate; each case-year carries its own past, the states of a
small pool of mechanisms, and next year's outcome (None for the open year,
whose outcome is still to come). A mechanism says that a case in some state
this year tends to some outcome next year, for every case at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

LEVELS = 3   # none, one, several


def level(n: int) -> int:
    return min(n, 2)


def doubling(n: int) -> int:
    """0, 1, 2, 3-4, 5-8, 9-16, 17+: a case's size graded finely enough
    that a mechanism cannot pass for it (abductive_engine ART-PLAN §8)."""
    return 0 if n == 0 else min(6, (n - 1).bit_length() + 1)


@dataclass(frozen=True)
class CaseYear:
    year: int
    own: tuple
    features: Mapping[str, int]
    outcome: Optional[int]          # None: the open year, to forecast
    weight: int = 1                 # identical case-years stored once
    case: Optional[str] = None


@dataclass(frozen=True)
class CaseSet:
    key: str
    title: str
    pool: tuple[str, ...]
    records: tuple[CaseYear, ...]
    labels: Mapping[str, str] = field(default_factory=dict)   # case -> readable name, when it has one
    outcome: str = ""               # what the outcome counts, in words
    meanings: Mapping[str, str] = field(default_factory=dict)  # mechanism -> what it says, in words
