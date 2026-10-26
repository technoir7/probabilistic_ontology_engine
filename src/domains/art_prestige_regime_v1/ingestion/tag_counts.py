"""One month of a paper's art coverage: how many art articles it ran, and
how many of them carry each of its editors' tags. Counts only: no text.

The server opens a source for every month it fetches, and each month's
signal reads the two years before it, so months read are kept in
PRESS_MONTHS for the whole process (as GDELT_TIMELINE_CACHE is, B24): a
rebuild then asks each paper for each month once."""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True)
class TagCounts:
    articles: int
    tags: Mapping[str, int] = field(default_factory=dict)

    def share(self, tag: str) -> float:
        """The share of the month's art articles carrying *tag*."""
        return self.tags.get(tag, 0) / self.articles


class MonthCache:
    """The newest *max_entries* months read, by (paper, year, month), each for *ttl_s*."""

    def __init__(self, max_entries: int = 1024, ttl_s: float = 6 * 3600,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_s
        self._clock = clock
        self._entries: OrderedDict[tuple[str, int, int], tuple[float, TagCounts]] = OrderedDict()

    def get(self, key: tuple[str, int, int]) -> TagCounts | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() - entry[0] > self._ttl:
            del self._entries[key]
            return None
        return entry[1]

    def put(self, key: tuple[str, int, int], value: TagCounts) -> None:
        self._entries.pop(key, None)
        self._entries[key] = (self._clock(), value)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


# Six hours: a rebuild finishes well inside it, and the latest month's
# archive can still be filling in when it is first read.
PRESS_MONTHS = MonthCache()
