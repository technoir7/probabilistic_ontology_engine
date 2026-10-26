"""Replay 16's records: art talk by quarter and by year (evals/README.md)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from evals import art_history, replay_art_slow
from src.domains.art_prestige_regime_v1.domain import TALK


def _saved(tmp_path, spike=None):
    press = {"guardian": {}, "nyt": {}}
    for y in range(2000, 2012):
        for m in range(1, 13):
            for paper in press:
                tags = {tag: 10 + (7 * m + 3 * y) % 5 for _, (p, tag) in TALK.items() if p == paper}
                if spike and (paper, y, m) == spike:
                    tags = {t: 60 for t in tags}
                press[paper][f"{y}-{m:02d}"] = {"articles": 100, "tags": tags}
    (tmp_path / "press.json").write_text(json.dumps(press))
    (tmp_path / "museums.json").write_text(json.dumps({"aic": {str(fy): 100 + fy % 3 for fy in range(1990, 2012)},
                                                      "cma": {str(y): 50 + y % 4 for y in range(1990, 2012)}}))
    return art_history.load(tmp_path)


def test_period_ends():
    assert replay_art_slow.period_ends("quarter", date(2001, 1, 1), date(2001, 9, 30)) == [
        date(2001, 3, 31), date(2001, 6, 30), date(2001, 9, 30)]
    assert replay_art_slow.period_ends("year", date(2001, 1, 1), date(2003, 12, 31)) == [
        date(2001, 12, 31), date(2002, 12, 31), date(2003, 12, 31)]


def test_a_quarter_is_its_months_pooled_and_read_against_the_eight_before(tmp_path):
    history = _saved(tmp_path, spike=("nyt", 2005, 5))
    records = dict(replay_art_slow.records(history, "quarter", date(2005, 1, 1), date(2005, 12, 31), figures={}))
    names = replay_art_slow.NAMES
    def level(d, name):
        return {names[str(a.variable_id)]: a.observed_value for a in records[d].observed_assignments}.get(name)
    assert level(date(2005, 6, 30), "NYTMuseumsTalk") == "high"
    assert level(date(2005, 12, 31), "MuseumAcquisitionMomentum") is not None   # museums in the last quarter


def test_the_guardian_is_read_from_2010_and_needs_half_its_window(tmp_path):
    history = _saved(tmp_path)
    names = replay_art_slow.NAMES
    early = dict(replay_art_slow.records(history, "quarter", date(2010, 1, 1), date(2011, 12, 31), figures={}))
    seen = {d: {names[str(a.variable_id)] for a in r.observed_assignments if a.observed_value} for d, r in early.items()}
    assert "GuardianPaintingTalk" not in seen[date(2010, 9, 30)]   # 2 quarters before it
    assert "GuardianPaintingTalk" in seen[date(2011, 3, 31)]      # 4 quarters before it


def test_yearly_figures_are_seen_in_their_year(tmp_path):
    history = _saved(tmp_path)
    figures = {"OnlineShare": {2005: 8.0, 2006: 10.0, 2007: 9.0, 2008: 9.0, 2009: 25.0}}
    records = dict(replay_art_slow.records(history, "year", date(2008, 1, 1), date(2010, 12, 31), figures=figures))
    names = replay_art_slow.NAMES
    got = {names[str(a.variable_id)]: a.observed_value for a in records[date(2010, 12, 31)].observed_assignments}
    assert got["OnlineShare"] == "high"   # the 2009 figure, published April 2010
