"""
Monthly evidence for art_prestige_regime_v1 from objective series.

Every measured variable follows one rule: take the series up to the target
month, z-score its latest value against its own trailing history, and map
the z-score to P(True) with the shared clamped sigmoid. No hand-set levels:
"rising" means "high for this series". A variable with no series, or too
little history, is MISSING, and is left to the hand-supplied reports
(reports.py), which are the only evidence for most market variables.

Series (MEASURES below says which variable reads which):
* Wikipedia pageviews (monthly): public attention to a topic.
* Art Institute of Chicago acquisitions (fiscal year, ends June 30): the
  share of a year's acquisitions matching some terms. Shares, because recent
  years' counts keep rising as cataloguing catches up. Annual, so these
  variables are observed once a year, in the December record for the fiscal
  year that ended the June before, and are MISSING in other months; repeating
  one yearly value twelve times would count it twelve times.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from ....engine.schemas import EvidenceRecord
from ...sources.soft_evidence import build_soft_record, soft_bool, zscore
from ..domain import DOMAIN_MODULE_ID, VARIABLES, get_variables
from .aic_client import AICClient
from .wikipedia_client import WikipediaClient

# Two years of history behind the latest month: enough for a stable z-score,
# short enough to follow a change in what "normal" attention is.
PAGEVIEW_MONTHS = 25
MIN_PAGEVIEW_HISTORY = 12
# Fiscal years compared with the latest one.
AIC_YEARS = 8
MIN_AIC_HISTORY = 4
AIC_REPORT_MONTH = 12


@dataclass(frozen=True)
class Pageviews:
    """Sum of monthly views across *articles*."""
    articles: Sequence[str]


@dataclass(frozen=True)
class AcquisitionShare:
    """Share of AIC acquisitions matching any of *any_of* ({field: [terms]})."""
    any_of: Mapping[str, Sequence[str]]


Measure = Pageviews | AcquisitionShare

MEASURES: dict[str, Measure] = {}


def signal(series: Sequence[float], min_history: int) -> float | None:
    """z-score of the last value against the ones before it; None with too little history."""
    if len(series) < min_history + 1:
        return None
    return zscore(series[-1], list(series[:-1]))


class ArtPipeline:
    def __init__(self, wikipedia: WikipediaClient, aic: AICClient) -> None:
        self._wikipedia = wikipedia
        self._aic = aic

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        names = list(MEASURES)
        signals = await asyncio.gather(*(self._signal(MEASURES[n], target_date) for n in names))
        z = {n: s for n, s in zip(names, signals) if s is not None}
        p = {n: soft_bool(z[n], 0.05, 0.95) for n in z}
        return build_soft_record(
            module_id=DOMAIN_MODULE_ID,
            variables=get_variables(),
            states=[(n, p.get(n, 0.5) > 0.5, p.get(n, 0.5)) for n in VARIABLES],
            confidence={},
            target_date=target_date,
            source_ref=f"wikipedia-pageviews+artic.edu@month-ending-{target_date}",
            missing=[n for n in VARIABLES if n not in p],
        )

    async def _signal(self, measure: Measure, target_date: date) -> float | None:
        if isinstance(measure, Pageviews):
            return await self._pageview_signal(measure, target_date)
        return await self._acquisition_signal(measure, target_date)

    async def _pageview_signal(self, measure: Pageviews, target_date: date) -> float | None:
        per_article = await asyncio.gather(*(
            self._wikipedia.monthly_views(a, end=target_date, months=PAGEVIEW_MONTHS) for a in measure.articles
        ))
        if any(not views for views in per_article):
            return None  # a missing article would shift the sum
        months = sorted(set.intersection(*(set(m for m, _ in views) for views in per_article)))
        totals = [sum(dict(views)[m] for views in per_article) for m in months]
        return signal(totals, MIN_PAGEVIEW_HISTORY)

    async def _acquisition_signal(self, measure: AcquisitionShare, target_date: date) -> float | None:
        if target_date.month != AIC_REPORT_MONTH:
            return None
        latest = target_date.year if target_date.month >= 7 else target_date.year - 1
        years = list(range(latest - AIC_YEARS + 1, latest + 1))
        totals = await asyncio.gather(*(self._aic.acquisitions(y) for y in years))
        matches = await asyncio.gather(*(self._aic.acquisitions(y, measure.any_of) for y in years))
        shares = [m / t for t, m in zip(totals, matches) if t and m is not None]
        if len(shares) != len(years):
            return None
        return signal(shares, MIN_AIC_HISTORY)
