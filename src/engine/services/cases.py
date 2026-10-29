"""
The engine on cases (REFACTOR_SPEC D29; abductive_engine ART-PLAN §9,
amended 2026-10-29). Every set of mechanisms from a small pool is a rival
scheme: a multinomial logistic model of each case's outcome next year on
its own past (one term per own-past grade) plus one term per mechanism
level, fitted on the years before only, then scored on the year. A
mechanism that adds nothing to the others gets a term near zero and costs
next to nothing, and each term says which way its mechanism pushes. (The
first engine split count tables by every mechanism at once, so a
combination relearned its parts in every cell and lost to them whatever
it added.) Standing is each scheme's score, decayed with a 5-year
half-life; the leader changes only when a rival stands SHIFT_NATS ahead,
a combination may lead only when it stands that far ahead of each of its
parts, and each change is recorded as a shift in what drives the cases.
Fitting is L-BFGS on the case-years seen so far, grouped by their values
and warm-started from last year's terms: 2^len(pool) fits a year.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Mapping, Optional

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from ..model.cases import LEVELS, CaseSet, CaseYear

HALF_LIFE_YEARS = 5
SHIFT_NATS = 3.0           # Jeffreys' "strong"
_DECAY = 0.5 ** (1 / HALF_LIFE_YEARS)
FORECAST_ROWS = 20
OWN_SD = 3.0          # prior sd of an own-past term: weak, as the tables' own-past cells were
MECHANISM_SD = 1.0    # prior sd of a mechanism term: a log-odds of one either way is unremarkable


class _Data:
    """Every case-year learned, grouped by own past, mechanism values and
    outcome, with the codes the schemes' terms are built from."""

    def __init__(self, pool: tuple[str, ...]):
        self.pool = pool
        self.own_codes: dict[tuple, int] = {}
        self.levels: dict[str, list[int]] = {f: [] for f in pool}   # nonzero levels seen, per mechanism
        self.counts: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * LEVELS)

    def learn(self, rows: Iterable[CaseYear]) -> None:
        for r in rows:
            self.own_codes.setdefault(r.own, len(self.own_codes))
            for f in self.pool:
                v = r.features[f]
                if v and v not in self.levels[f]:
                    self.levels[f].append(v)
                    self.levels[f].sort()
            self.counts[(r.own, tuple(r.features[f] for f in self.pool))][r.outcome] += r.weight


class CaseScheme:
    def __init__(self, features: tuple[str, ...], data: _Data):
        self.features = features
        self._data = data
        self._terms: Optional[np.ndarray] = None     # (columns, LEVELS - 1); outcome 0 is the reference
        self._columns: list = []
        self._index: dict = {}

    # Columns: intercept, one per own-past grade, one per (mechanism, nonzero level).
    def _layout(self) -> list:
        return (["intercept"] + [("own", o) for o in self._data.own_codes]
                + [(f, v) for f in self.features for v in self._data.levels[f]])

    @staticmethod
    def _row(own: tuple, values: dict, features: tuple, index: dict) -> np.ndarray:
        x = np.zeros(len(index))
        x[0] = 1.0
        if ("own", own) in index:
            x[index[("own", own)]] = 1.0
        for f in features:
            if (f, values[f]) in index:
                x[index[(f, values[f])]] = 1.0
        return x

    def fit(self) -> None:
        columns = self._layout()
        pos = {f: i for i, f in enumerate(self._data.pool)}
        grouped: dict = defaultdict(lambda: np.zeros(LEVELS))
        for (own, values), n in self._data.counts.items():
            grouped[(own, tuple(values[pos[f]] for f in self.features))] += n
        keys = list(grouped)
        index = {c: i for i, c in enumerate(columns)}
        X = np.array([self._row(own, dict(zip(self.features, v)), self.features, index) for own, v in keys])
        N = np.array([grouped[k] for k in keys])
        sd = np.array([np.inf] + [OWN_SD if isinstance(c, tuple) and c[0] == "own" else MECHANISM_SD
                                  for c in columns[1:]])
        precision = (1 / sd ** 2)[:, None]
        start = np.zeros((len(columns), LEVELS - 1))
        if self._terms is not None:                       # warm start: last year's terms where columns persist
            old = {c: i for i, c in enumerate(self._columns)}
            for i, c in enumerate(columns):
                if c in old:
                    start[i] = self._terms[old[c]]

        def loss(flat):
            W = flat.reshape(start.shape)
            Z = np.hstack([np.zeros((len(X), 1)), X @ W])
            logp = Z - logsumexp(Z, axis=1, keepdims=True)
            P = np.exp(logp)
            total = N.sum(axis=1, keepdims=True)
            value = -(N * logp).sum() + 0.5 * (precision * W ** 2).sum()
            grad = X.T @ (P[:, 1:] * total - N[:, 1:]) + precision * W
            return value, grad.ravel()
        out = minimize(loss, start.ravel(), jac=True, method="L-BFGS-B", options={"gtol": 1e-9, "ftol": 1e-15, "maxiter": 5000})
        # An abnormal line search means no further step could be taken at
        # machine precision, i.e. converged; anything else is a failure.
        if not out.success and "ABNORMAL" not in str(out.message):
            raise RuntimeError(f"fit of {self.features or 'own past'} failed: {out.message}")
        self._terms, self._columns, self._index = out.x.reshape(start.shape), columns, index

    def predict(self, r: CaseYear) -> list[float]:
        if self._terms is None:
            return [1 / LEVELS] * LEVELS
        z = np.concatenate([[0.0], self._row(r.own, r.features, self.features, self._index) @ self._terms])
        return list(np.exp(z - logsumexp(z)))

    def effects(self) -> dict[tuple, float]:
        """Each mechanism level's push on the log-odds of any outcome against
        none, at the average own past: positive helps, negative hurts."""
        if self._terms is None:
            return {}
        base = self._terms[0] + np.mean([self._terms[i] for i, c in enumerate(self._columns)
                                         if isinstance(c, tuple) and c[0] == "own"] or [np.zeros(LEVELS - 1)], axis=0)
        any_base = logsumexp(base)
        return {c: float(logsumexp(base + self._terms[i]) - any_base)
                for i, c in enumerate(self._columns) if isinstance(c, tuple) and c[0] != "own"}


