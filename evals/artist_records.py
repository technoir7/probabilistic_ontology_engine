"""Replay 17's artists as cases (REFACTOR_SPEC D29, evals/README.md replay
18): one record per artist and state year, with that year's signals, the
artist's acquisitions this year and before (graded finely) and next year's
acquisitions; the last year is open, its outcome still to come.

    uv run python -m evals.artist_records     # writes the art domain's artists snapshot"""
from __future__ import annotations

import json
from typing import Iterable, Mapping

from .art_artists import normalise, panel, press_names
from .artist_years import level
from src.domains.art_prestige_regime_v1 import cases
from src.engine.model.cases import doubling
from .reception import reception
from .replay17 import DATA, TEXTS

POOL = ("nyt", "guardian", "approval", "contested")
GUARDIAN_FROM = 2010      # its tags settle then (art plan §12)


def records(people: Mapping, years: Iterable[int], pool: tuple[str, ...]) -> list[dict]:
    years = sorted(years)
    out = []
    for name, s in people.items():
        museum = s.get("museum", {})
        for state in years:
            before = sum(c for y, c in museum.items() if y < state)
            features = {f: level(s.get(f, {}).get(state, 0)) if f != "guardian" or state >= GUARDIAN_FROM else 0
                        for f in pool}
            out.append({"year": state, "own": [doubling(museum.get(state, 0)), doubling(before)], "features": features,
                        "outcome": level(museum.get(state + 1, 0)) if state < years[-1] else None, "case": name})
    return out


YEARS = range(2000, 2026)   # museums fetched to 2025: states to 2024 closed, 2025 open


def artists() -> dict:
    """Replay 17's panel with the critics' judgements. Reads the press texts."""
    people = panel(json.loads((DATA / "artists" / "museums.json").read_text()), press_names(TEXTS))
    for name, series in reception(TEXTS / "grounded", set(people)).items():
        people[name] |= series
    return people


def display_names(museums: Mapping, names: set[str]) -> dict[str, str]:
    """Chicago's spelling of each name where it has one; Cleveland's
    descriptions are not names, so the rest are title-cased."""
    chicago = {normalise(t): t for t, _ in museums["aic"]["agents"].values() if t}
    return {n: chicago.get(n, n.title()) for n in names}


def main() -> None:
    rows = records(artists(), YEARS, POOL)
    museums = json.loads((DATA / "artists" / "museums.json").read_text())
    labels = display_names(museums, {r["case"] for r in rows if r["outcome"] is None})
    snap = cases.dump("artists", "Artists", "Chicago and Cleveland acquisitions next year", POOL, rows, labels)
    path = cases.DATA / "artists.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(rows)} artist-years ({len(snap['closed'])} distinct closed) -> {path}")


if __name__ == "__main__":
    main()
