"""
Replay 17 (evals/README.md): run the comparisons on the artists panel.

    uv run python -m evals.replay17 --first 2000 --last 2009 --press nyt

Writes evals/data/replay17/<press>_<first>-<last>.json: for each pair, the
gain (log Bayes factor), per artist-year, by year, and the same under five
shuffles of each artist's years.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .art_artists import panel, press_names
from .artist_years import compare, shuffled

DATA = Path(__file__).parent / "data"
TEXTS = Path.home() / "Documents" / "art-press-texts"
PAIRS = [("museum", "{press}"), ("{press}", "museum"), ("aic", "{press}"), ("cma", "{press}")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--first", type=int, required=True)
    parser.add_argument("--last", type=int, required=True)
    parser.add_argument("--press", default="nyt", choices=["nyt", "guardian"])
    args = parser.parse_args()
    museums = json.loads((DATA / "artists" / "museums.json").read_text())
    people = panel(museums, press_names(TEXTS))
    years = range(args.first, args.last + 1)
    out = {"artists": len(people), "years": [args.first, args.last], "pairs": {}}
    for target, other in PAIRS:
        target, other = target.format(press=args.press), other.format(press=args.press)
        real = compare(people, target, other, years)
        controls = [compare(shuffled(people, random.Random(s), years), target, other, years) for s in range(5)]
        out["pairs"][f"{other} -> {target}"] = {
            "gain": round(real.gain, 2), "cases": real.cases, "per_case": round(real.gain / real.cases, 5),
            "by_year": {y: round(g, 5) for y, g in real.by_year.items()},
            "shuffled_gains": [round(c.gain, 2) for c in controls],
        }
        print(f"{other:>8} -> {target:<8} gain {real.gain:9.1f} nats over {real.cases} artist-years; "
              f"shuffled {[round(c.gain, 1) for c in controls]}", flush=True)
    path = DATA / "replay17" / f"{args.press}_{args.first}-{args.last}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print(f"{out['artists']} artists -> {path}")


if __name__ == "__main__":
    main()