class CaseEngine:
    def __init__(self, pool: tuple[str, ...]):
        self._data = _Data(pool)
        sets = [c for k in range(len(pool) + 1) for c in combinations(pool, k)]
        self.schemes = {s: CaseScheme(s, self._data) for s in sets}
        self.leader: tuple = ()
        self.shifts: list[Shift] = []
        self._standing = {s: 0.0 for s in sets}
        self.last_scores: dict[tuple, float] = {}

    def step(self, year: int, rows: list[CaseYear]) -> tuple[float, float]:
        """Score one year by the models fitted on the years before, then learn
        it and refit. Returns the leader's score (chosen before the year was
        seen) and own past's."""
        scores = {s: sum(r.weight * math.log(sc.predict(r)[r.outcome]) for r in rows)
                  for s, sc in self.schemes.items()}
        self.last_scores = scores
        result = (scores[self.leader], scores[()])
        for s in self.schemes:
            self._standing[s] = _DECAY * self._standing[s] + scores[s]
        self._data.learn(rows)
        for sc in self.schemes.values():
            sc.fit()
        # A combination may lead only when it stands strongly ahead of each
        # of its parts: its extra mechanism has to earn its place.
        earned = [s for s in self.schemes
                  if all(self._standing[s] - self._standing[tuple(f for f in s if f != x)] > SHIFT_NATS for x in s)]
        best = max(earned, key=self._standing.get)
        if best != self.leader and self._standing[best] - self._standing[self.leader] > SHIFT_NATS:
            self.shifts.append(Shift(year, self.leader, best))
            self.leader = best
        return result


@dataclass(frozen=True)
class Shift:
    year: int
    frm: tuple
    to: tuple


@dataclass(frozen=True)
class YearScore:
    year: int
    engine: float      # log score of the leader chosen before the year
    own_past: float
    cases: int


@dataclass(frozen=True)
class MechanismScore:
    features: tuple
    gain: float        # nats over own past, all scored years


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
    mechanisms: tuple[MechanismScore, ...]   # every rival set, best first
    forecast_year: Optional[int]
    most_raised: tuple[Forecast, ...]   # whose chance the leader raises most over own past
    meanings: Mapping[str, str] = field(default_factory=dict)

    def describe(self, features: tuple) -> str:
        """A set of mechanisms in words; none is each case's own past alone."""
        return " + ".join(self.meanings.get(f, f) for f in features) or "each case's own past alone"

    @property
    def gain(self) -> float:
        """Nats the engine's leaders won over own past, all scored years."""
        return sum(y.engine - y.own_past for y in self.years)


def case_report(cases: CaseSet, top: int = FORECAST_ROWS) -> CaseReport:
    """Run the engine over every closed year (the first only learned), then
    forecast the open year's cases by the final leader and by own past
    alone: the TOP whose chance the leader raises most (what the mechanisms
    add; the likeliest cases are mostly the big ones, which own past alone
    names). Every rival set's gain over own past is reported too. Fits
    2^len(pool) models a year: seconds for art's sets, so callers cache it."""
    closed: dict[int, list[CaseYear]] = defaultdict(list)
    open_rows = []
    for r in cases.records:
        (open_rows if r.outcome is None else closed[r.year]).append(r)
    engine, years = CaseEngine(cases.pool), []
    gains = {s: 0.0 for s in engine.schemes if s}
    for i, y in enumerate(sorted(closed)):
        e, o = engine.step(y, closed[y])
        if i > 0:
            years.append(YearScore(y, e, o, sum(r.weight for r in closed[y])))
            for s in gains:
                gains[s] += engine.last_scores[s] - o
    leader, own = engine.schemes[engine.leader], engine.schemes[()]
    rows = [Forecast(r.case, cases.labels.get(r.case, r.case), tuple(own.predict(r)), tuple(leader.predict(r)))
            for r in open_rows]
    raised = sorted((f for f in rows if f.with_leader[0] < f.own_past[0]),
                    key=lambda f: (f.with_leader[0] - f.own_past[0], f.label))
    return CaseReport(cases.key, cases.title, cases.outcome, cases.pool, engine.leader, tuple(engine.shifts),
                      tuple(years), tuple(MechanismScore(s, g) for s, g in sorted(gains.items(), key=lambda kv: -kv[1])),
                      open_rows[0].year if open_rows else None, tuple(raised[:top]), cases.meanings)
