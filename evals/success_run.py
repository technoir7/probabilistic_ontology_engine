"""ART-PLAN §12.3: the case engine on each kind of success, with its
controls: each feature of the leader dealt at random among the year's
artists (3 deals; §12 deviation 1) and a placebo giving each artist-year
its features from the year after. Runs on several cores; writes one JSON
summary per kind of success.

    uv run python -m evals.success_run OUT_DIR [KIND ...]   # all kinds by default"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

from src.domains.art_prestige_regime_v1 import cases
from src.engine.services.cases import case_report

from .success_records import POOL, build

DEALS = 3
WORKERS = 8


def dealt(rows: list[dict], feature: str, seed: int) -> list[dict]:
    """FEATURE's values dealt at random among each year's closed records."""
    rng = random.Random(seed)
    by_year = defaultdict(list)
    for i, r in enumerate(rows):
        if r["outcome"] is not None:
            by_year[r["year"]].append(i)
    out = [dict(r, features=dict(r["features"])) for r in rows]
    for idx in by_year.values():
        values = [rows[i]["features"][feature] for i in idx]
        rng.shuffle(values)
        for i, v in zip(idx, values):
            out[i]["features"][feature] = v
    return out


def placebo(rows: list[dict]) -> list[dict]:
    """Each closed record with the features its case had the year after;
    records without a year after are dropped."""
    features = {(r["case"], r["year"]): r["features"] for r in rows}
    return [dict(r, features=features[(r["case"], r["year"] + 1)]) for r in rows
            if r["outcome"] is not None and (r["case"], r["year"] + 1) in features]


def _judge(job):
    key, title, outcome, rows, pool = job
    report = case_report(cases.load(cases.dump(key, title, outcome, pool, rows, {})))
    return {"leader": list(report.leader), "shifts": [(s.year, list(s.to)) for s in report.shifts],
            "gain": report.gain, "forecast_year": report.forecast_year,
            "mechanisms": [("+".join(m.features), m.gain) for m in report.mechanisms],
            "effects": {f"{f}={v}": e for (f, v), e in report.effects.items()},
            "years": [(y.year, y.engine - y.own_past, y.cases) for y in report.years],
            "most_raised": [(f.case, 1 - f.own_past[0], 1 - f.with_leader[0]) for f in report.most_raised]}


def judge_all(sets: dict, pools: dict, deal: Optional[dict] = None) -> tuple[dict, dict]:
    """Each case set judged with its POOLS[k] of features, then its controls:
    each of DEAL[k]'s features dealt at random (by default the leader's, or
    the best single feature if own past leads), DEALS times, and the placebo."""
    with ProcessPoolExecutor(WORKERS) as ex:
        real = dict(zip(sets, ex.map(_judge, [(k, t, o, rows, pools[k]) for k, (t, o, rows) in sets.items()])))
        for k, r in real.items():
            print(f"{k:8} leader {'+'.join(r['leader']) or 'own past'}, gain {r['gain']:+.1f}", flush=True)
        jobs, names = [], []
        for k, (t, o, rows) in sets.items():
            single = max((m for m in real[k]["mechanisms"] if "+" not in m[0]), key=lambda m: m[1])[0]
            for f in (deal or {}).get(k) or real[k]["leader"] or [single]:
                for seed in range(DEALS):
                    jobs.append((k, t, o, dealt(rows, f, seed), pools[k]))
                    names.append((k, f"dealt {f} #{seed}"))
            jobs.append((k, t, o, placebo(rows), pools[k]))
            names.append((k, "placebo: features from the year after"))
        controls: dict = defaultdict(dict)
        for (k, name), r in zip(names, ex.map(_judge, jobs)):
            controls[k][name] = {"leader": r["leader"], "gain": r["gain"],
                                 "best": r["mechanisms"][0] if r["mechanisms"] else None}
            print(f"{k:8} {name}: leader {'+'.join(r['leader']) or 'own past'}, gain {r['gain']:+.1f}", flush=True)
    return real, dict(controls)


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    sets = build()
    if sys.argv[2:]:
        sets = {k: sets[k] for k in sys.argv[2:]}
    real, controls = judge_all(sets, {k: POOL for k in sets})
    for k in sets:
        (out_dir / f"{k}.json").write_text(json.dumps({"real": real[k], "controls": controls[k]}, indent=1))
    print(f"-> {out_dir}")


if __name__ == "__main__":
    main()
