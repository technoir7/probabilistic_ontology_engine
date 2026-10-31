"""What is said about the championed (abductive_engine ART-PLAN 15.12):
the artists who had a kind of success in a year, and which life blocks are
told more about them than their share of that year's life talk."""
import pytest

from evals.champions import PRIOR, champion_scores, championed, latest


def _rows():
    """c0 and c1 have the success in 2002 (their 2001 rows), c2 in 2003; 2003 is open."""
    out = []
    for y, hits in ((2001, {"c0", "c1"}), (2002, {"c2"}), (2003, None)):
        for c in ("c0", "c1", "c2", "c3"):
            out.append({"year": y, "case": c, "own": [0, 0], "features": {},
                        "outcome": None if hits is None else int(c in hits) * 2})
    return out


def test_the_championed_in_a_year_are_those_with_the_success_that_year():
    assert championed(_rows()) == {2002: {"c0", "c1"}, 2003: {"c2"}}
    assert latest(_rows()) == 2003


def test_a_block_scores_by_how_much_more_it_is_told_about_the_championed_than_their_share():
    # 2002: the championed hold 4 of 8 life claims, so each block is expected half its claims about them
    life = {("c0", 2002): {"A": 3}, ("c1", 2002): {"B": 1},
            ("c2", 2002): {"A": 1, "B": 3}, ("c3", 2001): {"A": 5}}
    scores = champion_scores({2002: {"c0", "c1"}}, life)
    assert scores[2002]["A"] == pytest.approx((3 - 2) / (2 + PRIOR))
    assert scores[2002]["B"] == pytest.approx((1 - 2) / (2 + PRIOR))
    assert set(scores) == {2002}                   # 2001 has no championed artists


def test_a_year_with_no_life_claims_about_the_championed_scores_every_block_zero():
    scores = champion_scores({2002: {"c9"}}, {("c3", 2002): {"A": 2}})
    assert scores[2002] == {"A": 0.0}
