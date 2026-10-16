"""
REFACTOR_SPEC 4.5 / B7: a record's id is derived from its domain, date and
source, so fetching the same day twice yields the same id and the store's
ON CONFLICT DO NOTHING deduplicates structurally, not only through the
ingest path's timestamp check.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.domains.sf_urban_v1.ingestion.pipeline import SFUrbanPipeline, SFUrbanSnapshot


def _record(day: date):
    return SFUrbanPipeline.build_evidence_record(SFUrbanSnapshot(target_date=day))


def test_same_day_same_id_different_day_different_id():
    assert _record(date(2026, 3, 1)).evidence_id == _record(date(2026, 3, 1)).evidence_id
    assert _record(date(2026, 3, 1)).evidence_id != _record(date(2026, 3, 8)).evidence_id


def test_snapshot_rejects_misspelled_fields():
    snap = SFUrbanSnapshot(target_date=date(2026, 3, 1))
    with pytest.raises(AttributeError):
        snap.p_tech_hirng_accelerating = 0.9  # typo must not silently add a field
