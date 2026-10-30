"""
Art's case sets (REFACTOR_SPEC D29): artists and debates, exported locally
once a year (the debates come from reading the press with a model on a
subscription the server does not have) and shipped in ``case_data/``.

A snapshot stores each closed case-year once with its weight, since most
are alike (an artist with no press and no acquisitions), and each open
case-year by name, to forecast.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from ...engine.model.cases import CaseSet, CaseYear

DATA = Path(__file__).parent / "case_data"

# What each mechanism records about a case in its state year, for readers.
MEANINGS = {
    "nyt": "NYT coverage that year",
    "guardian": "Guardian coverage that year",
    "approval": "critics' approval that year",
    "contested": "contested that year (both praised and condemned)",
    "both_papers": "written about in both papers that year",
    "modality": "predictions or doubts voiced that year",
    # Success (D31): the artist's coverage that year.
    "new_trend": "claims about the artist in a new trend that year",
    "growing_trend": "claims about the artist in a growing trend that year",
    "fading_trend": "claims about the artist in a fading trend that year",
    "argued_trend": "claims about the artist in an argued-over trend that year",
    # Which themes help (ART-PLAN §14): records learned from earlier years only.
    "good_theme": "claims about the artist in themes with a good record so far",
    "poor_theme": "claims about the artist in themes with a poor record so far",
    "painting": "Guardian articles on the artist tagged painting that year",
    "photography": "articles on the artist tagged photography that year",
    "sculpture": "articles on the artist tagged sculpture that year",
}


def dump(key: str, title: str, outcome: str, pool: tuple[str, ...], records: Iterable[Mapping],
         labels: Mapping[str, str]) -> dict:
    closed: Counter = Counter()
    open_rows = []
    for r in records:
        values = [r["features"][f] for f in pool]
        if r["outcome"] is None:
            open_rows.append([r["year"], list(r["own"]), values, r["case"]])
        else:
            closed[(r["year"], tuple(r["own"]), tuple(values), r["outcome"])] += 1
    return {"key": key, "title": title, "outcome": outcome, "pool": list(pool), "labels": dict(labels),
            "closed": [[y, list(own), list(v), o, w] for (y, own, v, o), w in sorted(closed.items())],
            "open": sorted(open_rows, key=lambda r: (r[0], r[3]))}


def load(snapshot: Mapping) -> CaseSet:
    pool = tuple(snapshot["pool"])

    def features(values: list) -> dict:
        if len(values) != len(pool):
            raise ValueError(f"{snapshot['key']}: {len(values)} feature values for {len(pool)} features")
        return dict(zip(pool, values))

    records = [CaseYear(y, tuple(own), features(v), o, weight=w) for y, own, v, o, w in snapshot["closed"]]
    records += [CaseYear(y, tuple(own), features(v), None, case=c) for y, own, v, c in snapshot["open"]]
    return CaseSet(snapshot["key"], snapshot["title"], pool, tuple(records), dict(snapshot["labels"]),
                   snapshot["outcome"], {f: MEANINGS.get(f, f) for f in pool})


def case_sets() -> tuple[CaseSet, ...]:
    """Every snapshot shipped with the domain. Reads files: call once."""
    return tuple(load(json.loads(p.read_text())) for p in sorted(DATA.glob("*.json")))
