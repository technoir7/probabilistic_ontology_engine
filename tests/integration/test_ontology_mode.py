"""Integration tests for ontology_mode=apriori vs ontology_mode=dynamic.

Tests verify:
- apriori mode is unchanged (existing behaviour preserved)
- dynamic mode is recognized and dispatched (param no longer silently ignored)
- dynamic mode reads POE-A artifacts for art domain
- dynamic mode falls back gracefully when artifacts are absent
- inference/query handles dynamic mode sensibly
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app

# Path to real POE-A artifacts (art domain)
# test file → integration/ → tests/ → probabilistic_ontology_engine/ → suite root
_POEA_ARTIFACTS = (
    Path(__file__).resolve().parents[3]
    / "probabilistic_ontology_engine_abductive"
    / "artifacts"
)
_ARTIFACTS_AVAILABLE = (_POEA_ARTIFACTS / "poea_graph.json").exists()


# ── Shared fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POEA_ARTIFACTS_DIR", str(_POEA_ARTIFACTS))
    with TestClient(api_app.app) as c:
        yield c


@pytest.fixture()
def client_no_artifacts(monkeypatch, tmp_path):
    """Client with POEA_ARTIFACTS_DIR pointing at an empty directory."""
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POEA_ARTIFACTS_DIR", str(tmp_path))  # empty → no artifacts
    with TestClient(api_app.app) as c:
        yield c


# ── apriori mode: unchanged behaviour ─────────────────────────────────────────

def test_apriori_mode_population_status_identical_to_default(client):
    """ontology_mode=apriori returns same shape as omitting the param."""
    default = client.get("/v1/population/status?domain=art")
    apriori = client.get("/v1/population/status?domain=art&ontology_mode=apriori")
    assert default.status_code == 200
    assert apriori.status_code == 200
    d, a = default.json(), apriori.json()
    assert d["domain"] == a["domain"]
    assert d["engine_status"] == a["engine_status"]
    assert set(d.keys()) == set(a.keys())


def test_apriori_mode_candidates_returns_seed_candidates(client):
    """apriori candidates come from the old POE engine (not POE-A artifacts)."""
    res = client.get("/v1/population/candidates?domain=art&ontology_mode=apriori")
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"
    # Old POE art candidates have old POE variable names, not POE-A concept names
    names = [c["name"] for c in body["candidates"]]
    assert not any("POE-A" in n for n in names)


def test_apriori_mode_evidence_returns_engine_records(client):
    """apriori evidence/recent reads from the engine store (empty at startup)."""
    res = client.get("/v1/evidence/recent?domain=art&ontology_mode=apriori")
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"
    assert isinstance(body["records"], list)


def test_apriori_mode_shifts_returns_engine_shifts(client):
    """apriori shifts comes from the engine's shift log."""
    res = client.get("/v1/population/shifts?domain=art&ontology_mode=apriori")
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"


# ── dynamic mode: POE-A artifacts ─────────────────────────────────────────────

