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

from ...engine.model.success import AtTheTop, Rewarded, Success, SuccessKind
from .cases import MEANINGS

DATA = Path(__file__).parent / "success_data" / "success.json"
KINDS = ("approve", "press", "museum", "market")
APART = ("movers",)            # its own panel and report (ART-PLAN §13)
POOL = ("new_trend", "growing_trend", "fading_trend", "argued_trend", "painting", "photography", "sculpture", "nyt")
LISTS = {"new_trend": "new", "growing_trend": "growing", "fading_trend": "fading", "argued_trend": "argued"}
MEDIA = {"painting": "painting", "photography": "photography", "sculpture": "sculpture"}


def _kind(key: str, k: Mapping) -> SuccessKind:
    unknown = set(k["leader"]) - set(POOL)
    if unknown:
        raise ValueError(f"{key}: leader names features outside the pool: {sorted(unknown)}")
    effects = {(f, int(v)): e for f, by in k["effects"].items() for v, e in by.items()}
    return SuccessKind(key, k["title"], k["outcome"], tuple(k["leader"]), k["leader_since"], k["gain"],
                       tuple((m, g) for m, g in k["mechanisms"]), effects,
                       {f: tuple(g) for f, g in k["dealt"].items()}, k["placebo"], k["placebo_fair"],
                       tuple((a, o, w) for a, o, w in k["most_raised"]), tuple((y, g) for y, g in k["years"]))


def _at_the_top(t: Mapping) -> AtTheTop:
    return AtTheTop(t["table_year"], t["artists"], {k: (a, c) for k, (a, c) in t["themes"].items()}, dict(t["media"]),
                    {k: tuple(said) for k, said in t["said"].items()})


def load(snapshot: Mapping) -> Success:
    if not set(KINDS) <= set(snapshot["kinds"]) <= set(KINDS) | set(APART):
        raise ValueError(f"kinds {sorted(snapshot['kinds'])}, expected {sorted(KINDS)} and any of {sorted(APART)}")
    if not set(snapshot["at_the_top"]) <= set(KINDS):
        raise ValueError(f"at_the_top names kinds outside {sorted(KINDS)}: {sorted(snapshot['at_the_top'])}")
    return Success(snapshot["year"], snapshot["forecast_for"],
                   {key: _kind(key, k) for key, k in snapshot["kinds"].items()},
                   tuple(Rewarded(r["kind"], r["name"], r["approvals"], r["disapprovals"],
                                  tuple(r["approved"]), tuple(r["disapproved"])) for r in snapshot["rewarded"]),
                   {f: MEANINGS[f] for f in POOL}, LISTS, MEDIA,
                   {k: _at_the_top(t) for k, t in snapshot["at_the_top"].items()},
                   tuple(k for k in APART if k in snapshot["kinds"]))


def current() -> Optional[Success]:
    """The shipped snapshot, or None before one is made. Reads a file: call once."""
    return load(json.loads(DATA.read_text())) if DATA.exists() else None
