"""
REFACTOR_SPEC B7: re-running ingestion for a date that is already stored must
not append and learn a second copy of that day's evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import ADMIN, freeze_clock, patch_fake_evidence_for_all_domains, running_engine

NOW = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)


def test_trigger_twice_for_the_same_day_stores_and_learns_once(monkeypatch):
    freeze_clock(monkeypatch, NOW)
    patch_fake_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        first = client.post("/v1/ingest/trigger?domain=ng").json()
        second = client.post("/v1/ingest/trigger?domain=ng").json()
        engine = running_engine("ng")
        stored = engine.evidence_store.count("natural-gas-v1")
        scored = engine.get_population("natural-gas-v1").dominant().evidence_count

    assert first["evidence_records_ingested"] == 1
    assert second["evidence_records_ingested"] == 0
    assert stored == 1
    assert scored == 1


def test_overlapping_backfills_store_each_day_once(monkeypatch):
    freeze_clock(monkeypatch, NOW)
    patch_fake_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        client.post("/v1/ingest/backfill?domain=ng&days=10")
        again = client.post("/v1/ingest/backfill?domain=ng&days=14").json()
        stored = running_engine("ng").evidence_store.count("natural-gas-v1")

    assert again["days_successfully_ingested"] == 4
    assert stored == 14
