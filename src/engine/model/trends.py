"""
Trends (REFACTOR_SPEC D30): the broad ideas critics write about, grouped by
meaning from the claims read out of the press, followed year by year
(abductive_engine ART-PLAN §§10–11). Shown as this year's lists: new,
growing, fading and argued over. They describe the present; whether a trend
grows is judged as a case set (D29), where no mechanism has held.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

LISTS = ("new", "growing", "fading", "argued")


@dataclass(frozen=True)
class Trend:
    key: str
    name: str
    start: int                       # first year broad (many writers, many subjects)
    words: tuple[str, ...]           # the words that set it apart
    writers: tuple[int, ...]         # writers each year of TrendLists.years
    papers: tuple[str, ...]          # papers it was in this year
    verdicts: tuple[int, int]        # approvals, disapprovals this year
    sample: tuple[str, ...]          # a few of this year's claims, as the reader put them


@dataclass(frozen=True)
class TrendLists:
    year: int                        # years end in September
    before: int                      # years this one is set against
    years: tuple[int, ...]
    all_writers: tuple[int, ...]     # every writer each year
    lists: Mapping[str, tuple[str, ...]]
    trends: Mapping[str, Trend]

    def share(self, key: str, year: int) -> float:
        i = self.years.index(year)
        return self.trends[key].writers[i] / self.all_writers[i] if self.all_writers[i] else 0.0

    def share_before(self, key: str) -> float:
        """Average share over the BEFORE years before this one."""
        return sum(self.share(key, y) for y in range(self.year - self.before, self.year)) / self.before

    def listed(self, name: str) -> tuple[Trend, ...]:
        return tuple(self.trends[k] for k in self.lists[name])
