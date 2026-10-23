"""
How long each research programme survived a replay, and how it stood.

    uv run python -m evals.programmes evals/data/replay10
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from .replay import read_rows


def survival(rows: list[dict]) -> dict[str, dict]:
    """Per programme: weeks alive, last week alive, weeks it led, and at its
    last week the evidence against it and the share of founding links held."""
    out = {}
    led = Counter(r["family"] for r in rows)
    for family in sorted({f for r in rows for f in r["programmes"]}):
        alive = [r for r in rows if family in r["programmes"]]
        last = alive[-1]["programmes"][family]
        out[family] = {"weeks": len(alive), "until": alive[-1]["week"], "led": led.get(family, 0),
                       "last_log_bf": last["log_bf"], "core_kept": last["core_kept"], "links": last["edges"]}
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    for gz in sorted(folder.glob("seed*.jsonl.gz")):
        print(gz.stem.split(".")[0])
        for family, s in survival(read_rows(gz)).items():
            print(f"  {family:14s} alive {s['weeks']:4d} wk until {s['until']}  led {s['led']:4d} wk  "
                  f"last log BF {s['last_log_bf']:6.2f}  links {s['links']:2d}  founding links kept {s['core_kept']}")
