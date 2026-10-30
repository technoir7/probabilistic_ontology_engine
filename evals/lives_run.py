"""Life blocks (abductive_engine ART-PLAN 15.7): §14's theme test counting
only the claims read as about a life (§15.2), for every kind of success,
movers included. Each kind's pool is its §12 leader and the two life-block
features; controls as §12, dealing the two. Writes lives_KIND.json per kind
with this year's records of every named block.

    uv run python -m evals.lives_run OUT_DIR [KIND ...]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domains.art_prestige_regime_v1 import success

from .success_records import TEXTS, build, life_keys, life_theme_claims
from .success_run import judge_all
from .theme_records import track_records, with_theme_features

NEW = ("good_life", "poor_life")
SHOWN = 10        # named blocks shown at each end


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    kinds = sys.argv[2:] or list(success.KINDS + success.APART)
    shipped = success.current()
    leaders = {k: shipped.kinds[k].leader for k in kinds}
    built = build()
    names = {r["case"] for k in kinds for r in built[k][2]}
    claims = life_theme_claims(names, life_keys())
    named = json.loads((TEXTS / "trends" / "names.json").read_text())
    sets, records = {}, {}
    for k in kinds:
        title, outcome, rows = built[k]
        records[k] = track_records(rows, claims)
        sets[k] = (title, outcome, with_theme_features(rows, claims, records[k], NEW))
    real, controls = judge_all(sets, {k: tuple(leaders[k]) + NEW for k in kinds}, {k: list(NEW) for k in kinds})
    for k in kinds:
        year = max(records[k])
        now = {t: round(r, 4) for t, r in records[k][year].items() if t in named}
        ranked = sorted(now.items(), key=lambda tr: tr[1])
        shown = {"year": year, "best": [[t, named[t]["name"], r] for t, r in ranked[::-1][:SHOWN] if r > 0],
                 "worst": [[t, named[t]["name"], r] for t, r in ranked[:SHOWN] if r < 0], "now": now}
        (out_dir / f"lives_{k}.json").write_text(json.dumps(
            {"pool": list(leaders[k]) + list(NEW), "real": real[k], "controls": controls[k], "records": shown}, indent=1))
    print(f"-> {out_dir}")


if __name__ == "__main__":
    main()
