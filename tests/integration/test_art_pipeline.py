"""
The art pipeline (ingestion/pipeline.py), with fake clients: monthly talk in
two papers, the yearly report figures in April, museum acquisitions in
December (docs/art-evidence-plan.md).
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.domains.art_prestige_regime_v1.domain import TALK, get_variables
from src.domains.art_prestige_regime_v1.ingestion.aic_client import Acquisitions
from src.domains.art_prestige_regime_v1.ingestion.pipeline import ArtPipeline
from src.domains.art_prestige_regime_v1.ingestion.tag_counts import TagCounts
from src.domains.sources.structure import with_lags
from src.engine.model.errors import EvidenceUnavailable
from src.engine.schemas import MissingnessType

VARIABLES = with_lags("art_prestige_regime_v1", get_variables())
NAMES = {v.variable_id: n for n, v in VARIABLES.items()}
GUARDIAN = [n for n, (paper, _) in TALK.items() if paper == "guardian"]
NYT = [n for n, (paper, _) in TALK.items() if paper == "nyt"]


class FakePress:
    """Every month: 100 art articles, each tag on 10 of them (± a wobble), unless overridden."""

    def __init__(self, tags, overrides=None, fail=()):
        self.tags, self.overrides, self.fail = tags, overrides or {}, set(fail)
        self.requests: list[tuple[int, int]] = []

    async def month(self, year, month):
        self.requests.append((year, month))
        if (year, month) in self.fail:
            return None
        if (year, month) in self.overrides:
            return self.overrides[(year, month)]
        return TagCounts(articles=100, tags={t: 10 + (month % 3) for t in self.tags})


class FakeAIC:
    def __init__(self, artists_by_year=None):
        self.artists = artists_by_year or {}

    async def acquisitions(self, fiscal_year, artwork_types=None):
        if fiscal_year not in self.artists:
            return None
        return Acquisitions(objects=self.artists[fiscal_year] * 3, artists=self.artists[fiscal_year])


class FakeCMA:
    def __init__(self, artists_by_year=None):
        self.artists = artists_by_year

    async def artists_by_year(self):
        return self.artists


def _papers(**kw):
    g = FakePress([tag for n, (p, tag) in TALK.items() if p == "guardian"], **kw.get("guardian", {}))
    n = FakePress([tag for n, (p, tag) in TALK.items() if p == "nyt"], **kw.get("nyt", {}))
    return {"guardian": g, "nyt": n}


def _pipeline(papers=None, aic=None, cma=None, figures=None):
    return ArtPipeline(papers or _papers(), aic or FakeAIC(), cma or FakeCMA(), figures=figures or {})


def _levels(record):
    return {NAMES[a.variable_id]: a.observed_value for a in record.observed_assignments
            if a.missingness == MissingnessType.OBSERVED}


def _fetch(pipeline, d):
    return asyncio.run(pipeline.fetch_evidence(d))


def test_a_month_with_more_talk_of_a_topic_than_the_two_years_before_reads_high():
    spike = TagCounts(articles=100, tags={"artanddesign/photography": 40, "artanddesign/exhibition": 11,
                                          "artanddesign/painting": 11, "artanddesign/architecture": 11})
    levels = _levels(_fetch(_pipeline(_papers(guardian={"overrides": {(2020, 3): spike}})), date(2020, 3, 31)))
    assert levels["GuardianPhotographyTalk"] == "high"
    assert set(levels) == set(TALK)   # figures and museums wait for their months


def test_talk_that_rose_years_ago_and_stayed_reads_as_ordinary():
    risen = {(y, m): TagCounts(articles=100, tags={"museums": 40 + m % 3}) for y in range(2015, 2021) for m in range(1, 13)}
    levels = _levels(_fetch(_pipeline(_papers(nyt={"overrides": risen})), date(2020, 7, 31)))   # July: share at the mean
    assert levels["NYTMuseumsTalk"] == "mid"


def test_each_month_is_compared_with_the_two_years_before_it_and_never_later():
    papers = _papers()
    _fetch(_pipeline(papers), date(2020, 3, 31))
    asked = set(papers["nyt"].requests)
    assert (2020, 3) in asked and (2018, 3) in asked
    assert (2018, 2) not in asked and (2020, 4) not in asked


def test_guardian_tags_before_2010_are_not_read():
    papers = _papers()
    levels = _levels(_fetch(_pipeline(papers), date(2009, 6, 30)))
    assert set(levels) == set(NYT)
    assert all(y >= 2010 for y, _ in papers["guardian"].requests)


def test_with_under_a_year_of_history_a_paper_is_not_read():
    papers = _papers()
    levels = _levels(_fetch(_pipeline(papers), date(2010, 11, 30)))
    assert not set(GUARDIAN) & set(levels)
    levels = _levels(_fetch(_pipeline(papers), date(2011, 1, 31)))
    assert set(GUARDIAN) <= set(levels)


def test_a_month_a_paper_cannot_supply_leaves_only_that_paper_missing():
    levels = _levels(_fetch(_pipeline(_papers(nyt={"fail": [(2020, 3)]})), date(2020, 3, 31)))
    assert set(levels) == set(GUARDIAN)


def test_the_april_record_carries_last_years_figures_and_the_year_before():
    figures = {"OnlineShare": {2016: 8.0, 2017: 10.0, 2018: 9.0, 2019: 9.0, 2020: 25.0}}
    record = _fetch(_pipeline(figures=figures), date(2021, 4, 30))
    levels = _levels(record)
    assert levels["OnlineShare"] == "high"
    assert levels["OnlineShare_prev"] == "mid"
    assert "OnlineShare" not in _levels(_fetch(_pipeline(figures=figures), date(2021, 5, 31)))


def test_the_december_record_reads_both_museums_against_their_own_pasts():
    aic = FakeAIC({fy: 100 + fy % 2 for fy in range(2010, 2025)} | {2024: 300})   # FY2024 ended 18 months before
    cma = FakeCMA({y: 50 + y % 2 for y in range(2010, 2025)} | {2024: 150})
    levels = _levels(_fetch(_pipeline(aic=aic, cma=cma), date(2025, 12, 31)))
    assert levels["MuseumAcquisitionMomentum"] == "high"
    assert "MuseumAcquisitionMomentum_prev" in levels
    assert "MuseumAcquisitionMomentum" not in _levels(_fetch(_pipeline(aic=aic, cma=cma), date(2025, 11, 30)))


def test_one_museum_failing_leaves_the_other():
    aic = FakeAIC({fy: 100 + fy % 2 for fy in range(2010, 2025)} | {2024: 300})
    levels = _levels(_fetch(_pipeline(aic=aic, cma=FakeCMA(None)), date(2025, 12, 31)))
    assert levels["MuseumAcquisitionMomentum"] == "high"


def test_a_month_with_no_input_at_all_is_unavailable():
    papers = _papers(guardian={"fail": [(2020, 3)]}, nyt={"fail": [(2020, 3)]})
    with pytest.raises(EvidenceUnavailable):
        _fetch(_pipeline(papers), date(2020, 3, 31))


def test_a_month_with_no_art_articles_is_not_read():
    levels = _levels(_fetch(_pipeline(_papers(nyt={"overrides": {(2020, 3): TagCounts(articles=0)}})), date(2020, 3, 31)))
    assert set(levels) == set(GUARDIAN)
