"""
Success (REFACTOR_SPEC D31; abductive_engine ART-PLAN §12): what predicts
that an artist succeeds next year, in four senses kept apart, each judged
by the case engine (D29) offline over every artist-year and shipped with
the controls it faced and what critics rewarded this year.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
class LifeClaim:
    """A claim read as being about an artist's life (ART-PLAN §15.2), in a
    life block chosen for one kind of success (15.7)."""
    who: str
    when: str               # the date it was published
    claim: str              # "about: asserts"
    block: str              # the life block's name


@dataclass(frozen=True)
class AtTheTop:
    """What the press said this year about the artists who have one kind of
    success now (ART-PLAN §12.9): description, for a kind nothing predicts."""
    table_year: int                         # the latest table the artists are in
    artists: int
    themes: Mapping[str, tuple[int, int]]   # trend key -> (artists named, claims about them)
    media: Mapping[str, int]                # medium -> articles naming them with that tag
    said: Mapping[str, tuple[str, ...]]     # trend key -> the most recent claims about them in it


@dataclass(frozen=True)
class ThemeTest:
    """A theme's track record for one kind of success, tested on top of that
    kind's leader (ART-PLAN §14): features good_theme and poor_theme count
    claims in themes whose record, learned from earlier years, is above or
    below 0."""
    leader: tuple[str, ...]                 # with the records in the pool
    leader_since: Optional[int]
    gain: float
    gain_without: float                     # the kind's own leader, without the records
    effects: Mapping[tuple[str, int], float]
    dealt: Mapping[str, tuple[float, ...]]  # gain with each record feature dealt at random
    placebo: float
    year: int                               # the year the records shown are for
    best: tuple[tuple[str, float], ...]     # named themes with the best records, record
    worst: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Success:
    year: int                               # the year described (years to September)
    forecast_for: int                       # the year the kinds of success are forecast for
    kinds: Mapping[str, SuccessKind]
    rewarded: tuple[Rewarded, ...]
    meanings: Mapping[str, str]             # feature -> what it records, in words
    lists: Mapping[str, str]                # feature -> the trend list (TrendLists.lists) whose claims it counts
    media: Mapping[str, str]                # feature -> the medium (as Rewarded.name) whose articles it counts
    at_the_top: Mapping[str, AtTheTop]      # kind -> what the press said about those who have it now
    apart: tuple[str, ...] = ()             # kinds shown on their own: compared with the rest, never counted among them
    themes: Mapping[str, ThemeTest] = field(default_factory=dict)   # kind -> its theme test
    lives: Mapping[str, tuple[LifeClaim, ...]] = field(default_factory=dict)   # kind -> its imagined artist's claims
    life_tests: Mapping[str, ThemeTest] = field(default_factory=dict)       # kind -> its life-block test (15.7)
