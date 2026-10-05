"""
G5 — error-path golden (REFACTOR_SPEC §7 Phase 0.3).

Pins how the API fails today, including the silent fallbacks the refactor will
turn into explicit errors (E4, A8, D6). A behaviour commit that fixes one of
those regenerates this snapshot, so the change is visible in review.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import patch_soft_evidence_for_all_domains

from .snapshot import assert_matches_snapshot

READ_ROUTES = [
    "/v1/population/status",
    "/v1/population/candidates",
    "/v1/population/shifts",
    "/v1/evidence/recent",
    "/v1/export/narrative-snapshot",
    "/v1/debug/entropy",
    "/v1/debug/evidence-geometry",
    "/v1/debug/learning",
    "/v1/debug/structure",
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as c:
        yield c


def _call(client, method: str, url: str, json: dict | None = None) -> dict:
    resp = client.request(method, url, json=json)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return {"status": resp.status_code, "body": body}


def test_g5_error_paths_match_golden(client):
    out: dict = {}
    for route in READ_ROUTES:
        out[f"unknown_domain {route}"] = _call(client, "GET", f"{route}?domain=xx")
    out["unknown_domain report"] = _call(client, "GET", "/v1/report/xx")
    out["unknown_domain trigger"] = _call(client, "POST", "/v1/ingest/trigger?domain=xx")

    out["lineage unknown uuid"] = _call(client, "GET", f"/v1/population/lineage/{uuid.uuid4()}?domain=ng")
    out["backfill days=0"] = _call(client, "POST", "/v1/ingest/backfill?domain=ng&days=0")

    q = {"domain": "ng", "target_variable": "TempAnom"}
    out["inference unknown variable"] = _call(client, "POST", "/v1/inference/query", {**q, "target_variable": "Nope"})
    out["inference fuzzy suffix"] = _call(client, "POST", "/v1/inference/query", {**q, "target_variable": "price_up"})
    # E4: a malformed candidate id silently falls back to the dominant candidate.
    out["inference malformed candidate id"] = _call(client, "POST", "/v1/inference/query", {**q, "candidate_id": "not-a-uuid"})
    out["inference unknown candidate uuid"] = _call(client, "POST", "/v1/inference/query", {**q, "candidate_id": str(uuid.uuid4())})
    # D6: conditions/aggregation are accepted and ignored.
    out["inference with conditions"] = _call(
        client, "POST", "/v1/inference/query",
        {**q, "conditions": {"HeatingDem": True}, "aggregation": "weighted_avg"},
    )

    # A8: ontology_mode is not validated; unknown values fall back to apriori.
    out["status ontology_mode=bogus"] = _call(client, "GET", "/v1/population/status?domain=ng&ontology_mode=bogus")
    out["status ontology_mode=dynamic non-art"] = _call(client, "GET", "/v1/population/status?domain=ng&ontology_mode=dynamic")

    out["report read, nothing cached"] = _call(client, "GET", "/v1/report/ng")
    out["report refresh, no API key"] = _call(client, "POST", "/v1/report/ng/refresh")

    assert_matches_snapshot("g5_error_paths", out)
