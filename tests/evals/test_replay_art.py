"""Replay 15's inputs and run: the art pipeline fed from saved counts."""
from __future__ import annotations

import json
from datetime import date

from evals import art_history, replay_art
from src.domains.art_prestige_regime_v1.domain import TALK


def _saved(tmp_path, months=range(1, 13), years=range(2000, 2003)):
    press = {paper: {} for paper in ("guardian", "nyt")}
    for y in years:
        for m in months:
            for paper in press:
                tags = {tag: 10 + (m * 7 + y) % 5 for _, (p, tag) in TALK.items() if p == paper}
                press[paper][f"{y}-{m:02d}"] = {"articles": 100, "tags": tags}
    (tmp_path / "press.json").write_text(json.dumps(press))
    (tmp_path / "museums.json").write_text(json.dumps({"aic": {str(fy): 100 + fy % 3 for fy in range(1990, 2003)},
                                                      "cma": {str(y): 50 + y % 4 for y in range(1990, 2003)}}))
    return art_history.load(tmp_path)


def test_saved_months_are_read_as_the_clients_would_give_them(tmp_path):
    history = _saved(tmp_path)
    import asyncio
    counts = asyncio.run(history.papers["nyt"].month(2001, 3))
    assert counts.articles == 100 and counts.share("museums") == (10 + (21 + 2001) % 5) / 100
    assert asyncio.run(history.papers["nyt"].month(1999, 3)) is None


def test_month_ends_from_start_to_end():
    assert replay_art.month_ends(date(2001, 1, 1), date(2001, 3, 31)) == [date(2001, 1, 31), date(2001, 2, 28), date(2001, 3, 31)]


def test_a_month_with_no_evidence_is_left_out(tmp_path):
    history = _saved(tmp_path)
    records = list(replay_art.records(history, date(2000, 6, 1), date(2001, 2, 28)))
    # The NYT needs a year of history and the Guardian is read only from 2010,
    # so until 2001 only December's museums are evidence.
    assert [d for d, _ in records] == [date(2000, 12, 31), date(2001, 1, 31), date(2001, 2, 28)]


def test_the_run_learns_each_month_in_turn(tmp_path):
    history = _saved(tmp_path)
    rows = replay_art.run(history, seed=0, start=date(2001, 1, 1), end=date(2002, 12, 31))
    assert [r["week"] for r in rows] == [d.isoformat() for d in replay_art.month_ends(date(2001, 1, 1), date(2002, 12, 31))]
    assert {r["observed"] for r in rows if not r["week"].startswith(("2001-12", "2002-12"))} == {4}
    december = next(r for r in rows if r["week"] == "2002-12-31")
    assert "MuseumAcquisitionMomentum" in december["states"]
