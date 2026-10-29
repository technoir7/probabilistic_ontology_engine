"""Controls for the success test (abductive_engine ART-PLAN §12.3)."""
from collections import Counter

from evals.success_run import dealt, placebo


def _rows():
    return [{"year": y, "own": [0, 0], "features": {"f": (i + y) % 3, "g": i % 2}, "outcome": i % 3, "case": f"c{i}"}
            for y in (2001, 2002, 2003) for i in range(30)]


def test_dealing_moves_a_features_values_between_cases_within_each_year_and_nothing_else():
    rows = _rows()
    out = dealt(rows, "f", seed=0)
    for y in (2001, 2002, 2003):
        before = [r for r in rows if r["year"] == y]
        after = [r for r in out if r["year"] == y]
        assert Counter(r["features"]["f"] for r in before) == Counter(r["features"]["f"] for r in after)
        assert [r["features"]["g"] for r in before] == [r["features"]["g"] for r in after]
        assert [r["outcome"] for r in before] == [r["outcome"] for r in after]
    assert [r["features"]["f"] for r in out] != [r["features"]["f"] for r in rows]


def test_the_placebo_gives_each_case_year_its_features_from_the_year_after():
    rows = _rows()
    out = placebo(rows)
    assert {r["year"] for r in out} == {2001, 2002}                     # 2003 has no year after
    first = next(r for r in out if r["year"] == 2001 and r["case"] == "c4")
    assert first["features"] == next(r for r in rows if r["year"] == 2002 and r["case"] == "c4")["features"]
    assert first["outcome"] == next(r for r in rows if r["year"] == 2001 and r["case"] == "c4")["outcome"]
