"""Which themes help (abductive_engine ART-PLAN §14): §12 tested "a claim in
some theme on this list", never a theme. Here each theme gets a track
record for one kind of success, learned only from earlier years, and each
artist-year two features from it: claims in themes with a good record, and
in themes with a poor one."""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from .artist_years import level

PRIOR = 5.0       # expected successes added below the line, so a theme with few cases stays near 0


def track_records(rows: list[dict], claims: Mapping[tuple[str, int], Mapping[str, int]]) -> dict[int, dict[str, float]]:
    """Year Y -> theme -> record for Y, from the closed artist-years before
    Y: over those with a claim about the artist in the theme, successes next
    year (outcome one or several) less expected, over expected plus PRIOR.
    Expected is the success rate that year among all artists with the same
    amount of the success so far (own[0])."""
    closed = [r for r in rows if r["outcome"] is not None]
    tally: dict = defaultdict(lambda: [0, 0])
    for r in closed:
        t = tally[(r["year"], r["own"][0])]
        t[0] += r["outcome"] >= 1
        t[1] += 1
    seen: dict = defaultdict(lambda: [0.0, 0.0])          # theme -> [observed, expected], so far
    by_year = defaultdict(list)
    for r in closed:
        by_year[r["year"]].append(r)
    out = {}
    for y in sorted({r["year"] for r in rows}):
        out[y] = {t: (o - e) / (e + PRIOR) for t, (o, e) in seen.items()}
        for r in by_year.get(y, []):
            hits, n = tally[(y, r["own"][0])]
            for t in claims.get((r["case"], y), {}):
                seen[t][0] += r["outcome"] >= 1
                seen[t][1] += hits / n
    return out


def with_theme_features(rows: list[dict], claims: Mapping[tuple[str, int], Mapping[str, int]],
                        records: Mapping[int, Mapping[str, float]]) -> list[dict]:
    """Each artist-year with two more features, graded none / one / several:
    claims about the artist in themes whose record that year is above 0, and
    below 0."""
    out = []
    for r in rows:
        rec = records.get(r["year"], {})
        mine = claims.get((r["case"], r["year"]), {})
        good = sum(n for t, n in mine.items() if rec.get(t, 0.0) > 0)
        poor = sum(n for t, n in mine.items() if rec.get(t, 0.0) < 0)
        out.append(dict(r, features=dict(r["features"], good_theme=level(good), poor_theme=level(poor))))
    return out
