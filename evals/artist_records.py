"""Replay 17's artists as cases for the abductive engine's case engine
(abductive_engine ART-PLAN §9): one record per artist and year with last
year's signals and this year's museum acquisitions, written as JSON.

    uv run python -m evals.artist_records OUT.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Mapping

from .art_artists import panel, press_names
from .artist_years import level
from .reception import reception
from .replay17 import DATA, TEXTS

POOL = ("nyt", "guardian", "approval", "contested")
GUARDIAN_FROM = 2010      # its tags settle then (art plan §12)


def records(people: Mapping, years: Iterable[int], pool: tuple[str, ...]) -> list[dict]:
    years = sorted(years)
    out = []
    for name, s in people.items():
        museum = s.get("museum", {})
        for state in years[:-1]:
            standing = level(sum(c for y, c in museum.items() if y < state))
            features = {f: level(s.get(f, {}).get(state, 0)) if f != "guardian" or state >= GUARDIAN_FROM else 0
                        for f in pool}
            out.append({"year": state, "own": [level(museum.get(state, 0)), standing], "features": features,
                        "outcome": level(museum.get(state + 1, 0)), "case": name})
    return out


def main() -> None:
    people = panel(json.loads((DATA / "artists" / "museums.json").read_text()), press_names(TEXTS))
    for name, series in reception(TEXTS / "grounded", set(people)).items():
        people[name] |= series
    rows = records(people, range(2000, 2026), POOL)
    Path(sys.argv[1]).write_text(json.dumps({"pool": POOL, "records": rows}))
    print(f"{len(rows)} artist-years -> {sys.argv[1]}")


if __name__ == "__main__":
    main()
