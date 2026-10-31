"""What is said about the championed (abductive_engine ART-PLAN 15.12):
not what predicts a kind of success, but which life stories are told more
about the artists who had it in a year than their share of that year's
life talk. Description, not a cause."""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

PRIOR = 5.0       # as §14's record: a block with few claims stays near 0


def championed(rows: list[dict]) -> dict[int, set[str]]:
    """Year Y -> the artists who had the kind of success in Y: their row for
    Y - 1 has an outcome of one or more."""
    out: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        if r["outcome"]:
            out[r["year"] + 1].add(r["case"])
    return dict(out)


def latest(rows: list[dict]) -> int:
    """The latest year whose success is known."""
    return max(r["year"] for r in rows if r["outcome"] is not None) + 1


def champion_scores(champions: Mapping[int, set[str]],
                    life: Mapping[tuple[str, int], Mapping[str, int]]) -> dict[int, dict[str, float]]:
    """Year -> block -> score: life claims in the block about that year's
    CHAMPIONS, less what their share of all that year's life claims would
    give, over that plus PRIOR. LIFE is (artist, year) -> block -> claims."""
    by_year: dict = defaultdict(lambda: (defaultdict(int), defaultdict(int)))   # year -> (all, championed) by block
    for (artist, year), blocks in life.items():
        if year not in champions:
            continue
        every, theirs = by_year[year]
        for b, n in blocks.items():
            every[b] += n
            if artist in champions[year]:
                theirs[b] += n
    out = {}
    for year, (every, theirs) in by_year.items():
        share = sum(theirs.values()) / sum(every.values())
        out[year] = {b: (theirs[b] - n * share) / (n * share + PRIOR) for b, n in every.items()}
    return out