@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_status_serves_poea_data(client):
    """dynamic status returns POE-A dominant candidate id (UUID format)."""
    res = client.get("/v1/population/status?domain=art&ontology_mode=dynamic")
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"
    assert body["engine_status"] == "online"
    # POE-A dominant hypothesis name is from poea_dynamic
    assert "POE-A" in body["dominant_hypothesis"]["name"]
    # paradigm_shifts is 0 in dynamic mode
    assert body["paradigm_shifts_this_window"] == 0


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_candidates_named_poea(client):
    """dynamic candidates are labelled 'POE-A Candidate N' from graph artifacts."""
    res = client.get("/v1/population/candidates?domain=art&ontology_mode=dynamic")
    assert res.status_code == 200
    body = res.json()
    names = [c["name"] for c in body["candidates"]]
    assert all("POE-A Candidate" in n for n in names)
    # Confirm 10 candidates (matches poea_graph.json candidate_summaries count)
    assert len(body["candidates"]) == 10


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_candidates_have_required_fields(client):
    """Every dynamic candidate has the required CandidateOut fields."""
    res = client.get("/v1/population/candidates?domain=art&ontology_mode=dynamic")
    assert res.status_code == 200
    for c in res.json()["candidates"]:
        assert "id" in c
        assert "log_score" in c
        assert "evidence_count" in c
        assert "score_normalized" in c
        assert c["status"] in ("dominant", "rising", "falling", "neutral")


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_inference_returns_poea_nodes(client):
    """dynamic inference returns POE-A concept nodes, not old POE art variables."""
    body = {
        "domain": "art",
        "target_variable": "InstitutionalValidationPremium",
        "ontology_mode": "dynamic",
    }
    res = client.post("/v1/inference/query", json=body)
    assert res.status_code == 200
    data = res.json()
    node_names = [n["id"] for n in data["nodes"]]
    # POE-A concept names are present
    assert "InstitutionalValidationPremium" in node_names or any(
        "Institutional" in n for n in node_names
    )
    # Target node is tagged
    target_node = next((n for n in data["nodes"] if n["status"] == "target"), None)
    assert target_node is not None
    assert data["target_probability"] > 0.0


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_inference_fuzzy_target_match(client):
    """dynamic inference accepts apriori-style variable names via fuzzy matching."""
    # CollectorFlightToSafety (apriori) fuzzy-matches FlightToQualityConcentration (dynamic)
    body = {
        "domain": "art",
        "target_variable": "CollectorFlightToSafety",
        "ontology_mode": "dynamic",
    }
    res = client.post("/v1/inference/query", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["target_probability"] > 0.0
    assert len(data["nodes"]) == 11  # 11 POE-A concepts


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_shifts_returns_empty(client):
    """dynamic shifts is always empty (POE-A has no paradigm shift history)."""
    res = client.get("/v1/population/shifts?domain=art&ontology_mode=dynamic")
    assert res.status_code == 200
    body = res.json()
    assert body["total_shifts"] == 0
    assert body["events"] == []
    assert body["domain"] == "Art Prestige Regime"


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_recent_evidence_from_scored_evidence(client):
    """dynamic evidence/recent returns records from scored_evidence.json."""
    res = client.get("/v1/evidence/recent?domain=art&ontology_mode=dynamic&limit=5")
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"
    assert len(body["records"]) <= 5
    for r in body["records"]:
        assert "id" in r
        assert "description" in r
        assert "impact_delta" in r
        assert r["strength"] in ("strong", "shift", "weak")


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_lineage_found(client):
    """dynamic lineage returns a lineage for a known POE-A candidate id."""
    # Load the first candidate id from the real artifacts
    graph_path = _POEA_ARTIFACTS / "poea_graph.json"
    with graph_path.open() as f:
        graph = json.load(f)
    first_cid = graph["candidate_summaries"][0]["candidate_id"]

    res = client.get(
        f"/v1/population/lineage/{first_cid}?domain=art&ontology_mode=dynamic"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["candidate_id"] == first_cid
    assert len(body["events"]) >= 1


@pytest.mark.skipif(not _ARTIFACTS_AVAILABLE, reason="POE-A artifacts not present")
def test_dynamic_mode_lineage_missing_returns_404(client):
    """dynamic lineage for unknown candidate returns 404, not a crash."""
    res = client.get(
        "/v1/population/lineage/00000000-dead-beef-0000-000000000000"
        "?domain=art&ontology_mode=dynamic"
    )
    assert res.status_code == 404


# ── dynamic mode: non-art domain falls back to apriori ────────────────────────

def test_dynamic_mode_non_art_domain_falls_back(client):
    """dynamic mode for non-art domain silently falls back to apriori."""
    res = client.get("/v1/population/status?domain=mr&ontology_mode=dynamic")
    assert res.status_code == 200
    body = res.json()
    # Should be the real macro-regime engine response, not POE-A
    assert body["domain"] == "Macro Regime"
    # POE-A sentinel should NOT appear
    assert "POE-A" not in body["dominant_hypothesis"]["name"]


# ── dynamic mode: missing artifacts fall back gracefully ──────────────────────

def test_dynamic_mode_missing_artifacts_falls_back_to_apriori(client_no_artifacts):
    """dynamic mode with no POE-A artifacts returns apriori data without crashing."""
    res = client_no_artifacts.get(
        "/v1/population/status?domain=art&ontology_mode=dynamic"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["domain"] == "Art Prestige Regime"
    assert body["engine_status"] in ("online", "degraded", "offline")
    # POE-A sentinel absent — fell back to apriori
    assert "POE-A" not in body["dominant_hypothesis"]["name"]


def test_dynamic_mode_missing_artifacts_candidates_fallback(client_no_artifacts):
    """dynamic candidates without artifacts returns apriori (no POE-A Candidate names)."""
    res = client_no_artifacts.get(
        "/v1/population/candidates?domain=art&ontology_mode=dynamic"
    )
    assert res.status_code == 200
    names = [c["name"] for c in res.json()["candidates"]]
    assert not any("POE-A" in n for n in names)


def test_dynamic_mode_missing_artifacts_evidence_fallback(client_no_artifacts):
    """dynamic evidence without artifacts returns apriori (engine store)."""
    res = client_no_artifacts.get(
        "/v1/evidence/recent?domain=art&ontology_mode=dynamic"
    )
    assert res.status_code == 200
    assert res.json()["domain"] == "Art Prestige Regime"


# ── param presence verification ───────────────────────────────────────────────

def test_ontology_mode_param_accepted_on_all_endpoints(client):
    """Confirm all 5 GET endpoints accept ontology_mode without 422."""
    endpoints = [
        "/v1/population/status?domain=art&ontology_mode=apriori",
        "/v1/population/candidates?domain=art&ontology_mode=apriori",
        "/v1/population/shifts?domain=art&ontology_mode=apriori",
        "/v1/evidence/recent?domain=art&ontology_mode=apriori",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"{ep} returned {res.status_code}: {res.text}"


def test_ontology_mode_in_inference_body_accepted(client):
    """POST /v1/inference/query accepts ontology_mode field without 422."""
    body = {
        "domain": "art",
        "target_variable": "InstitutionalRiskAversion",
        "ontology_mode": "apriori",
    }
    res = client.post("/v1/inference/query", json=body)
    assert res.status_code == 200
