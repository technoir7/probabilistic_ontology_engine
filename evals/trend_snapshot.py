"""The art domain's trend snapshots (REFACTOR_SPEC D30) from the file
abductive_engine's evals/export_trends.py writes: the trends as a case set
(case_data/trends.json, for the case engine) and this year's lists
(trend_data/trends.json, for reading).

    uv run python -m evals.trend_snapshot EXPORT.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domains.art_prestige_regime_v1 import cases, trends


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text())
    c = data["cases"]
    # Outcomes are falls (0), holds (1), grows (2) a doubling of writers; the
    # case engine's "chance of the outcome at all" is then the chance a trend holds or grows.
    snap = cases.dump("trends", "Trends", "trends holding or growing next year", tuple(c["pool"]),
                      c["records"], c["labels"])
    path = cases.DATA / "trends.json"
    path.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(c['records'])} trend-years ({len(snap['closed'])} distinct closed) -> {path}")
    trends.load(data["lists"])     # refuse a snapshot that does not hang together
    trends.DATA.parent.mkdir(exist_ok=True)
    trends.DATA.write_text(json.dumps(data["lists"], separators=(",", ":"), ensure_ascii=False))
    print(f"{sum(len(v) for v in data['lists']['lists'].values())} listed trends -> {trends.DATA}")


if __name__ == "__main__":
    main()
