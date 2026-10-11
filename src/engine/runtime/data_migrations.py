"""
One-off fixes to stored evidence, run at startup. Each is idempotent; delete
one once no deployed database can still need it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..engine import ProbabilisticOntologyEngine

logger = logging.getLogger(__name__)

_FRIDAY = 4


def move_friday_weekly_records_to_sunday(engine: ProbabilisticOntologyEngine, domain_id: str) -> None:
    """
    REFACTOR_SPEC D12: weekly evidence is dated by the Sunday ending its week.
    The old schedulers dated it by Friday, so move each Friday-dated record
    two days on. If that Sunday already has a record (the API path already
    used Sundays), the Friday one is dropped so the week appears once.
    """

    def to_sunday(ts: datetime) -> datetime | None:
        return ts + timedelta(days=2) if ts.weekday() == _FRIDAY else None

    with engine.db.transaction():
        moved, deleted = engine.evidence_store.restamp(domain_id, to_sunday)
    if moved or deleted:
        logger.info(
            "Re-dated %s weekly evidence to Sundays: %d moved, %d dropped as duplicates of an existing Sunday",
            domain_id, moved, deleted,
        )
