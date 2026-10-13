"""
The art pipeline's measurements (ingestion/pipeline.py), with fake clients.

AI imagery comes from GDELT news coverage, monthly; museum variables from AIC
acquisitions, once a year in the December record.
Everything else is MISSING in fetched records.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.domains.art_prestige_regime_v1.domain import get_variables
from src.domains.art_prestige_regime_v1.ingestion.aic_client import Acquisitions
from src.domains.art_prestige_regime_v1.ingestion.pipeline import CRAFT_TYPES, ArtPipeline
from src.domains.sources.gdelt import GDELTObs
from src.engine.model.errors import EvidenceUnavailable

NAMES = {v.variable_id: n for n, v in get_variables().items()}


def _months(end: date, n: int) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


class FakeGDELT:
    """Daily points for each month in the window: a flat level, the last month times *boost*."""

    def __init__(self, level=0.002, boost=1.0, fail=False, end_gap=False):
        self.level, self.boost, self.fail, self.end_gap = level, boost, fail, end_gap

    async def fetch_timeline(self, query, label, lookback_days=90, end_date=None):
        if self.fail:
            return []
        months = _months(end_date, 61)
        if self.end_gap:
            months = months[:-1]
        out = []
        for i, m in enumerate(months):
            value = self.level * (self.boost if m == date(end_date.year, end_date.month, 1) else 1) + (i % 3) * 1e-5
            out.append(GDELTObs(obs_date=m, value=value, query_label=label))
        return out[::-1]


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
    pipeline = ArtPipeline(FakeGDELT(boost=3.0), FakeAIC())
    p = _probabilities(asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31))))
    assert p["AIImageSaturation"] > 0.9
    assert p["MuseumAcquisitionMomentum"] is None and p["CraftPrestigeRising"] is None
    assert sum(v is not None for v in p.values()) == 1


def test_a_window_that_does_not_reach_the_target_month_is_missing():
    pipeline = ArtPipeline(FakeGDELT(end_gap=True), FakeAIC())
    with pytest.raises(EvidenceUnavailable):
        asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31)))


def test_december_reads_the_previous_fiscal_year_against_seven_before_it():
    years = range(2018, 2026)
    artists = {y: 300 for y in years} | {2025: 600}
    craft = {y: 30 for y in years} | {2025: 30}  # craft count flat while artists double: share falls
    aic = FakeAIC(artists_by_year={y: a + (y % 2) for y, a in artists.items()}, craft_by_year=craft)
    p = _probabilities(asyncio.run(ArtPipeline(FakeGDELT(), aic).fetch_evidence(date(2026, 12, 31))))
    assert set(aic.years) == set(years)  # FY2025 (ended June 2025) and seven before it
    assert p["MuseumAcquisitionMomentum"] > 0.9
    assert p["CraftPrestigeRising"] < 0.1


def test_nothing_measured_raises():
    pipeline = ArtPipeline(FakeGDELT(fail=True), FakeAIC())
    with pytest.raises(EvidenceUnavailable):
        asyncio.run(pipeline.fetch_evidence(date(2026, 3, 31)))


def test_craft_types_are_aic_artwork_types():
    assert "Ceramics" in CRAFT_TYPES and "Textile" in CRAFT_TYPES
