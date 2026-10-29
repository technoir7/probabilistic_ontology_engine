"""Art's trends (REFACTOR_SPEC D30): this year's new, growing, fading and
argued-over trends in the press, exported locally and shipped with the
domain; they describe the present and forecast nothing."""
from __future__ import annotations

import copy

import pytest

from src.domains.art_prestige_regime_v1 import trends


def _snapshot():
    return {
        "year": 2026, "before": 3, "years": [2023, 2024, 2025, 2026], "all_writers": [100, 100, 100, 200],
        "lists": {"new": ["7"], "growing": ["7"], "fading": ["8"], "argued": []},
        "trends": {
            "7": {"name": "art made with AI", "start": 2025, "words": ["ai", "robot"], "writers": [0, 0, 10, 40],
                  "papers": ["guardian", "nyt"], "verdicts": [5, 4], "sample": ["AI art: is contested"]},
            "8": {"name": "NFTs", "start": 2021, "words": ["nft"], "writers": [30, 20, 10, 5],
                  "papers": ["guardian"], "verdicts": [0, 1], "sample": []},
        },
    }


def test_a_trends_share_is_its_writers_over_every_writer_that_year():
    t = trends.load(_snapshot())
    assert t.share("7", 2026) == pytest.approx(0.2)
    assert t.share_before("7") == pytest.approx(10 / 300)       # the three years before
    assert t.share_before("8") == pytest.approx(60 / 300)


def test_the_lists_name_their_trends_in_order():
    t = trends.load(_snapshot())
    assert [x.name for x in t.listed("new")] == ["art made with AI"]
    assert [x.name for x in t.listed("fading")] == ["NFTs"]
    assert t.trends["7"].verdicts == (5, 4) and t.trends["7"].papers == ("guardian", "nyt")


@pytest.mark.parametrize("break_it", [
    lambda s: s["lists"]["new"].append("9"),                        # a listed trend that is not there
    lambda s: s["trends"]["7"]["writers"].pop(),                    # writers for fewer years than given
    lambda s: s["lists"].pop("argued"),                             # a list missing
    lambda s: s.update(year=2030),                                  # a year outside the years given
])
def test_a_snapshot_that_does_not_hang_together_is_refused(break_it):
    snap = copy.deepcopy(_snapshot())
    break_it(snap)
    with pytest.raises(ValueError):
        trends.load(snap)


def test_the_domain_ships_this_years_trends():
    t = trends.current()
    assert t is not None and t.year == 2026
    assert all(t.listed(k) for k in trends.LISTS)
