"""The artist as a graph of life stories (abductive_engine ART-PLAN 15.16):
directed edges between life blocks told about the same artist in the same
year more than by chance."""
import pytest

from evals.life_graph import PRIOR, edges


LIFE = {("a", 2020): {"A": 1, "B": 2}, ("b", 2020): {"A": 1, "B": 1}, ("c", 2020): {"A": 3},
        ("d", 2021): {"C": 1}, ("e", 2021): {"B": 1, "C": 1}, ("f", 2021): {"C": 2}}


def test_an_edge_is_how_often_b_is_told_with_a_beyond_its_share():
    e = edges(LIFE)
    # 6 artist-years with a life claim; B in 3; A in 3, of which 2 also have B
    p, times, score = e[("A", "B")]
    assert p == pytest.approx(2 / 3) and times == pytest.approx((2 / 3) / (3 / 6))
    assert score == pytest.approx((2 - 3 * 3 / 6) / (3 * 3 / 6 + PRIOR))
    assert ("A", "C") not in e                 # never told together: below chance, not kept
    assert ("B", "A") in e and e[("B", "A")][0] == pytest.approx(2 / 3)
