"""The work most likely to succeed now (abductive_engine ART-PLAN §12.3):
every artist in replay 17's panel, by year, with features from the press
and four kinds of success the year after, as case sets for the case
engine (services/cases.py).

Features of an artist's year, each graded none / one / several:
- new_trend, growing_trend, fading_trend, argued_trend: claims whose subject
  names the artist (reception.linked) and whose trend is on that list that
  year (abductive_engine evals/export_trend_status.py);
- painting, photography, sculpture: articles naming the artist with that
  medium tag (the Guardian tags all three; the NYT only photography and
  sculpture, so painting is the Guardian's);
- nyt: NYT articles naming the artist, the existing leader for museums.
Outcomes: critics' approvals; articles in either paper; Chicago and
Cleveland acquisitions; place in Artprice's Top 500 by auction turnover
(evals/artprice.py), only in years with a table.

    uv run python -m evals.success_records OUT_DIR     # writes four case sets"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Optional

from src.domains.art_prestige_regime_v1 import cases
from src.domains.art_prestige_regime_v1.success import POOL
from src.engine.model.cases import doubling

from .art_artists import cma_person, normalise, nyt_person
from .artist_years import level
from .artprice import REPORTS, key
from .reception import linked
from .replay17 import DATA, TEXTS

YEARS = range(2003, 2026)      # trend lists start in 2003; 2025 is open
LISTS = {"new": "new_trend", "growing": "growing_trend", "fading": "fading_trend", "argued": "argued_trend"}
MEDIA = {("guardian", "artanddesign/painting"): "painting", ("guardian", "artanddesign/photography"): "photography",
         ("guardian", "artanddesign/sculpture"): "sculpture", ("nyt", "Photography"): "photography",
         ("nyt", "Sculpture"): "sculpture"}
UNKNOWN = 3                    # the open year without a table


def _features(s: Mapping, year: int, pool: tuple[str, ...]) -> dict:
    return {f: level(s.get(f, {}).get(year, 0)) for f in pool}


def count_records(people: Mapping, outcome: tuple[str, ...], years: Iterable[int], pool: tuple[str, ...]) -> list[dict]:
    """One record per artist and state year: the OUTCOME series summed this
    year and before (own past, graded finely) and next year (none / one /
    several); the last year is open."""
    years = sorted(years)
    out = []
    for name, s in people.items():
        total = defaultdict(int)
        for series in outcome:
            for y, n in s.get(series, {}).items():
                total[y] += n
        for state in years:
            before = sum(n for y, n in total.items() if y < state)
            out.append({"year": state, "own": [doubling(total.get(state, 0)), doubling(before)],
                        "features": _features(s, state, pool),
                        "outcome": level(total.get(state + 1, 0)) if state < years[-1] else None, "case": name})
    return out


def market_level(rank: Optional[int]) -> int:
    return 0 if rank is None else 2 if rank <= 100 else 1


def market_records(people: Mapping, ranks: Mapping[str, Mapping[int, int]], covered: set[int],
                   years: Iterable[int], pool: tuple[str, ...]) -> list[dict]:
    """As count_records, with an artist's Top 500 place for outcome and own
    past. A closed state year is a case only when it, the next year and some
    earlier year all have a table (ART-PLAN §12 deviations 2 and 3): with an
    own past unknown, press coverage would stand in for it. In the open year
    a missing place is graded UNKNOWN."""
    years = sorted(years)
    out = []
    for name, s in people.items():
        r = ranks.get(name, {})

        def at(y):
            return market_level(r.get(y)) if y in covered else UNKNOWN
        for state in years:
            last = state == years[-1]
            seen = [market_level(r.get(y)) for y in covered if y < state]
            if not last and (state not in covered or state + 1 not in covered or not seen):
                continue
            out.append({"year": state, "own": [at(state), max(seen) if seen else UNKNOWN],
                        "features": _features(s, state, pool),
                        "outcome": None if last else market_level(r.get(state + 1)), "case": name})
    return out


# ── Reading the sources (glue) ────────────────────────────────────────────────

def _births(museums: Mapping) -> dict[str, int]:
    born = {normalise(t): b for t, b in museums["aic"]["agents"].values() if t and b}
    for d in museums["cma"].get("creators", {}).values() if isinstance(museums["cma"].get("creators"), dict) else []:
        p = cma_person(d)
        if p and p.born:
            born.setdefault(p.name, p.born)
    return born


def _media(names: set[str]) -> dict[str, dict[str, dict[int, int]]]:
    """Artist -> medium -> year -> articles naming the artist with that tag."""
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for paper in ("guardian", "nyt"):
        for path in sorted(Path(TEXTS, paper).glob("*.jsonl")):
            year = int(path.stem[:4])
            for line in path.read_text().splitlines():
                tags = json.loads(line).get("tags", [])
                media = {MEDIA[(paper, v if paper == "nyt" else k)] for k, v in tags
                         if (paper, v if paper == "nyt" else k) in MEDIA and (paper != "nyt" or k == "subject")}
                if not media:
                    continue
                named = {nyt_person(v) for k, v in tags if paper == "nyt" and k.lower() == "persons"} | \
                        {normalise(v) for k, v in tags if paper == "guardian" and k.startswith("artanddesign/")}
                for n in named & names:
                    for m in media:
                        out[n][m][year] += 1
    return out


def _trend_claims(names: set[str]) -> dict[str, dict[str, dict[int, int]]]:
    """Artist -> list feature -> year -> claims about the artist in a trend
    on that list that year (years to September, as the lists)."""
    trend_of = {}
    for line in (TEXTS / "trends" / "claims.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["start"] is not None:
            trend_of[(r["paper"], r["article"], r["i"])] = r["trend"]
    status = {}
    for line in (TEXTS / "trends" / "status.jsonl").read_text().splitlines():
        r = json.loads(line)
        status[(r["trend"], r["year"])] = [LISTS[k] for k in LISTS if r[k]]
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for path in sorted((TEXTS / "grounded").glob("*/*.jsonl")):
        paper, month = path.parent.name, path.stem
        y, m = map(int, month.split("-"))
        year_to_sep, year = y + (m >= 10), y
        for line in path.read_text().splitlines():
            row = json.loads(line)
            for i, a in enumerate(row["assertions"]):
                t = trend_of.get((paper, row["id"], i))
                lists = status.get((t, year_to_sep), []) if t is not None else []
                if not lists:
                    continue
                artist = linked(a["about"], names)
                if artist is None:
                    continue
                for f in lists:
                    out[artist][f][year] += 1
    return out


def _ranks(people: Mapping, births: Mapping[str, int]) -> tuple[dict, set[int]]:
    """Artist -> year -> best Top 500 rank (all-artists or contemporary), and
    the years with a usable table (ART-PLAN §12.7)."""
    by_key: dict = defaultdict(list)
    for name in people:
        by_key[key(name, births.get(name))[0]].append(name)
    ranks: dict = defaultdict(dict)
    covered = set()
    for r in csv.DictReader(open(REPORTS / "top500.csv")):
        series, year = r["series"], int(r["year"])
        if series == "contemporary" and year in (2022, 2026):
            continue            # 2022 misread; 2026 covers only artists born after 1945, so not a whole year
        covered.add(year)
        words, born = key(r["name"], int(r["born"]) if r["born"] else None)
        for name in by_key.get(words, []):
            if born is None or births.get(name) in (None, born):
                ranks[name][year] = min(ranks[name].get(year, 999), int(r["rank"]))
    return ranks, covered


def build() -> dict[str, tuple[str, str, list[dict]]]:
    """Each kind of success: (title, outcome in words, records). Reads the
    press texts, claims, museums and Artprice's tables."""
    from .artist_records import artists
    people = artists()
    names = set(people)
    for name, by in _media(names).items():
        people[name] |= {m: dict(ys) for m, ys in by.items()}
    for name, by in _trend_claims(names).items():
        people[name] |= {f: dict(ys) for f, ys in by.items()}
    museums = json.loads((DATA / "artists" / "museums.json").read_text())
    ranks, covered = _ranks(people, _births(museums))
    return {
        "approve": ("Critics approve", "critics' approvals next year", count_records(people, ("approval",), YEARS, POOL)),
        "press": ("More press", "articles naming the artist next year", count_records(people, ("nyt", "guardian"), YEARS, POOL)),
        "museum": ("Museum buys", "Chicago and Cleveland acquisitions next year", count_records(people, ("museum",), YEARS, POOL)),
        "market": ("Market", "place in Artprice's Top 500 next year", market_records(people, ranks, covered, YEARS, POOL)),
    }


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, (title, outcome, rows) in build().items():
        snap = cases.dump(k, title, outcome, POOL, rows, {})
        (out_dir / f"{k}.json").write_text(json.dumps(snap, separators=(",", ":")))
        print(f"{k:8} {len(rows):7} artist-years, {len(snap['closed'])} distinct closed", flush=True)


if __name__ == "__main__":
    main()
