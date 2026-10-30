"""The art domain's success snapshot (REFACTOR_SPEC D31) from what
evals/success_run.py wrote (one summary per kind of success) and
abductive_engine's evals/export_rewarded.py (what critics rewarded).

    uv run python -m evals.success_snapshot RUN_DIR REWARDED.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domains.art_prestige_regime_v1 import success

from .artist_records import display_names
from .replay17 import DATA
from .success_records import YEARS, market_top

ROWS = 15


def kind(key: str, title: str, outcome: str, placebo_fair: bool, run: dict, labels: dict) -> dict:
    real, controls = run["real"], run["controls"]
    effects: dict = {}
    for k, e in real["effects"].items():
        f, v = k.split("=")
        effects.setdefault(f, {})[v] = round(e, 3)
    dealt: dict = {}
    for name, c in controls.items():
        if name.startswith("dealt "):
            dealt.setdefault(name.split()[1], []).append(round(c["gain"], 1))
    placebo = next(c["gain"] for name, c in controls.items() if name.startswith("placebo"))
    return {"title": title, "outcome": outcome, "leader": real["leader"],
            "leader_since": real["shifts"][-1][0] + 1 if real["shifts"] else None, "gain": round(real["gain"], 1),
            "mechanisms": [[m, round(g, 1)] for m, g in real["mechanisms"][:ROWS]], "effects": effects,
            "dealt": dealt, "placebo": round(placebo, 1), "placebo_fair": placebo_fair,
            "most_raised": [[labels.get(a, a.title()), round(o, 3), round(w, 3)] for a, o, w in real["most_raised"][:ROWS]],
            "years": [[y, round(g, 2)] for y, g, _ in real["years"]]}


# The placebo (features from the year after) is no test where those features
# count part of the outcome: an approval is a claim, so next year's trend
# claims include next year's approvals, and next year's NYT and medium-tagged
# articles are next year's press.
TITLES = {"approve": ("Critics approve", "critics' approvals of the artist next year", False),
          "press": ("More press", "articles naming the artist next year, in either paper", False),
          "museum": ("Museum buys", "works acquired by Chicago or Cleveland next year", True),
          "market": ("Market", "the artist's place in Artprice's Top 500 by auction turnover next year", True)}


def main() -> None:
    run_dir, rewarded = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
    runs = {k: json.loads((run_dir / f"{k}.json").read_text()) for k in success.KINDS}
    museums = json.loads((DATA / "artists" / "museums.json").read_text())
    labels = display_names(museums, {a for r in runs.values() for a, _, _ in r["real"]["most_raised"]})
    snap = {"year": rewarded["year"], "forecast_for": YEARS[-1] + 1,
            "kinds": {k: kind(k, *TITLES[k], runs[k], labels) for k in success.KINDS},
            "rewarded": rewarded["rewarded"],
            # Nothing predicts the market, so its image prompt describes who is at the top (ART-PLAN §12.9).
            "at_the_top": {"market": market_top(rewarded["year"])}}
    success.load(snap)          # refuse a snapshot that does not hang together
    success.DATA.parent.mkdir(exist_ok=True)
    success.DATA.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    print(f"-> {success.DATA}")


if __name__ == "__main__":
    main()
