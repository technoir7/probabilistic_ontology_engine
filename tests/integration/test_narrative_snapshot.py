"""
Tests for GET /v1/export/narrative-snapshot.

TEST-NS-01 : endpoint returns 200 for all active domains (ng, zc, zs, mr)
TEST-NS-02 : response contains all required top-level keys
TEST-NS-03 : current_regime_state has correct variable count per domain
TEST-NS-04 : interpretation_hints is a non-empty list of strings
TEST-NS-05 : metadata fields have correct types and domain values
TEST-NS-06 : ontology_competition has required sub-keys
TEST-NS-07 : dominant_hypothesis is present and well-formed when available
TEST-NS-08 : competing_candidates reflects active population
TEST-NS-09 : frontier has correct structure
TEST-NS-10 : unknown domain returns 404
TEST-NS-11 : regime_state probabilities come from inference, not raw evidence
TEST-NS-12 : regime_state null when no evidence ingested
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app

# Expected variable counts per domain short key
_DOMAIN_VAR_COUNTS: dict[str, int] = {
    "ng": 4,   # TempAnom, HeatingDem, StorageDraw, PriceUp
    "zc": 4,   # PlantingDelayed, DroughtIndex, YieldForecastDown, CornPriceUp
    "zs": 4,   # PlantingDelayed, DroughtIndex, YieldForecastDown, SoyPriceUp
    "mr": 8,   # YieldCurveInverted … AIRiskOn
}

_DOMAIN_MODULE_IDS: dict[str, str] = {
    "ng": "natural-gas-v1",
    "zc": "corn-v1",
    "zs": "soybean-v1",
    "mr": "macro-regime-v1",
}

_REQUIRED_TOP_LEVEL_KEYS = {
    "metadata",
    "current_regime_state",
    "dominant_hypothesis",
    "competing_candidates",
    "ontology_competition",
    "frontier",
    "interpretation_hints",
}

_REQUIRED_METADATA_KEYS = {"domain", "domain_module_id", "timestamp", "evidence_count", "current_generation"}
_REQUIRED_ONTOLOGY_KEYS = {
    "structure_entropy",
    "entropy_interpretation",
    "active_candidates",
    "paradigm_shifts_total",
    "recent_shifts",
}
_REQUIRED_FRONTIER_KEYS = {"frontier_edge_count", "frontier_edges"}
_REQUIRED_COMPETING_KEYS = {"candidates", "score_gap_to_dominant"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """
    Single TestClient shared across all NS tests.
    No scheduler, fresh in-memory DBs in a temp directory.
    """
    import os
    tmp = tmp_path_factory.mktemp("ns_test")
    os.environ["EVIDENCE_SCHEDULER_ENABLED"] = "false"
    os.environ["POE_DATA_DIR"] = str(tmp)
    with TestClient(api_app.app) as c:
        yield c


# ---------------------------------------------------------------------------
# TEST-NS-01 : 200 for all domains
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", ["ng", "zc", "zs", "mr"])
def test_ns_01_returns_200_all_domains(client, domain):
    """Snapshot endpoint must respond 200 for every active domain."""
    resp = client.get(f"/v1/export/narrative-snapshot?domain={domain}")
    assert resp.status_code == 200, (
        f"Expected 200 for domain={domain}, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# TEST-NS-02 : required top-level keys
# ---------------------------------------------------------------------------

def test_ns_02_required_top_level_keys(client):
    """Response must contain all seven required top-level keys."""
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    body = resp.json()
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        assert key in body, f"Missing top-level key: '{key}'"


# ---------------------------------------------------------------------------
# TEST-NS-03 : current_regime_state has correct variable count per domain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain,expected_count", list(_DOMAIN_VAR_COUNTS.items()))
def test_ns_03_regime_state_variable_count(client, domain, expected_count):
    """current_regime_state must list exactly the right number of variables."""
    resp = client.get(f"/v1/export/narrative-snapshot?domain={domain}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    regime = body["current_regime_state"]
    assert isinstance(regime, list), "current_regime_state must be a list"
    assert len(regime) == expected_count, (
        f"domain={domain}: expected {expected_count} variables, got {len(regime)}: "
        f"{[r['name'] for r in regime]}"
    )


# ---------------------------------------------------------------------------
# TEST-NS-04 : interpretation_hints is a non-empty list of strings
# ---------------------------------------------------------------------------

def test_ns_04_interpretation_hints_nonempty(client):
    """interpretation_hints must be a non-empty list, each item a string."""
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    body = resp.json()
    hints = body["interpretation_hints"]
    assert isinstance(hints, list), "interpretation_hints must be a list"
    assert len(hints) > 0, "interpretation_hints must not be empty"
    for h in hints:
        assert isinstance(h, str), f"Each hint must be a string, got {type(h)}: {h!r}"


# ---------------------------------------------------------------------------
# TEST-NS-05 : metadata fields have correct types and domain values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", ["ng", "zc", "zs", "mr"])
def test_ns_05_metadata_fields(client, domain):
    """metadata must contain correct domain_module_id and integer types."""
    resp = client.get(f"/v1/export/narrative-snapshot?domain={domain}")
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata"]

    for key in _REQUIRED_METADATA_KEYS:
        assert key in meta, f"Missing metadata key: '{key}'"

    assert meta["domain_module_id"] == _DOMAIN_MODULE_IDS[domain], (
        f"domain_module_id mismatch for domain={domain}"
    )
    assert isinstance(meta["evidence_count"], int)
    assert meta["evidence_count"] >= 0
    assert isinstance(meta["current_generation"], int)
    assert meta["current_generation"] >= 0
    # Timestamp must be a non-empty ISO string
    assert isinstance(meta["timestamp"], str) and len(meta["timestamp"]) > 0


# ---------------------------------------------------------------------------
# TEST-NS-06 : ontology_competition sub-keys
# ---------------------------------------------------------------------------

def test_ns_06_ontology_competition_structure(client):
    """ontology_competition must contain all required sub-fields."""
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    oc = resp.json()["ontology_competition"]

    for key in _REQUIRED_ONTOLOGY_KEYS:
        assert key in oc, f"Missing ontology_competition key: '{key}'"

    assert isinstance(oc["structure_entropy"], float)
    assert oc["structure_entropy"] >= 0.0
    assert oc["entropy_interpretation"] in ("low", "medium", "high"), (
        f"entropy_interpretation must be low/medium/high, got {oc['entropy_interpretation']!r}"
    )
    assert isinstance(oc["active_candidates"], int)
    assert oc["active_candidates"] >= 0
    assert isinstance(oc["paradigm_shifts_total"], int)
    assert oc["paradigm_shifts_total"] >= 0
    assert isinstance(oc["recent_shifts"], list)
    # Each shift has required keys
    for shift in oc["recent_shifts"]:
        assert "timestamp" in shift
        assert "from_name" in shift
        assert "to_name" in shift
        assert "generation" in shift


# ---------------------------------------------------------------------------
# TEST-NS-07 : dominant_hypothesis is well-formed when present
# ---------------------------------------------------------------------------

def test_ns_07_dominant_hypothesis_schema(client):
    """
    dominant_hypothesis may be null on a fresh engine but, when present,
    must contain all required fields with correct types.
    """
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    body = resp.json()
    dh = body["dominant_hypothesis"]

    if dh is None:
        return  # Acceptable on a cold engine with no evidence

    for key in ("name", "candidate_id", "edge_count", "edges", "generations_dominant", "log_score"):
        assert key in dh, f"Missing dominant_hypothesis key: '{key}'"

    assert isinstance(dh["edge_count"], int) and dh["edge_count"] >= 0
    assert isinstance(dh["generations_dominant"], int) and dh["generations_dominant"] >= 0
    assert isinstance(dh["log_score"], float)
    assert isinstance(dh["edges"], list)
    for edge in dh["edges"]:
        assert "source" in edge and "target" in edge and "existence_probability" in edge
        assert isinstance(edge["existence_probability"], float)


# ---------------------------------------------------------------------------
# TEST-NS-08 : competing_candidates reflects active population
# ---------------------------------------------------------------------------

def test_ns_08_competing_candidates_schema(client):
    """competing_candidates must list active candidates with required fields."""
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    cc = resp.json()["competing_candidates"]

    for key in _REQUIRED_COMPETING_KEYS:
        assert key in cc, f"Missing competing_candidates key: '{key}'"

    assert isinstance(cc["candidates"], list)
    # score_gap_to_dominant is either null or a float
    gap = cc["score_gap_to_dominant"]
    assert gap is None or isinstance(gap, float), (
        f"score_gap_to_dominant must be null or float, got {type(gap)}"
    )
    for cand in cc["candidates"]:
        for key in ("name", "log_score", "edge_count", "status", "score_normalized"):
            assert key in cand, f"Missing candidate key: '{key}'"
        assert cand["status"] in ("dominant", "rising", "falling", "neutral")
        assert 0.0 <= cand["score_normalized"] <= 1.0


# ---------------------------------------------------------------------------
# TEST-NS-09 : frontier has correct structure
# ---------------------------------------------------------------------------

def test_ns_09_frontier_structure(client):
    """frontier must have frontier_edge_count and frontier_edges list."""
    resp = client.get("/v1/export/narrative-snapshot?domain=ng")
    assert resp.status_code == 200
    frontier = resp.json()["frontier"]

    for key in _REQUIRED_FRONTIER_KEYS:
        assert key in frontier, f"Missing frontier key: '{key}'"

    assert isinstance(frontier["frontier_edge_count"], int)
    assert frontier["frontier_edge_count"] >= 0
    assert isinstance(frontier["frontier_edges"], list)
    assert frontier["frontier_edge_count"] == len(frontier["frontier_edges"])
    for edge in frontier["frontier_edges"]:
        assert "source" in edge and "target" in edge
        assert "probability" in edge and "relation" in edge


# ---------------------------------------------------------------------------
# TEST-NS-10 : unknown domain returns 404
# ---------------------------------------------------------------------------

def test_ns_10_unknown_domain_returns_404(client):
    """Requesting a domain that does not exist must return 404."""
    resp = client.get("/v1/export/narrative-snapshot?domain=xx")
    assert resp.status_code == 404, (
        f"Expected 404 for unknown domain 'xx', got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# TEST-NS-11 : regime_state probabilities come from inference, not raw evidence
# ---------------------------------------------------------------------------

def test_ns_11_regime_state_uses_inference(tmp_path, monkeypatch):
    """
    After learning on synthetic evidence, current_regime_state probabilities
    must come from marginal inference (matching POST /v1/inference/query),
    not from raw soft-evidence weights.

    We verify:
    1. All regime_state variables have non-null boolean_state and probability
       once evidence exists.
    2. The regime_state probability for each variable matches the probability
       returned by POST /v1/inference/query for the same variable.
    """
    import os
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as c:
        # Ingest one day of evidence via the trigger endpoint.
        # This requires no external API keys — the NG domain uses mock-friendly
        # defaults when EIA/NOAA aren't reachable; we skip if it errors.
        trigger_resp = c.post("/v1/ingest/trigger?domain=ng")
        if trigger_resp.status_code != 200:
            pytest.skip(
                f"Ingestion trigger failed ({trigger_resp.status_code}); "
                "skipping inference comparison test"
            )

        snap = c.get("/v1/export/narrative-snapshot?domain=ng").json()
        regime = snap["current_regime_state"]

        # Every variable must have real (non-null) values after evidence
        for entry in regime:
            assert entry["boolean_state"] is not None, (
                f"Variable '{entry['name']}' has null boolean_state after ingestion"
            )
            assert entry["probability"] is not None, (
                f"Variable '{entry['name']}' has null probability after ingestion"
            )

        # Probabilities must match POST /v1/inference/query for each variable
        for entry in regime:
            var_name = entry["name"]
            inf_resp = c.post("/v1/inference/query", json={
                "domain": "ng",
                "target_variable": var_name,
            })
            assert inf_resp.status_code == 200, (
                f"inference/query failed for {var_name}: {inf_resp.text}"
            )
            inf_prob = inf_resp.json()["target_probability"]
            snap_prob = entry["probability"]
            assert abs(snap_prob - inf_prob) < 1e-6, (
                f"Variable '{var_name}': snapshot probability {snap_prob:.6f} "
                f"!= inference probability {inf_prob:.6f}"
            )


# ---------------------------------------------------------------------------
# TEST-NS-12 : regime_state is all-null when no evidence has been ingested
# ---------------------------------------------------------------------------

def test_ns_12_regime_state_null_without_evidence(tmp_path, monkeypatch):
    """
    On a fresh engine with no evidence ingested, every entry in
    current_regime_state must have boolean_state=null and probability=null.
    The variables must still be listed (correct count), just unobserved.

    Uses its own isolated client to guarantee a cold engine regardless of what
    other tests (e.g. NS-11's live ingest) may have written to app.state.
    """
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as c:
        resp = c.get("/v1/export/narrative-snapshot?domain=ng")
        assert resp.status_code == 200
        body = resp.json()

        # A fresh engine must have zero evidence records
        assert body["metadata"]["evidence_count"] == 0, (
            f"Expected 0 evidence records in cold-start engine, "
            f"got {body['metadata']['evidence_count']}"
        )

        for entry in body["current_regime_state"]:
            assert entry["boolean_state"] is None, (
                f"Expected null boolean_state for '{entry['name']}' with no evidence"
            )
            assert entry["probability"] is None, (
                f"Expected null probability for '{entry['name']}' with no evidence"
            )
