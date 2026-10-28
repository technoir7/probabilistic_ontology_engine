"""Each domain's case reports (REFACTOR_SPEC D29). The case sets are static
snapshots shipped with the domain, so a report is computed once per process
(file reads and the case engine over every case-year: under a second for
art) and kept."""
from __future__ import annotations

from functools import cache

from ..services.cases import CaseReport, case_report
from .registry import BY_KEY


@cache
def compute_case_reports(key: str) -> tuple[CaseReport, ...]:
    return tuple(case_report(s) for s in BY_KEY[key].case_sets())
