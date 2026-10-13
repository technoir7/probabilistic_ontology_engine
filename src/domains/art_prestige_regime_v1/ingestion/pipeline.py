"""
Monthly evidence for art_prestige_regime_v1 from objective series.

Every measured variable follows one rule: take its series up to the target
month, z-score the latest value against the series' own trailing history,
and map the z-score to P(True) with the shared clamped sigmoid. No hand-set
levels: "elevated" means "high for this series".

Only three of the 25 variables have a series that measures them acceptably
(free, objective, backfillable; checked 2026-10-13):

* AIImageSaturation — GDELT: the monthly share of all monitored news that
  mentions "AI-generated" in articles about artists, against the five years
  before. Coverage rose from ~0 before 2022 and has stayed high. Wikipedia
  views of the AI-image tools were tried and rejected: they peaked in
  2022-23 and fell as the tools became ordinary, the opposite of saturation.
* MuseumAcquisitionMomentum — distinct artists the Art Institute of Chicago
  acquired in a fiscal year (artists, not objects: one gift was 4,780
  objects in FY2023).
* CraftPrestigeRising — the share of those artists acquired in craft media.

The museum series are annual. They are observed once a year, in the December
record, for the fiscal year that ended 18 months earlier (cataloguing fills
recent years in late, which would make every latest year look low), and are
MISSING in the other months: repeating one yearly value twelve times would
count it twelve times. One museum is a narrow view and single gifts move it.

Everything else is MISSING in fetched records and comes only from the
hand-labelled reports (reports.py). There is no free machine-readable art
auction or sales data, so all seven market variables are reports-only. Weak
proxies considered and left out are listed in REFACTOR_SPEC (B23); adding a
measure is one MEASURES entry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from ....engine.schemas import EvidenceRecord
from ...sources.soft_evidence import build_soft_record, soft_bool, zscore
from ..domain import DOMAIN_MODULE_ID, VARIABLES, get_variables
from ...sources.gdelt import GDELTClient
from .aic_client import AICClient

# Five years behind the latest month, so a lasting rise reads as high rather
# than as the new normal; GDELT starts in 2017.
NEWS_MONTHS = 61
MIN_NEWS_HISTORY = 24
# The latest fiscal year and the seven before it (about 8 points exist since
# 2018 at the museum's current cataloguing; a longer window would mix eras).
AIC_YEARS = 8
MIN_AIC_HISTORY = 4
AIC_REPORT_MONTH = 12

AI_IMAGERY_QUERY = '"AI-generated" theme:TAX_FNCACT_ARTIST sourcelang:english'
CRAFT_TYPES = ("Ceramics", "Textile", "Glass", "Basketry", "Furniture", "Metalwork", "Vessel", "Coverings and Hangings")


@dataclass(frozen=True)
class NewsShare:
    """GDELT: monthly mean share of all monitored news matching *query*."""
    query: str


@dataclass(frozen=True)
class ArtistsAcquired:
    """Distinct artists AIC acquired in the fiscal year."""


@dataclass(frozen=True)
class ArtistShare:
    """Share of the year's distinct artists acquired in *artwork_types*."""
    artwork_types: Sequence[str]


Measure = NewsShare | ArtistsAcquired | ArtistShare

MEASURES: dict[str, Measure] = {
    "AIImageSaturation": NewsShare(AI_IMAGERY_QUERY),
    "MuseumAcquisitionMomentum": ArtistsAcquired(),
    "CraftPrestigeRising": ArtistShare(CRAFT_TYPES),
}


def signal(series: Sequence[float], min_history: int) -> float | None:
    """z-score of the last value against the ones before it; None with too little history."""
    if len(series) < min_history + 1:
        return None
    return zscore(series[-1], list(series[:-1]))


def reported_fiscal_years(target_date: date) -> list[int] | None:
    """The fiscal years a target month reads (oldest first), or None outside the report month."""
    if target_date.month != AIC_REPORT_MONTH:
        return None
    latest = target_date.year - 1  # ended June 30, 18 months before this December
    return list(range(latest - AIC_YEARS + 1, latest + 1))


class ArtPipeline:
    def __init__(self, gdelt: GDELTClient, aic: AICClient) -> None:
        self._gdelt = gdelt
        self._aic = aic

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        z: dict[str, float] = {}
        # One measure at a time: GDELT allows one request per 5 seconds.
        for name, measure in MEASURES.items():
            s = await self._signal(measure, target_date)
            if s is not None:
                z[name] = s
        p = {n: soft_bool(z[n], 0.05, 0.95) for n in z}
        return build_soft_record(
            module_id=DOMAIN_MODULE_ID,
            variables=get_variables(),
            states=[(n, p.get(n, 0.5) > 0.5, p.get(n, 0.5)) for n in VARIABLES],
            confidence={},
            target_date=target_date,
            source_ref=f"gdelt+artic.edu@month-ending-{target_date}",
            missing=[n for n in VARIABLES if n not in p],
        )

    async def _signal(self, measure: Measure, target_date: date) -> float | None:
        if isinstance(measure, NewsShare):
            return await self._news_signal(measure, target_date)
        years = reported_fiscal_years(target_date)
        if years is None:
            return None
        if isinstance(measure, ArtistsAcquired):
            totals = [await self._aic.acquisitions(y) for y in years]
            if any(t is None for t in totals):
                return None
            return signal([t.artists for t in totals], MIN_AIC_HISTORY)
        totals = [await self._aic.acquisitions(y) for y in years]
        matches = [await self._aic.acquisitions(y, measure.artwork_types) for y in years]
        if any(t is None or not t.artists for t in totals) or any(m is None for m in matches):
            return None
        return signal([m.artists / t.artists for t, m in zip(totals, matches)], MIN_AIC_HISTORY)

    async def _news_signal(self, measure: NewsShare, target_date: date) -> float | None:
        first = date(target_date.year - NEWS_MONTHS // 12, target_date.month, 1)
        obs = await self._gdelt.fetch_timeline(
            measure.query, "art-ai-imagery",
            lookback_days=(target_date - first).days, end_date=target_date,
        )
        if not obs:
            return None
        by_month: dict[date, list[float]] = defaultdict(list)
        for o in obs:
            by_month[o.obs_date.replace(day=1)].append(o.value)
        if target_date.replace(day=1) not in by_month:
            return None  # the target month itself must be covered
        months = sorted(by_month)
        return signal([sum(by_month[m]) / len(by_month[m]) for m in months], MIN_NEWS_HISTORY)
