"""
Tests for GET /v1/population/lineage/{candidate_id} cross-domain robustness.

TEST-LIN-01 : lineage returns 200 for an NG candidate with ?domain=ng (happy path)
TEST-LIN-02 : lineage returns 200 for an MR candidate with ?domain=mr (happy path)
TEST-LIN-03 : lineage finds an MR candidate even when ?domain=ng is specified (cross-domain fallback)
TEST-LIN-04 : lineage finds an NG candidate even when ?domain=mr is specified (cross-domain fallback)
TEST-LIN-05 : lineage returns 404 for a completely unknown UUID across all domains
TEST-LIN-06 : lineage response contains required fields (domain, candidate_id, events)
TEST-LIN-07 : candidates endpoint returns valid UUIDs that lineage can resolve with correct domain
TEST-LIN-08 : candidates endpoint returns valid UUIDs that lineage resolves even with wrong domain
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    with TestClient(api_app.app) as c:
        yield c


def _get_first_candidate_id(client: TestClient, domain: str) -> str:
    """Return the UUID of the first active candidate for a domain."""
    resp = client.get(f"/v1/population/candidates?domain={domain}")
    assert resp.status_code == 200, f"candidates endpoint failed for {domain}: {resp.text}"
    candidates = resp.json()["candidates"]
    assert candidates, f"No candidates returned for domain {domain}"
    return candidates[0]["id"]


# ── TEST-LIN-01 ────────────────────────────────────────────────────────────────

def test_lin_01_lineage_ng_correct_domain(client):
    """lineage returns 200 for an NG candidate with ?domain=ng."""
    ng_uuid = _get_first_candidate_id(client, "ng")
    resp = client.get(f"/v1/population/lineage/{ng_uuid}?domain=ng")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_id"] == ng_uuid
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1


# ── TEST-LIN-02 ────────────────────────────────────────────────────────────────

def test_lin_02_lineage_mr_correct_domain(client):
    """lineage returns 200 for an MR candidate with ?domain=mr."""
    mr_uuid = _get_first_candidate_id(client, "mr")
    resp = client.get(f"/v1/population/lineage/{mr_uuid}?domain=mr")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_id"] == mr_uuid
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1


# ── TEST-LIN-03 ────────────────────────────────────────────────────────────────

def test_lin_03_lineage_mr_uuid_with_ng_domain_falls_back(client):
    """
    Cross-domain fallback: an MR UUID passed with ?domain=ng should still resolve.
    The endpoint searches all loaded engines when not found in the specified one.
    """
    mr_uuid = _get_first_candidate_id(client, "mr")
    # Pass the MR UUID but specify the wrong domain (ng — the default)
    resp = client.get(f"/v1/population/lineage/{mr_uuid}?domain=ng")
    assert resp.status_code == 200, (
        f"Expected 200 via cross-domain fallback for MR UUID with domain=ng, got "
        f"{resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["candidate_id"] == mr_uuid


# ── TEST-LIN-04 ────────────────────────────────────────────────────────────────

def test_lin_04_lineage_ng_uuid_with_mr_domain_falls_back(client):
    """
    Cross-domain fallback: an NG UUID passed with ?domain=mr should still resolve.
    """
    ng_uuid = _get_first_candidate_id(client, "ng")
    resp = client.get(f"/v1/population/lineage/{ng_uuid}?domain=mr")
    assert resp.status_code == 200, (
        f"Expected 200 via cross-domain fallback for NG UUID with domain=mr, got "
        f"{resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["candidate_id"] == ng_uuid


# ── TEST-LIN-05 ────────────────────────────────────────────────────────────────

def test_lin_05_lineage_unknown_uuid_returns_404(client):
    """lineage returns 404 for a UUID that doesn't exist in any domain."""
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/v1/population/lineage/{fake_uuid}?domain=ng")
    assert resp.status_code == 404


# ── TEST-LIN-06 ────────────────────────────────────────────────────────────────

def test_lin_06_lineage_response_schema(client):
    """lineage response contains the required top-level fields."""
    ng_uuid = _get_first_candidate_id(client, "ng")
    resp = client.get(f"/v1/population/lineage/{ng_uuid}?domain=ng")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "domain" in body
    assert "candidate_id" in body
    assert "events" in body
    assert isinstance(body["events"], list)
    # Each event must have generation, event_type, description
    for event in body["events"]:
        assert "generation" in event
        assert "event_type" in event
        assert "description" in event
        assert event["event_type"] in ("shift", "introduce", "milestone", "current")


# ── TEST-LIN-07 ────────────────────────────────────────────────────────────────

def test_lin_07_candidates_uuids_resolvable_via_lineage_correct_domain(client):
    """
    Every UUID from /v1/population/candidates?domain=mr is resolvable via
    /v1/population/lineage/<uuid>?domain=mr.
    """
    resp = client.get("/v1/population/candidates?domain=mr")
    assert resp.status_code == 200, resp.text
    candidates = resp.json()["candidates"]
    assert candidates, "MR population must have at least one candidate"

    for cand in candidates:
        uuid = cand["id"]
        lineage_resp = client.get(f"/v1/population/lineage/{uuid}?domain=mr")
        assert lineage_resp.status_code == 200, (
            f"lineage returned {lineage_resp.status_code} for MR UUID {uuid}: "
            f"{lineage_resp.text}"
        )
        assert lineage_resp.json()["candidate_id"] == uuid


# ── TEST-LIN-08 ────────────────────────────────────────────────────────────────

def test_lin_08_mr_uuids_resolvable_via_lineage_with_default_domain(client):
    """
    Every UUID from /v1/population/candidates?domain=mr is resolvable via
    /v1/population/lineage/<uuid> (no domain param — defaults to 'ng').
    This is the exact failure mode from the bug report: the cross-domain
    fallback must find MR candidates even when domain defaults to ng.
    """
    resp = client.get("/v1/population/candidates?domain=mr")
    assert resp.status_code == 200, resp.text
    candidates = resp.json()["candidates"]
    assert candidates, "MR population must have at least one candidate"

    for cand in candidates:
        uuid = cand["id"]
        # Note: no ?domain=mr — this is the buggy call pattern
        lineage_resp = client.get(f"/v1/population/lineage/{uuid}")
        assert lineage_resp.status_code == 200, (
            f"Cross-domain fallback failed for MR UUID {uuid} with default domain: "
            f"{lineage_resp.text}"
        )
        assert lineage_resp.json()["candidate_id"] == uuid
