"""
Monthly evidence for art_prestige_regime_v1 (docs/art-evidence-plan.md).

- **Talk** (monthly): the share of a paper's art articles that carry one of
  its editors' tags, read against the two years before it, so a topic that
  rose and stayed reads ordinary again and a change in the editors' tagging
  habits fades out. Discourse is the evidence itself, not a noisy sample of
  something else, so no month is discarded for being small next to chance.
  Guardian tags are read from 2010, when its scheme settled.
- **Report figures** (yearly, in April): ingestion/figures.py.
- **Museum acquisitions** (yearly, in December): distinct artists the Art
  Institute of Chicago acquired in the fiscal year that ended 18 months
  before, and the Cleveland Museum of Art in the calendar year that ended
  12 months before (cataloguing fills recent years in late), each against
  its own seven years before; the signal is the mean of those available.
  Last year's level is given too (plan §7).

A signal with no input is MISSING; repeating a yearly value twelve times
would count it twelve times.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Protocol

from ....engine.schemas import EvidenceRecord
from ...sources.grades import build_graded_record
from ...sources.soft_evidence import zscore
from ...sources.structure import with_lags
from ..domain import DOMAIN_MODULE_ID, TALK, get_variables
from .aic_client import AICClient
from .cma_client import CMAClient
from .figures import Figures, figure_signals, load_figures
from .tag_counts import TagCounts

TALK_MONTHS = 24
MIN_TALK_HISTORY = 12
PAPER_START = {"guardian": (2010, 1), "nyt": (2000, 1)}
MUSEUM_MONTH = 12
MUSEUM_YEARS = 8   # the year read and the seven before it
MIN_MUSEUM_HISTORY = 4

_VARIABLES = with_lags(DOMAIN_MODULE_ID, get_variables())


class Paper(Protocol):
    async def month(self, year: int, month: int) -> TagCounts | None: ...


def _months_back(target: date, n: int) -> list[tuple[int, int]]:
    """The n months before *target*'s month, oldest first."""
    y, m, out = target.year, target.month, []
    for _ in range(n):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        out.append((y, m))
    return out[::-1]


def _against_past(by_year: Mapping[int, float], year: int) -> float | None:
    past = [by_year[y] for y in range(year - MUSEUM_YEARS + 1, year) if y in by_year]
    if year not in by_year or len(past) < MIN_MUSEUM_HISTORY:
        return None
    return zscore(by_year[year], past)


def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


class ArtPipeline:
    def __init__(self, papers: Mapping[str, Paper], aic: AICClient, cma: CMAClient,
                 figures: Figures | None = None) -> None:
        self._papers = papers
        self._aic = aic
        self._cma = cma
        self._figures = load_figures() if figures is None else figures
        self._aic_years: dict[int, int] = {}

    async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
        signals: dict[str, float] = {}
        for paper in self._papers:
            signals |= await self._talk(paper, target_date)
        figures, previous = figure_signals(self._figures, target_date)
        signals |= figures
        if target_date.month == MUSEUM_MONTH:
            now, prev = await self._museums(target_date.year)
            if now is not None:
                signals["MuseumAcquisitionMomentum"] = now
                if prev is not None:
                    previous["MuseumAcquisitionMomentum"] = prev
        return build_graded_record(
            module_id=DOMAIN_MODULE_ID, variables=_VARIABLES, signals=signals, previous=previous,
            confidence={}, target_date=target_date,
            source_ref=f"guardian+nyt+reports+artic.edu+clevelandart.org@month-ending-{target_date}",
        )

    async def _month(self, paper: str, year: int, month: int) -> TagCounts | None:
        counts = await self._papers[paper].month(year, month)
        return None if counts is None or counts.articles == 0 else counts

    async def _talk(self, paper: str, target: date) -> dict[str, float]:
        start = PAPER_START[paper]
        if (target.year, target.month) < start:
            return {}
        current = await self._month(paper, target.year, target.month)
        if current is None:
            return {}
        history = [c for ym in _months_back(target, TALK_MONTHS) if ym >= start
                   and (c := await self._month(paper, *ym)) is not None]
        if len(history) < MIN_TALK_HISTORY:
            return {}
        return {name: zscore(current.share(tag), [c.share(tag) for c in history])
                for name, (p, tag) in TALK.items() if p == paper}

    async def _museums(self, december: int) -> tuple[float | None, float | None]:
        """(this December's signal, last December's)."""
        fiscal = december - 1          # Chicago's year ended June 30, 18 months before
        calendar = december - 1        # Cleveland's ended 12 months before
        for fy in range(fiscal - MUSEUM_YEARS, fiscal + 1):
            if fy not in self._aic_years and (got := await self._aic.acquisitions(fy)) is not None:
                self._aic_years[fy] = got.artists
        cma = await self._cma.artists_by_year() or {}
        now = _mean([_against_past(self._aic_years, fiscal), _against_past(cma, calendar)])
        prev = _mean([_against_past(self._aic_years, fiscal - 1), _against_past(cma, calendar - 1)])
        return now, prev
