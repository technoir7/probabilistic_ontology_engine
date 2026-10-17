"""
The art pipeline's measurements (ingestion/pipeline.py), with fake clients.

AI imagery comes from GDELT news coverage, monthly; museum variables from AIC
acquisitions, once a year in the December record.
Everything else is MISSING in fetched records.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from src.domains.art_prestige_regime_v1.domain import get_variables
from src.domains.art_prestige_regime_v1.ingestion.aic_client import Acquisitions
from src.domains.art_prestige_regime_v1.ingestion.pipeline import CRAFT_TYPES, ArtPipeline
from src.domains.sources.gdelt import GDELTObs
from src.engine.model.errors import EvidenceUnavailable

NAMES = {v.variable_id: n for n, v in get_variables().items()}


def _months(first: date, last: date) -> list[date]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(date(y, m, 1))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


TODAY = date(2026, 6, 15)


class FakeGDELT:
    """Monthly points from the requested start to end: a flat level, *boost_month* times *boost*."""

    def __init__(self, level=0.002, boost=1.0, boost_month=None, gap_month=None, fail=False):
        self.level, self.boost, self.boost_month, self.gap_month, self.fail = level, boost, boost_month, gap_month, fail
        self.requests: list[tuple[str, int, date]] = []

    async def fetch_timeline(self, query, label, lookback_days=90, end_date=None):
        self.requests.append((query, lookback_days, end_date))
        if self.fail:
            return []
        start = end_date - timedelta(days=lookback_days)
        out = []
        for i, m in enumerate(_months(start, end_date)):
            if m == self.gap_month:
                continue
            value = self.level * (self.boost if m == self.boost_month else 1) + (i % 3) * 1e-5
            out.append(GDELTObs(obs_date=m, value=value, query_label=label))
        return out[::-1]


def _pipeline(gdelt, aic=None):
    return ArtPipeline(gdelt, aic or FakeAIC(), today=lambda: TODAY)


class FakeAIC:
    def __init__(self, artists_by_year=None, craft_by_year=None):
        self.artists = artists_by_year or {}
        self.craft = craft_by_year or {}
        self.years: list[int] = []

    async def acquisitions(self, fiscal_year, artwork_types=None):
        self.years.append(fiscal_year)
        table = self.craft if artwork_types else self.artists
        if fiscal_year not in table:
            return None
        return Acquisitions(objects=table[fiscal_year] * 3, artists=table[fiscal_year])


def _probabilities(record):
    return {NAMES[a.variable_id]: (a.probabilities or {}).get(True) for a in record.observed_assignments}


def test_a_coverage_rise_reads_true_and_museum_variables_wait_for_december():
    pipeline = _pipeline(FakeGDELT(boost=3.0, boost_month=date(2026, 3, 1)))
    p = _probabilities(asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31))))
    assert p["AIImageSaturation"] > 0.9
    assert p["MuseumAcquisitionMomentum"] is None and p["CraftPrestigeRising"] is None
    assert sum(v is not None for v in p.values()) == 1


def test_every_month_asks_gdelt_the_same_question():
    # A rebuild used to send one five-year request per month, 36 of nearly the
    # same data, and GDELT throttled most of them. Identical requests let the
    # shared timeline cache answer all but the first (sources/gdelt.py).
    gdelt = FakeGDELT()
    pipeline = _pipeline(gdelt)
    for target in (date(2023, 10, 31), date(2025, 1, 31), date(2026, 5, 31)):
        asyncio.run(pipeline.fetch_evidence(target))
    assert len(set(gdelt.requests)) == 1
    [(_, lookback_days, end_date)] = set(gdelt.requests)
    assert end_date == TODAY and end_date - timedelta(days=lookback_days) <= date(2018, 10, 1)


def test_a_month_never_sees_later_coverage():
    gdelt = FakeGDELT(boost=3.0, boost_month=date(2026, 5, 1))
    pipeline = _pipeline(gdelt)
    before = _probabilities(asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31))))
    during = _probabilities(asyncio.run(pipeline.fetch_evidence(date(2026, 5, 31))))
    assert before["AIImageSaturation"] < 0.9 < during["AIImageSaturation"]


def test_a_target_month_without_coverage_is_missing():
    pipeline = _pipeline(FakeGDELT(gap_month=date(2026, 3, 1)))
    with pytest.raises(EvidenceUnavailable):
        asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31)))


def test_december_reads_the_previous_fiscal_year_against_seven_before_it():
    years = range(2017, 2025)
    artists = {y: 300 for y in years} | {2024: 600}
    craft = {y: 30 for y in years} | {2024: 30}  # craft count flat while artists double: share falls
    aic = FakeAIC(artists_by_year={y: a + (y % 2) for y, a in artists.items()}, craft_by_year=craft)
    p = _probabilities(asyncio.run(_pipeline(FakeGDELT(), aic).fetch_evidence(date(2025, 12, 31))))
    assert set(aic.years) == set(years)  # FY2024 (ended June 2024) and seven before it
    assert p["MuseumAcquisitionMomentum"] > 0.9
    assert p["CraftPrestigeRising"] < 0.1


def test_nothing_measured_raises():
    pipeline = _pipeline(FakeGDELT(fail=True))
    with pytest.raises(EvidenceUnavailable):
        asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31)))


def test_craft_types_are_aic_artwork_types():
    assert "Ceramics" in CRAFT_TYPES and "Textile" in CRAFT_TYPES
