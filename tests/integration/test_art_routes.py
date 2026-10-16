"""
The art operator routes: report ingest and rebuild (both need the admin token).

Reports are learned once each, by evidence id; a rebuild forgets the domain
and relearns fetched months and reports together, oldest first.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import ADMIN, freeze_clock, patch_soft_evidence_for_all_domains, running_engine

DOMAIN_ID = "art_prestige_regime_v1"


def _report(tmp_path, name="report.json", published="2026-05-01", url="https://example.test/a"):
    (tmp_path / name).write_text(json.dumps({
        "title": "Art market signal", "url": url, "published_at": published,
        "assignments": {"AIImageSaturation": {"value": True, "confidence": 0.8},
                        "BlueChipConcentration": {"value": False, "confidence": 0.7}},
    }), encoding="utf-8")


def test_reports_are_learned_once(tmp_path):
    _report(tmp_path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with TestClient(api_app.app, headers=ADMIN) as client:
        first = client.post("/v1/ingest/art/manual").json()
        second = client.post("/v1/ingest/art/manual").json()
        engine = running_engine("art")
        stored = engine.evidence_store.count(DOMAIN_ID)

    assert first["records_found"] == 1 and first["records_learned"] == 1
    assert first["files_scanned"] == 2 and len(first["failed"]) == 1 and "broken.json" in first["failed"][0]
    assert second["records_learned"] == 0 and second["records_skipped_duplicates"] == 1
    assert stored == 1


def test_rebuild_relearns_months_and_reports_in_date_order(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    freeze_clock(monkeypatch, datetime(2026, 6, 15, tzinfo=timezone.utc))
    calls = patch_soft_evidence_for_all_domains(monkeypatch)
    _report(tmp_path, published="2026-04-10")
    with TestClient(api_app.app, headers=ADMIN) as client:
        client.post("/v1/ingest/art/manual")  # learned before the rebuild; must not survive twice
        body = client.post("/v1/ingest/art/rebuild", params={"months": 3}).json()
        stored = running_engine("art").evidence_store.load_all(DOMAIN_ID)

    art_months = [d for key, d in calls if key == "art"]
    assert art_months[-3:] == [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]
    assert body["records_learned"] == 4
    assert [r.timestamp.date() for r in stored] == [
        date(2026, 3, 31), date(2026, 4, 10), date(2026, 4, 30), date(2026, 5, 31),
    ]
