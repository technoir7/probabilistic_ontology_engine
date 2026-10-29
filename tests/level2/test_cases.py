"""Cases mode (REFACTOR_SPEC D29): a mechanism judged across many cases at
once, every set of mechanisms a rival scheme, each year predicted from the
years before against each case's own past."""
from __future__ import annotations

import random

from src.engine.model.cases import CaseSet, CaseYear, doubling, level
from src.engine.services.cases import case_report


def test_levels_are_none_one_several_and_doubling_grades_size_finely():
    assert [level(n) for n in (0, 1, 2, 7)] == [0, 1, 2, 2]
    assert [doubling(n) for n in (0, 1, 2, 3, 4, 5, 8, 9, 16, 17, 400)] == [0, 1, 2, 3, 3, 4, 4, 5, 5, 6, 6]


def _year(y, n, rng, matters, case=None):
    rows = []
    for i in range(n):
        own, f, g = rng.randrange(4), rng.randrange(2), rng.randrange(2)
        outcome = 2 * f if matters else rng.choice((0, 0, 1, 2))
        rows.append(CaseYear(y, (own,), {"f": f, "g": g}, outcome, case=case and f"{case}{i}"))
    return rows


def test_a_report_judges_the_closed_years_and_forecasts_the_open_one_by_its_leader():
    rng = random.Random(2)
    closed = [r for y in range(2000, 2010) for r in _year(y, 200, rng, True)]
    open_year = [CaseYear(2010, (0,), {"f": 1, "g": 0}, None, case="x"),
                 CaseYear(2010, (0,), {"f": 0, "g": 0}, None, case="y")]
    report = case_report(CaseSet("t", "Test", ("f", "g"), tuple(closed + open_year), {"x": "the x"}))
    assert report.leader == ("f",)
    assert [y.year for y in report.years] == list(range(2001, 2010))   # the first year is only learned
    assert report.gain > 500
    assert report.forecast_year == 2010
    # Raised by the leader: x only; y's chance the leader lowered.
    [top] = report.most_raised
    assert (top.case, top.label) == ("x", "the x")
    assert abs(sum(top.with_leader) - 1) < 1e-9 and abs(sum(top.own_past) - 1) < 1e-9
    assert top.with_leader[2] > 0.95 > top.own_past[2]


def test_a_report_scores_every_rival_set_of_mechanisms_against_own_past():
    rng = random.Random(5)
    closed = [r for y in range(2000, 2010) for r in _year(y, 200, rng, True)]
    report = case_report(CaseSet("t", "Test", ("f", "g"), tuple(closed)))
    gains = {m.features: m.gain for m in report.mechanisms}
    assert set(gains) == {("f",), ("g",), ("f", "g")}                   # own past is the baseline, not a rival
    assert gains[("f",)] > 500 and gains[("g",)] <= 0
    assert gains[("f",)] == max(gains.values())
    assert [m.features for m in report.mechanisms] == sorted(gains, key=lambda k: -gains[k])


def test_the_most_raised_are_ranked_by_how_much_the_leader_raises_their_chance():
    rng = random.Random(4)
    closed = [r for y in range(2000, 2010) for r in _year(y, 200, rng, True)]
    open_year = [CaseYear(2010, (3,), {"f": 1, "g": 0}, None, case="a"),
                 CaseYear(2010, (0,), {"f": 1, "g": 1}, None, case="b"),
                 CaseYear(2010, (1,), {"f": 0, "g": 0}, None, case="c")]
    report = case_report(CaseSet("t", "Test", ("f", "g"), tuple(closed + open_year)))
    raised = [f.with_leader[0] - f.own_past[0] for f in report.most_raised]
    assert raised == sorted(raised) and all(x < 0 for x in raised)


def test_a_case_set_with_no_open_year_has_no_forecast():
    rng = random.Random(3)
    closed = [r for y in range(2000, 2004) for r in _year(y, 50, rng, False)]
    report = case_report(CaseSet("t", "Test", ("f", "g"), tuple(closed), {}))
    assert report.forecast_year is None and report.most_raised == ()


def test_a_report_says_which_way_the_leaders_mechanisms_push():
    rng = random.Random(5)
    closed = [r for y in range(2000, 2010) for r in _year(y, 200, rng, True)]
    report = case_report(CaseSet("t", "Test", ("f", "g"), tuple(closed)))
    assert report.leader == ("f",) and report.effects[("f", 1)] > 1
