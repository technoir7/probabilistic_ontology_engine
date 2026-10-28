"""
The engine on cases (REFACTOR_SPEC D29; abductive_engine ART-PLAN §9).
Every set of mechanisms from a small pool is a rival scheme. Each predicts
every case's outcome from its own past and its mechanisms before the year is
seen, by count tables whose split cells start from the own-past cell's
prediction (backoff), so a mechanism that says nothing costs next to
nothing. Standing is each scheme's score, decayed with a 5-year half-life;
the leader changes only when a rival stands SHIFT_NATS ahead, and each
change is recorded as a shift in what drives the cases.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Optional

from ..model.cases import LEVELS, CaseSet, CaseYear

HALF_LIFE_YEARS = 5
SHIFT_NATS = 3.0           # Jeffreys' "strong"
_DECAY = 0.5 ** (1 / HALF_LIFE_YEARS)
BACKOFF_WEIGHT = LEVELS    # as much as the uniform prior's, no more
FORECAST_ROWS = 20


def _p_backoff(counts: list[int], y: int, base: list[int]) -> float:
    prior = (base[y] + 1) / (sum(base) + LEVELS)
    return (counts[y] + BACKOFF_WEIGHT * prior) / (sum(counts) + BACKOFF_WEIGHT)


class CaseScheme:
    def __init__(self, features: tuple[str, ...]):
        self.features = features
        self._own: dict = defaultdict(lambda: [0] * LEVELS)
        self._cells: dict = defaultdict(lambda: [0] * LEVELS)

    def _cell(self, r: CaseYear) -> list[int]:
        return self._cells[(r.own,) + tuple(r.features[f] for f in self.features)]

    def predict(self, r: CaseYear) -> list[float]:
        cell, base = self._cell(r), self._own[r.own]
        return [_p_backoff(cell, y, base) for y in range(LEVELS)]

    def score(self, rows: Iterable[CaseYear]) -> float:
        return sum(r.weight * math.log(_p_backoff(self._cell(r), r.outcome, self._own[r.own])) for r in rows)

    def learn(self, rows: Iterable[CaseYear]) -> None:
        for r in rows:
            self._own[r.own][r.outcome] += r.weight
            self._cell(r)[r.outcome] += r.weight


@dataclass(frozen=True)
class Shift:
    year: int
    frm: tuple
    to: tuple


class CaseEngine:
    def __init__(self, pool: tuple[str, ...]):
        sets = [c for k in range(len(pool) + 1) for c in combinations(pool, k)]
        self.schemes = {s: CaseScheme(s) for s in sets}
        self.leader: tuple = ()
        self.shifts: list[Shift] = []
        self._standing = {s: 0.0 for s in sets}

    def step(self, year: int, rows: list[CaseYear]) -> tuple[float, float]:
        """Score and learn one year. Returns the engine's score (its leader's,
        chosen before the year was seen) and own past's."""
        scores = {s: scheme.score(rows) for s, scheme in self.schemes.items()}
        result = (scores[self.leader], scores[()])
        for s, scheme in self.schemes.items():
            self._standing[s] = _DECAY * self._standing[s] + scores[s]
            scheme.learn(rows)
        best = max(self._standing, key=self._standing.get)
        if best != self.leader and self._standing[best] - self._standing[self.leader] > SHIFT_NATS:
            self.shifts.append(Shift(year, self.leader, best))
            self.leader = best
        return result


@dataclass(frozen=True)
class YearScore:
    year: int
    engine: float      # log score of the leader chosen before the year
    own_past: float
    cases: int


@dataclass(frozen=True)
class Forecast:
    case: str
    label: str
    own_past: tuple[float, ...]      # chance of none, one, several
    with_leader: tuple[float, ...]


@dataclass(frozen=True)
class CaseReport:
    key: str
    title: str
    outcome: str
    pool: tuple[str, ...]
    leader: tuple
    shifts: tuple[Shift, ...]
    years: tuple[YearScore, ...]
    forecast_year: Optional[int]
    likeliest: tuple[Forecast, ...]     # most likely to see the outcome at all
    most_raised: tuple[Forecast, ...]   # whose chance the leader raises most over own past

    @property
    def gain(self) -> float:
        """Nats the engine's leaders won over own past, all scored years."""
        return sum(y.engine - y.own_past for y in self.years)


def case_report(cases: CaseSet, top: int = FORECAST_ROWS) -> CaseReport:
    """Run the engine over every closed year (the first only learned), then
    forecast the open year's cases by the final leader and by own past
    alone: the TOP most likely to see the outcome at all, and the TOP whose
    chance the leader raises most (what the mechanisms add; own past alone
    mostly says big cases stay big). Learns 2^len(pool) tables over every
    record: under a second for art's sets, but callers should cache it."""
    closed: dict[int, list[CaseYear]] = defaultdict(list)
    open_rows = []
    for r in cases.records:
        (open_rows if r.outcome is None else closed[r.year]).append(r)
    engine, years = CaseEngine(cases.pool), []
    for i, y in enumerate(sorted(closed)):
        e, o = engine.step(y, closed[y])
        if i > 0:
            years.append(YearScore(y, e, o, sum(r.weight for r in closed[y])))
    leader, own = engine.schemes[engine.leader], engine.schemes[()]
    rows = [Forecast(r.case, cases.labels.get(r.case, r.case), tuple(own.predict(r)), tuple(leader.predict(r)))
            for r in open_rows]
    likeliest = sorted(rows, key=lambda f: (f.with_leader[0], f.label))
    raised = sorted((f for f in rows if f.with_leader[0] < f.own_past[0]),
                    key=lambda f: (f.with_leader[0] - f.own_past[0], f.label))
    return CaseReport(cases.key, cases.title, cases.outcome, cases.pool, engine.leader, tuple(engine.shifts),
                      tuple(years), open_rows[0].year if open_rows else None, tuple(likeliest[:top]), tuple(raised[:top]))
