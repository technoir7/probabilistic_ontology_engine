"""The artist as a graph of life stories (abductive_engine ART-PLAN 15.16):
an edge A -> B where a life story in block B is told about an artist in a
year more often, given one in A, than B's share of all lives. Description,
not a cause: it shows how an imagined life's stories go together; it does
not choose them."""
from __future__ import annotations

from collections import Counter
from itertools import permutations
from typing import Mapping

PRIOR = 5.0       # as §14's record and 15.12's score


def edges(life: Mapping[tuple[str, int], Mapping[str, int]]) -> dict[tuple[str, str], tuple[float, float, float]]:
    """(A, B) -> (P(B | A), P(B | A) / P(B), score) over the artist-years of
    LIFE ((artist, year) -> block -> claims), for the pairs told together
    more than by chance: score (both - expected) / (expected + PRIOR) above 0."""
    told = [{b for b, n in blocks.items() if n > 0} for blocks in life.values()]
    told = [t for t in told if t]
    alone = Counter(b for t in told for b in t)
    both = Counter(pair for t in told for pair in permutations(sorted(t), 2))
    out = {}
    for (a, b), n in both.items():
        share = alone[b] / len(told)
        expected = alone[a] * share
        score = (n - expected) / (expected + PRIOR)
        if score > 0:
            p = n / alone[a]
            out[(a, b)] = (p, p / share, score)
    return out
