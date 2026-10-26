"""
Replay 17 (evals/README.md): artist by artist, does one consecrating body's
attention last year help predict another's this year?

Each year is predicted before it is seen, from counts over earlier years
only, under two rivals: the target's own past (last year's level and its
standing, the level of its total over all earlier years), and own past plus
the other body's level last year. Each table cell's probabilities are the
counts plus one (a uniform Dirichlet prior), so a rival with more cells
pays for them in the prediction itself: the difference of the summed log
scores is the log Bayes factor between them.

A panel is {artist: {signal: {year: count}}}; a missing year is 0 for a
museum (nothing acquired) and unread for a paper outside its years.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

Panel = Mapping[str, Mapping[str, Mapping[int, int]]]
LEVELS = 3


def level(count: int) -> int:
    """None, one, several."""
    return min(count, 2)


@dataclass
class Comparison:
    gain: float = 0.0                       # nats, own past + other over own past: the log Bayes factor
    cases: int = 0
    by_year: dict[int, float] = field(default_factory=dict)   # nats per artist-year


def _features(series: Mapping[str, Mapping[int, int]], target: str, other: str, year: int, lag: int):
    t, o = series.get(target, {}), series.get(other, {})
    standing = level(sum(c for y, c in t.items() if y < year - 1))
    own = (level(t.get(year - 1, 0)), standing)
    return own, own + (level(o.get(year - lag, 0)),)


def _log_p(counts: list[int], y: int) -> float:
    return math.log((counts[y] + 1) / (sum(counts) + LEVELS))


def compare(panel: Panel, target: str, other: str, years: Iterable[int], lag: int = 1) -> Comparison:
    """LAG 1 reads the other body last year. LAG -1, next year, is a placebo
    for a shared trend: it is not a prediction (it reads the future) and is
    used only to compare with LAG 1."""
    years = sorted(years)
    tables = {"own": defaultdict(lambda: [0] * LEVELS), "both": defaultdict(lambda: [0] * LEVELS)}
    out = Comparison()
    for year in years[1:]:            # the first year is only last year for the second
        rows = [(_features(s, target, other, year, lag), level(s.get(target, {}).get(year, 0))) for s in panel.values()]
        if year >= years[2]:          # scored once a year of counts exists
            gain = 0.0
            for (own, both), y in rows:
                gain += _log_p(tables["both"][both], y) - _log_p(tables["own"][own], y)
            out.gain += gain
            out.cases += len(rows)
            out.by_year[year] = gain / len(rows)
        for (own, both), y in rows:   # learned only after the year is scored
            tables["own"][own][y] += 1
            tables["both"][both][y] += 1
    return out


def shuffled(panel: Panel, rng: random.Random, years: Iterable[int]) -> dict:
    """Each artist's YEARS permuted, all signals together: fame kept, order
    lost. Years with nothing recorded move too."""
    years = sorted(years)
    out = {}
    for artist, series in panel.items():
        moved = dict(zip(years, rng.sample(years, len(years))))
        out[artist] = {sig: {moved[y]: c for y, c in s.items() if y in moved} for sig, s in series.items()}
    return out
