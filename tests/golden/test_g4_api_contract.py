"""
G4 — HTTP contract golden (REFACTOR_SPEC §7 Phase 0.3; SPEC TEST-INT-02).

For every registered domain: seed evidence through the real backfill route
(with a fake fetch and a frozen clock), then snapshot every read route.
Phase 5 splits app.py into routers; these snapshots must not move.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import (
    ADMIN,
    domain_keys,
    domain_variables,
    freeze_clock,
    patch_soft_evidence_for_all_domains,
)

from .snapshot import assert_matches_snapshot

# A Wednesday, so weekly and daily calendars both produce several targets.
FROZEN_NOW = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
BACKFILL_DAYS = 21


@pytest.fixture
def client(monkeypatch):
    freeze_clock(monkeypatch, FROZEN_NOW)
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as c:
        yield c


def _get(client, url: str) -> dict:
    resp = client.get(url)
    return {"status": resp.status_code, "body": resp.json()}


def _post(client, url: str, json: dict | None = None) -> dict:
    resp = client.post(url, json=json)
    return {"status": resp.status_code, "body": resp.json()}


@pytest.mark.parametrize("key", domain_keys())
def test_g4_routes_match_golden(client, key):
    out: dict = {}
    out["backfill"] = _post(client, f"/v1/ingest/backfill?domain={key}&days={BACKFILL_DAYS}")

    out["status"] = _get(client, f"/v1/population/status?domain={key}")
    out["candidates"] = _get(client, f"/v1/population/candidates?domain={key}")
    out["shifts"] = _get(client, f"/v1/population/shifts?domain={key}")
    out["evidence_recent"] = _get(client, f"/v1/evidence/recent?domain={key}&limit=100")
    out["narrative_snapshot"] = _get(client, f"/v1/export/narrative-snapshot?domain={key}")
    for name in ("entropy", "evidence-geometry", "learning", "structure"):
        out[f"debug_{name}"] = _get(client, f"/v1/debug/{name}?domain={key}")

    dominant_id = out["status"]["body"]["dominant_hypothesis"]["candidate_id"]
    out["lineage_dominant"] = _get(client, f"/v1/population/lineage/{dominant_id}?domain={key}")

    target = domain_variables(key)[0].name
    out["inference_dominant"] = _post(
        client, "/v1/inference/query", {"domain": key, "target_variable": target}
    )
    # Pins B3: a non-dominant candidate's graph is returned with the dominant's probability.
    others = [c["id"] for c in out["candidates"]["body"]["candidates"] if c["id"] != dominant_id]
    if others:
        out["inference_other_candidate"] = _post(
            client,
            "/v1/inference/query",
            {"domain": key, "target_variable": target, "candidate_id": others[-1]},
        )

    assert_matches_snapshot(f"g4_api_{key}", out)


def test_g4_service_routes_and_openapi_match_golden(client):
    out = {
        "health": _get(client, "/health"),
        "runtime": _get(client, "/runtime"),
        "openapi": api_app.app.openapi(),
    }
    assert_matches_snapshot("g4_api_service_and_openapi", out)
