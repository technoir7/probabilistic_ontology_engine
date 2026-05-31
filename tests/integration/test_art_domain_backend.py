from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient

from src.engine.api import app as api_app


def test_art_domain_registered_and_manual_evidence_reaches_store(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_ingest = api_app._import_art_module("manual_ingest")
    domain_module = api_app._import_art_module("domain")

    manual_path = tmp_path / "manual_art_signal.json"
    manual_path.write_text(
        json.dumps(
            {
                "title": "Manual art market prestige signal",
                "url": "https://example.test/art-market-signal",
                "published_at": "2026-05-01T00:00:00Z",
                "assignments": {
                    "AIImageSaturation": True,
                    "CraftPrestigeRising": True,
                    "BlueChipConcentration": False,
                },
                "publication": "Example Review",
                "notes": "Backend smoke fixture.",
            }
        ),
        encoding="utf-8",
    )
    manual_records = manual_ingest.ingest_manual_path(manual_path)
    assert len(manual_records) == 1

    async def fake_fetch_evidence_record(domain_key: str, target_date: date):
        assert domain_key == "art"
        return manual_records[0]

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch_evidence_record)

    with TestClient(api_app.app) as client:
        status = client.get("/v1/population/status?domain=art")
        assert status.status_code == 200, status.text
        assert status.json()["domain"] == "Art Prestige Regime"

        candidates = client.get("/v1/population/candidates?domain=art")
        assert candidates.status_code == 200, candidates.text
        assert len(candidates.json()["candidates"]) == len(domain_module.SEED_CANDIDATES)

        snapshot = client.get("/v1/export/narrative-snapshot?domain=art")
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["metadata"]["domain_module_id"] == domain_module.DOMAIN_MODULE_ID
        assert len(snapshot.json()["current_regime_state"]) == len(domain_module.VARIABLES)

        trigger = client.post("/v1/ingest/trigger?domain=art")
        assert trigger.status_code == 200, trigger.text
        assert trigger.json()["evidence_records_ingested"] == 1

        engine = api_app.app.state.engines["art"]
        assert engine.evidence_store.count(domain_module.DOMAIN_MODULE_ID) == 1

        recent = client.get("/v1/evidence/recent?domain=art")
        assert recent.status_code == 200, recent.text
        body = recent.json()
        assert body["domain"] == "Art Prestige Regime"
        assert len(body["records"]) == 1
        assert body["records"][0]["variables_updated"] == 3
