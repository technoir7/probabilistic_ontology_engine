"""Each domain's case reports (REFACTOR_SPEC D29). The case sets are static
snapshots shipped with the domain, so a report is computed once per process
(file reads and the case engine over every case-year: about 15 s on a laptop,
over a minute on the server) and kept."""
from __future__ import annotations

import threading
from functools import cache

from ..services.cases import CaseReport, case_report
from .registry import BY_KEY, REGISTRY

# A request that arrives while another computes waits for it, rather than computing again.
_computing = threading.Lock()


def compute_case_reports(key: str) -> tuple[CaseReport, ...]:
    """Slow the first time in a process (see above); blocks, so call it off the event loop."""
    with _computing:
        return _case_reports(key)


@cache
def _case_reports(key: str) -> tuple[CaseReport, ...]:
    return tuple(case_report(s) for s in BY_KEY[key].case_sets())



def warm_case_reports() -> None:
    """Compute every domain's case reports, so the first visitor does not wait for them."""
    for reg in REGISTRY:
        compute_case_reports(reg.key)
