"""
Art's success snapshot (REFACTOR_SPEC D31), made locally once a year by
evals/success_run.py and evals/success_snapshot.py (the features come from
reading the press on a subscription the server does not have) and shipped
in ``success_data/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from ...engine.model.success import Rewarded, Success, SuccessKind
from .cases import MEANINGS

DATA = Path(__file__).parent / "success_data" / "success.json"
KINDS = ("approve", "press", "museum", "market")
POOL = ("new_trend", "growing_trend", "fading_trend", "argued_trend", "painting", "photography", "sculpture", "nyt")


def _kind(key: str, k: Mapping) -> SuccessKind:
    unknown = set(k["leader"]) - set(POOL)
    if unknown:
        raise ValueError(f"{key}: leader names features outside the pool: {sorted(unknown)}")
    effects = {(f, int(v)): e for f, by in k["effects"].items() for v, e in by.items()}
    return SuccessKind(key, k["title"], k["outcome"], tuple(k["leader"]), k["leader_since"], k["gain"],
                       tuple((m, g) for m, g in k["mechanisms"]), effects,
                       {f: tuple(g) for f, g in k["dealt"].items()}, k["placebo"], k["placebo_fair"],
                       tuple((a, o, w) for a, o, w in k["most_raised"]), tuple((y, g) for y, g in k["years"]))


def load(snapshot: Mapping) -> Success:
    if set(snapshot["kinds"]) != set(KINDS):
        raise ValueError(f"kinds {sorted(snapshot['kinds'])}, expected {sorted(KINDS)}")
    return Success(snapshot["year"], snapshot["forecast_for"],
                   {key: _kind(key, k) for key, k in snapshot["kinds"].items()},
                   tuple(Rewarded(r["kind"], r["name"], r["approvals"], r["disapprovals"],
                                  tuple(r["approved"]), tuple(r["disapproved"])) for r in snapshot["rewarded"]),
                   {f: MEANINGS[f] for f in POOL})


def current() -> Optional[Success]:
    """The shipped snapshot, or None before one is made. Reads a file: call once."""
    return load(json.loads(DATA.read_text())) if DATA.exists() else None
