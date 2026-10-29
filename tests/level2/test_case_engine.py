"""The case engine (abductive_engine ART-PLAN §9, amended): each set of
mechanisms a multinomial logistic model on each case's own past plus one
term per mechanism level, fitted on the years before, scored on the year."""
from __future__ import annotations

import random

from src.engine.model.cases import CaseYear
from src.engine.services.cases import CaseEngine


def _thin(seed, effect, own_grades=30, n=300):
    """Cases with many own-past grades and few cases each, as thin as art's,
    the outcome set by EFFECT(f, g)."""
    rng = random.Random(seed)

    def rows(y):
        out = []
        for _ in range(n):
            f, g = rng.randrange(2), rng.randrange(2)
            out.append(CaseYear(y, (rng.randrange(own_grades),), {"f": f, "g": g}, 2 if rng.random() < effect(f, g) else 0))
        return out
    return rows


def _gains(engine, years, rows_of):
    gains = {s: 0.0 for s in engine.schemes}
    for i, y in enumerate(years):
        o = engine.step(y, rows_of(y))[1]
        if i:
            for s in gains:
                gains[s] += engine.last_scores[s] - o
    return gains


def test_noise_never_takes_the_lead():
    engine = CaseEngine(("f", "g"))
    gains = _gains(engine, range(2000, 2015), _thin(1, lambda f, g: 0.2))
    assert engine.leader == () and engine.shifts == []
    assert all(v < 3 for k, v in gains.items() if k)


def test_a_useless_mechanism_added_to_a_useful_one_costs_next_to_nothing():
    engine = CaseEngine(("f", "g"))
    gains = _gains(engine, range(2000, 2015), _thin(5, lambda f, g: 0.4 if f else 0.1))
    assert gains[("f",)] > 100
    assert gains[("f", "g")] > gains[("f",)] - 5
    assert engine.leader == ("f",)


def test_two_mechanisms_that_each_matter_lead_together():
    engine = CaseEngine(("f", "g"))
    gains = _gains(engine, range(2000, 2015), _thin(6, lambda f, g: 0.05 + 0.25 * f + 0.25 * g))
    assert engine.leader == ("f", "g")
    assert gains[("f", "g")] > max(gains[("f",)], gains[("g",)]) + 30


def test_a_mechanism_that_starts_to_matter_takes_the_lead_after_it_does():
    engine = CaseEngine(("f", "g"))
    _gains(engine, range(2000, 2015), _thin(7, lambda f, g: 0.2))           # warm up on noise
    rows = _thin(8, lambda f, g: 0.5 if f else 0.1)
    for y in range(2015, 2025):
        engine.step(y, rows(y))
    assert engine.leader == ("f",) and engine.shifts[-1].year >= 2015


def test_a_weighted_record_counts_as_that_many_identical_cases():
    rows_of = _thin(9, lambda f, g: 0.4 if f else 0.1, own_grades=3, n=60)
    years = {y: rows_of(y) for y in range(2000, 2006)}
    one, many = CaseEngine(("f",)), CaseEngine(("f",))
    for y, rows in years.items():
        merged: dict = {}
        for r in rows:
            k = (r.own, r.features["f"], r.outcome)
            merged[k] = merged.get(k, 0) + 1
        weighted = [CaseYear(y, own, {"f": f}, o, weight=w) for (own, f, o), w in merged.items()]
        a, b = one.step(y, rows), many.step(y, weighted)
        assert abs(a[1] - b[1]) < 1e-4 and abs(one.last_scores[("f",)] - many.last_scores[("f",)]) < 1e-4


def test_a_scheme_says_which_way_each_mechanism_pushes():
    engine = CaseEngine(("f", "g"))
    _gains(engine, range(2000, 2012), _thin(10, lambda f, g: 0.4 if f else 0.1))
    effects = engine.schemes[("f", "g")].effects()          # mechanism level -> change in log-odds of any outcome
    assert effects[("f", 1)] > 0.5 and abs(effects[("g", 1)]) < 0.3
