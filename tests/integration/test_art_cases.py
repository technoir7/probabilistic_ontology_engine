"""Art's case sets (REFACTOR_SPEC D29): records exported locally, stored
compactly in the domain package, loaded as case sets."""
from __future__ import annotations

import json

import pytest

from src.domains.art_prestige_regime_v1 import cases


def _records():
    rows = []
    for year in (2001, 2002):
        for case in ("a", "b", "c"):
            rows.append({"year": year, "own": [0, 1], "features": {"nyt": 0, "contested": 0}, "outcome": 0, "case": case})
    rows.append({"year": 2002, "own": [2, 1], "features": {"nyt": 2, "contested": 1}, "outcome": 1, "case": "d"})
    rows.append({"year": 2003, "own": [1, 1], "features": {"nyt": 1, "contested": 0}, "outcome": None, "case": "a"})
    return rows


def _snapshot():
    return cases.dump("artists", "Artists", "acquisitions next year", ("nyt", "contested"), _records(), {"a": "Artist A"})


def test_identical_closed_case_years_are_stored_once_with_their_weight():
    snap = _snapshot()
    assert sorted(snap["closed"]) == [[2001, [0, 1], [0, 0], 0, 3], [2002, [0, 1], [0, 0], 0, 3], [2002, [2, 1], [2, 1], 1, 1]]
    assert snap["open"] == [[2003, [1, 1], [1, 0], "a"]]


def test_a_snapshot_loads_as_the_case_set_it_was_made_from():
    s = cases.load(json.loads(json.dumps(_snapshot())))
    assert (s.key, s.title, s.outcome, s.pool) == ("artists", "Artists", "acquisitions next year", ("nyt", "contested"))
    assert sum(r.weight for r in s.records if r.outcome is not None) == 7
    [open_row] = [r for r in s.records if r.outcome is None]
    assert (open_row.year, open_row.own, dict(open_row.features), open_row.case) == (2003, (1, 1), {"nyt": 1, "contested": 0}, "a")
    assert s.labels == {"a": "Artist A"}


def test_a_snapshot_with_a_bad_row_is_refused():
    snap = _snapshot()
    snap["closed"].append([2004, [0, 1], [0], 0, 1])      # one feature value for two features
    with pytest.raises(ValueError):
        cases.load(snap)


def test_the_domain_ships_its_case_sets():
    sets = cases.case_sets()
    assert {s.key for s in sets} <= {"artists", "concepts"}
    for s in sets:
        assert s.records and s.pool
