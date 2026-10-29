"""
Art's trends (REFACTOR_SPEC D30), exported locally once a year with the case
sets (abductive_engine evals/export_trends.py, then evals/trend_snapshot.py)
and shipped in ``trend_data/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from ...engine.model.trends import LISTS, Trend, TrendLists

DATA = Path(__file__).parent / "trend_data" / "trends.json"

__all__ = ["DATA", "LISTS", "current", "load"]


def load(snapshot: Mapping) -> TrendLists:
    years = tuple(snapshot["years"])
    if len(snapshot["all_writers"]) != len(years):
        raise ValueError(f"{len(snapshot['all_writers'])} writer totals for {len(years)} years")
    if snapshot["year"] not in years or snapshot["year"] - snapshot["before"] not in years:
        raise ValueError(f"year {snapshot['year']} and the {snapshot['before']} before it are not all in {years}")
    if set(snapshot["lists"]) != set(LISTS):
        raise ValueError(f"lists {sorted(snapshot['lists'])}, expected {sorted(LISTS)}")
    trends = {}
    for k, t in snapshot["trends"].items():
        if len(t["writers"]) != len(years):
            raise ValueError(f"trend {k}: writers for {len(t['writers'])} years, not {len(years)}")
        trends[k] = Trend(k, t["name"], t["start"], tuple(t["words"]), tuple(t["writers"]), tuple(t["papers"]),
                          tuple(t["verdicts"]), tuple(t["sample"]))
    lists = {name: tuple(ks) for name, ks in snapshot["lists"].items()}
    missing = sorted({k for ks in lists.values() for k in ks} - set(trends))
    if missing:
        raise ValueError(f"listed trends not in the snapshot: {missing}")
    return TrendLists(snapshot["year"], snapshot["before"], years, tuple(snapshot["all_writers"]), lists, trends)


def current() -> Optional[TrendLists]:
    """The shipped snapshot, or None before one is made. Reads a file: call once."""
    return load(json.loads(DATA.read_text())) if DATA.exists() else None
