"""Each domain's trend lists (REFACTOR_SPEC D30): a static snapshot shipped
with the domain, read once per process and kept."""
from __future__ import annotations

from functools import cache
from typing import Optional

from ..model.trends import TrendLists
from .registry import BY_KEY


@cache
def current_trends(key: str) -> Optional[TrendLists]:
    return BY_KEY[key].trend_lists()
