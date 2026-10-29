"""Each domain's success snapshot (REFACTOR_SPEC D31), read once per process."""
from __future__ import annotations

from functools import cache
from typing import Optional

from ..model.success import Success
from .registry import BY_KEY


@cache
def current_success(key: str) -> Optional[Success]:
    return BY_KEY[key].success()
