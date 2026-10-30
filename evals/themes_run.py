"""Which themes help (abductive_engine ART-PLAN §14): for each of the four
kinds of success, the case engine with a pool of that kind's §12 leader and
the two theme-record features, so the question is whether a theme's record
adds anything to what already leads; controls as §12, dealing the two new
features. Writes themes_KIND.json per kind, with this year's records of the
named themes.

    uv run python -m evals.themes_run OUT_DIR [KIND ...]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domains.art_prestige_regime_v1 import success

from .success_records import TEXTS, build, theme_claims
from .success_run import judge_all
from .theme_records import track_records, with_theme_features

NEW = ("good_theme", "poor_theme")
SHOWN = 10        # named themes shown at each end


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    kinds = sys.argv[2:] or list(success.KINDS)
    shipped = success.current()
    leaders = {k: shipped.kinds[k].leader for k in kinds}
    built = build()
    names = {r["case"] for k in kinds for r in built[k][2]}
    claims = theme_claims(names)
    named = json.loads((TEXTS / "trends" / "names.json").read_text())
    sets, records = {}, {}
    for k in kinds:
        title, outcome, rows = built[k]
        records[k] = track_records(rows, claims)
        sets[k] = (title, outcome, with_theme_features(rows, claims, records[k]))
    real, controls = judge_all(sets, {k: tuple(leaders[k]) + NEW for k in kinds}, {k: list(NEW) for k in kinds})
    for k in kinds:
        year = max(records[k])
        ranked = sorted(((t, r) for t, r in records[k][year].items() if t in named), key=lambda tr: tr[1])
        shown = {"year": year, "best": [[t, named[t]["name"], round(r, 3)] for t, r in ranked[::-1][:SHOWN] if r > 0],
                 "worst": [[t, named[t]["name"], round(r, 3)] for t, r in ranked[:SHOWN] if r < 0]}
        (out_dir / f"themes_{k}.json").write_text(json.dumps(
            {"pool": list(leaders[k]) + list(NEW), "real": real[k], "controls": controls[k], "records": shown}, indent=1))
    print(f"-> {out_dir}")


if __name__ == "__main__":
    main()
