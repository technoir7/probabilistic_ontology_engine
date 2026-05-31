from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.engine.api import app as api_app


def _write_manual_file(path):
    path.write_text(
        json.dumps(
            {
                "title": "Manual art market prestige signal",
                "url": "https://example.test/art-market-signal",
                "published_at": "2026-05-01T00:00:00Z",
                "publication": "Example Review",
                "notes": "Backend operational smoke fixture.",
                "assignments": {
                    "AIImageSaturation": True,
                    "CraftPrestigeRising": True,
                    "BlueChipConcentration": False,
                },
            }
        ),
        encoding="utf-8",
    )


def test_manual_art_endpoint_persists_and_serves_domain_art(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_path = tmp_path / "manual_art_signal.json"
    _write_manual_file(manual_path)

    with TestClient(api_app.app) as client:
        ingest = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})
        assert ingest.status_code == 200, ingest.text
        ingest_body = ingest.json()
        assert ingest_body["domain_key"] == "art"
        assert ingest_body["domain_module_id"] == "art_prestige_regime_v1"
        assert ingest_body["records_found"] == 1
        assert ingest_body["records_ingested"] == 1
        assert ingest_body["records_skipped_duplicates"] == 0
        assert ingest_body["evidence_count_after"] == 1

        status = client.get("/v1/population/status?domain=art")
        assert status.status_code == 200, status.text
        assert status.json()["domain"] == "Art Prestige Regime"

        learning = client.get("/v1/debug/learning?domain=art")
        assert learning.status_code == 200, learning.text
        assert learning.json()["total_evidence_records"] == 1
        assert learning.json()["dominant_evidence_count"] == 1

        recent = client.get("/v1/evidence/recent?domain=art")
        assert recent.status_code == 200, recent.text
        recent_body = recent.json()
        assert recent_body["domain"] == "Art Prestige Regime"
        assert len(recent_body["records"]) == 1
        assert recent_body["records"][0]["variables_updated"] == 3


def test_manual_art_endpoint_is_idempotent_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_path = tmp_path / "manual_art_signal.json"
    _write_manual_file(manual_path)

    with TestClient(api_app.app) as client:
        first = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})
        second = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["records_ingested"] == 1
    assert second.json()["rebuild_mode"] is True
    assert second.json()["records_ingested"] == 1
    assert second.json()["records_replaced"] == 1
    assert second.json()["records_removed_stale"] == 0
    assert second.json()["records_skipped_duplicates"] == 0
    assert second.json()["records_learned"] == 1
    assert second.json()["evidence_count_before"] == 1
    assert second.json()["evidence_count_after"] == 1


def test_duplicate_only_manual_art_endpoint_learns_existing_uninitialized_rows(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_path = tmp_path / "manual_art_signal.json"
    _write_manual_file(manual_path)

    with TestClient(api_app.app) as client:
        manual_ingest = api_app._import_art_module("manual_ingest")
        engine = api_app.app.state.engines["art"]
        records = manual_ingest.ingest_manual_path(manual_path)
        engine.ingest_batch(records)
        pop = engine.get_population("art_prestige_regime_v1")
        for candidate in pop.active_candidates():
            candidate.evidence_count = 1
            candidate.log_score = -1.0
            engine.population_store.update_score(candidate.candidate_id, -1.0, 1)

        before_debug = client.get("/v1/debug/learning?domain=art")
        assert before_debug.status_code == 200, before_debug.text
        assert before_debug.json()["total_evidence_records"] == 1
        assert before_debug.json()["dominant_evidence_count"] == 1
        assert before_debug.json()["current_generation"] == 0
        assert before_debug.json()["last_learn_timestamp"] is None
        assert before_debug.json()["records_scored_this_session"] == 0

        ingest = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})
        assert ingest.status_code == 200, ingest.text
        body = ingest.json()
        assert body["rebuild_mode"] is True
        assert body["records_ingested"] == 1
        assert body["records_replaced"] == 1
        assert body["records_skipped_duplicates"] == 0
        assert body["records_learned"] == 1
        assert body["evidence_count_after"] == 1

        after_debug = client.get("/v1/debug/learning?domain=art")
        assert after_debug.status_code == 200, after_debug.text
        assert after_debug.json()["total_evidence_records"] == 1
        assert after_debug.json()["dominant_evidence_count"] == 1
        assert after_debug.json()["current_generation"] > 0
        assert after_debug.json()["last_learn_timestamp"] is not None
        assert after_debug.json()["records_scored_this_session"] > 0


def test_duplicate_only_manual_art_endpoint_does_not_relearn_restored_population(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_path = tmp_path / "manual_art_signal.json"
    _write_manual_file(manual_path)

    with TestClient(api_app.app) as client:
        first = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})
        assert first.status_code == 200, first.text

        engine = api_app.app.state.engines["art"]
        engine._learn_call_count.clear()
        engine._learn_last_ts.clear()
        engine._learn_records_total.clear()

        before_debug = client.get("/v1/debug/learning?domain=art")
        assert before_debug.status_code == 200, before_debug.text
        before_body = before_debug.json()
        assert before_body["current_generation"] > 0
        assert before_body["dominant_evidence_count"] == 1
        assert before_body["last_learn_timestamp"] is None

        second = client.post(
            "/v1/ingest/art/manual",
            params={"path": str(manual_path), "append": "true"},
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["rebuild_mode"] is False
        assert second_body["records_ingested"] == 0
        assert second_body["records_skipped_duplicates"] == 1
        assert second_body["records_learned"] == 0

        after_debug = client.get("/v1/debug/learning?domain=art")
        assert after_debug.status_code == 200, after_debug.text
        after_body = after_debug.json()
        assert after_body["dominant_evidence_count"] == 1
        assert after_body["records_scored_this_session"] == 0
        assert after_body["current_generation"] == before_body["current_generation"]


def test_manual_art_endpoint_force_reingests_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    manual_path = tmp_path / "manual_art_signal.json"
    _write_manual_file(manual_path)

    with TestClient(api_app.app) as client:
        first = client.post("/v1/ingest/art/manual", params={"path": str(manual_path)})
        second = client.post(
            "/v1/ingest/art/manual",
            params={"path": str(manual_path), "force": "true", "append": "true"},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["records_ingested"] == 1
    assert second.json()["records_ingested"] == 1
    assert second.json()["records_skipped_duplicates"] == 0
    assert second.json()["evidence_count_before"] == 1
    assert second.json()["evidence_count_after"] == 2


def test_manual_art_endpoint_invalid_json_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    bad_path = tmp_path / "bad.json"
    bad_path.write_text('{"title": "Broken",', encoding="utf-8")

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/art/manual", params={"path": str(bad_path)})

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]
