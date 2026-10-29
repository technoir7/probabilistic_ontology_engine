"""
Success (REFACTOR_SPEC D31; abductive_engine ART-PLAN §12): what predicts
that an artist succeeds next year, in four senses kept apart, each judged
by the case engine (D29) offline over every artist-year and shipped with
the controls it faced and what critics rewarded this year.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class SuccessKind:
    key: str
    title: str
    outcome: str
    leader: tuple[str, ...]                 # empty: own past alone
    leader_since: Optional[int]
    gain: float                             # nats the leaders won over own past, all scored years
    mechanisms: tuple[tuple[str, float], ...]   # best rival sets, "a+b" -> gain
    effects: Mapping[tuple[str, int], float]    # the leader's push of each feature level on any outcome
    dealt: Mapping[str, tuple[float, ...]]  # engine gain with that feature dealt at random, each deal
    placebo: float                          # engine gain with features from the year after
    placebo_fair: bool                      # False: the year-after features count part of the outcome itself
    most_raised: tuple[tuple[str, float, float], ...]   # artist, chance from own past, with the leader
    years: tuple[tuple[int, float], ...]    # each scored year, engine minus own past


@dataclass(frozen=True)
class Rewarded:
    kind: str                               # "trend" or "medium"
    name: str
    approvals: int
    disapprovals: int
    approved: tuple[str, ...]
    disapproved: tuple[str, ...]


@dataclass(frozen=True)
class Success:
    year: int                               # the year described (years to September)
    forecast_for: int                       # the year the kinds of success are forecast for
    kinds: Mapping[str, SuccessKind]
    rewarded: tuple[Rewarded, ...]
    meanings: Mapping[str, str]             # feature -> what it records, in words
