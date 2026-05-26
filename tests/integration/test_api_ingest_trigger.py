from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from src.domains.natural_gas_v1.domain import get_variables
from src.engine.api import app as api_app
from src.engine.schemas import EvidenceRecord, ObservedAssignment, SourceType


def test_ingest_trigger_fetches_ingests_and_updates_population(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    async def fake_fetch_evidence_record(
        domain_key: str,
        target_date: date,
    ) -> EvidenceRecord:
        assert domain_key == "ng"
        variables = get_variables()
        return EvidenceRecord(
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=variables["TempAnom"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["HeatingDem"].variable_id,
                    observed_value=False,
                ),
                ObservedAssignment(
                    variable_id=variables["StorageDraw"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["PriceUp"].variable_id,
                    observed_value=True,
                ),
            ],
            source_type=SourceType.API,
            source_ref=f"test@{target_date}",
            confidence=1.0,
        )

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch_evidence_record)

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/trigger?domain=ng")

        assert response.status_code == 200
        body = response.json()
        assert body["domain"] == "Natural Gas"
        assert body["evidence_records_ingested"] == 1
        assert body["population_status"]["domain"] == "Natural Gas"
        assert body["population_status"]["last_evidence_cycle_ago"] != "never"

        engine = api_app.app.state.engines["ng"]
        assert engine.evidence_store.count("natural-gas-v1") == 1
        assert engine.get_population("natural-gas-v1").dominant().evidence_count == 1


def test_ingest_backfill_fetches_and_ingests_days_sequentially(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    seen_dates: list[date] = []

    async def fake_fetch_evidence_record(
        domain_key: str,
        target_date: date,
    ) -> EvidenceRecord:
        assert domain_key == "ng"
        seen_dates.append(target_date)
        variables = get_variables()
        return EvidenceRecord(
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=variables["TempAnom"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["HeatingDem"].variable_id,
                    observed_value=False,
                ),
                ObservedAssignment(
                    variable_id=variables["StorageDraw"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["PriceUp"].variable_id,
                    observed_value=True,
                ),
            ],
            source_type=SourceType.API,
            source_ref=f"test@{target_date}",
            confidence=1.0,
        )

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch_evidence_record)

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/backfill?domain=ng&days=3")

        assert response.status_code == 200
        body = response.json()
        assert body["domain"] == "Natural Gas"
        assert body["days_requested"] == 3
        assert body["days_successfully_ingested"] == 3
        assert seen_dates == sorted(seen_dates)
        assert len(seen_dates) == 3

        engine = api_app.app.state.engines["ng"]
        assert engine.evidence_store.count("natural-gas-v1") == 3


def test_inference_query_non_uuid_candidate_id_falls_back_to_active_candidate(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as client:
        response = client.post(
            "/v1/inference/query",
            json={
                "domain": "ng",
                "target_variable": "PriceUp",
                "candidate_id": "cand-004",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["candidate_id"]
        assert body["target_variable"] == "PriceUp"
