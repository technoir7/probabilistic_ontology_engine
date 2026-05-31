"""
Tests for GET /v1/report/{domain} and POST /v1/report/{domain}/refresh,
plus the report cache module.

TEST-RC-01 : snapshot_hash is stable for identical snapshots
TEST-RC-02 : snapshot_hash differs when epistemic content changes
TEST-RC-03 : snapshot_hash excludes metadata.timestamp (cache-poisoning guard)
TEST-RC-04 : snapshot_hash uses stable key ordering (JSON sort_keys)
TEST-RC-05 : cache hit returns stored report without calling LLM
TEST-RC-06 : changed snapshot (new hash) gets a different cache path
TEST-RC-07 : report file is written under POE_DATA_DIR/reports/
TEST-RC-08 : stale_cache_path returns most-recently-modified file
TEST-RC-09 : GET /v1/report/{domain} returns found=False when no cache exists
TEST-RC-10 : GET /v1/report/{domain} returns found=True when cache exists (no LLM)
TEST-RC-11 : GET /v1/report/{domain} returns 404 for unknown domain
TEST-RC-12 : POST refresh with unchanged snapshot does not call LLM (cached=True)
TEST-RC-13 : POST refresh with changed snapshot calls Fireworks (regenerated=True)
TEST-RC-14 : POST refresh with no key but stale cache serves stale (stale=True)
TEST-RC-15 : POST refresh with no key and no stale cache returns 503
TEST-RC-16 : POST refresh Fireworks failure serves stale cache with stale=True
TEST-RC-17 : POST refresh Fireworks failure with no cache returns 502
TEST-RC-18 : GET /v1/report/{domain} does not build snapshot (not expensive)
TEST-RC-19 : snapshot_hash excludes interpretation_hints (time-derived narrative)
TEST-RC-20 : bumping PROMPT_VERSION produces a different cache path for the same hash
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.api.report import (
    cache_path,
    load_cache,
    reports_dir,
    save_cache,
    snapshot_hash,
    stale_cache_path,
)


# ─── Shared mock snapshot ────────────────────────────────────────────────────
# Reusable across endpoint tests — avoids needing a real engine (no lifespan).

_MOCK_SNAPSHOT = {
    "metadata": {
        "domain": "Natural Gas",
        "domain_module_id": "natural-gas-v1",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "evidence_count": 7,
        "current_generation": 0,
    },
    "current_regime_state": [],
    "dominant_hypothesis": None,
    "competing_candidates": {"candidates": [], "score_gap_to_dominant": None},
    "ontology_competition": {
        "structure_entropy": 1.0,
        "entropy_interpretation": "medium",
        "active_candidates": 5,
        "paradigm_shifts_total": 0,
        "recent_shifts": [],
    },
    "frontier": {"frontier_edge_count": 0, "frontier_edges": []},
    "interpretation_hints": ["test hint"],
}


def _mock_snap_model():
    from src.engine.api.app import NarrativeSnapshotOut
    return NarrativeSnapshotOut.model_validate(_MOCK_SNAPSHOT)


# ─── TEST-RC-01 to TEST-RC-04: hash stability & correctness ──────────────────

def test_snapshot_hash_stable():
    snap = {"domain": "ng", "metadata": {"evidence_count": 42}, "frontier": []}
    assert snapshot_hash(snap) == snapshot_hash(snap)


def test_snapshot_hash_differs_on_epistemic_change():
    snap_a = {"metadata": {"evidence_count": 42}}
    snap_b = {"metadata": {"evidence_count": 43}}
    assert snapshot_hash(snap_a) != snapshot_hash(snap_b)


def test_snapshot_hash_excludes_metadata_timestamp():
    """Changing only metadata.timestamp must NOT change the hash."""
    snap_a = {"metadata": {"timestamp": "2026-01-01T00:00:00+00:00", "evidence_count": 10}}
    snap_b = {"metadata": {"timestamp": "2026-06-15T12:34:56+00:00", "evidence_count": 10}}
    assert snapshot_hash(snap_a) == snapshot_hash(snap_b)


def test_snapshot_hash_key_order_independent():
    assert snapshot_hash({"b": 2, "a": 1}) == snapshot_hash({"a": 1, "b": 2})


# ─── TEST-RC-05 to TEST-RC-08: cache module ──────────────────────────────────

def test_cache_hit_returns_stored_report(tmp_path):
    snap = {"domain": "mr", "evidence_count": 100}
    h = snapshot_hash(snap)
    p = cache_path(tmp_path, "mr", "apriori", h)
    data = {
        "domain": "mr", "ontology_mode": "apriori",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_hash": h, "report": "Test report.",
    }
    save_cache(p, data)
    loaded = load_cache(p)
    assert loaded is not None
    assert loaded["report"] == "Test report."


def test_changed_snapshot_uses_different_path(tmp_path):
    h_a = snapshot_hash({"evidence_count": 10})
    h_b = snapshot_hash({"evidence_count": 11})
    assert cache_path(tmp_path, "mr", "apriori", h_a) != cache_path(tmp_path, "mr", "apriori", h_b)


def test_report_file_written_under_data_dir(tmp_path):
    h = snapshot_hash({"x": 1})
    p = cache_path(tmp_path, "sf", "apriori", h)
    save_cache(p, {"report": "hello"})
    assert p.parent == reports_dir(tmp_path)
    assert p.exists()
    assert json.loads(p.read_text())["report"] == "hello"


def test_stale_cache_path_most_recent(tmp_path):
    import time
    p1 = cache_path(tmp_path, "mr", "apriori", "a" * 20)
    save_cache(p1, {"report": "old"})
    time.sleep(0.02)
    p2 = cache_path(tmp_path, "mr", "apriori", "b" * 20)
    save_cache(p2, {"report": "newer"})
    assert stale_cache_path(tmp_path, "mr", "apriori") == p2


# ─── TEST-RC-09 to TEST-RC-11: GET endpoint ──────────────────────────────────

def test_get_report_found_false_when_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    client = TestClient(api_app.app)
    res = client.get("/v1/report/ng?ontology_mode=apriori")
    assert res.status_code == 200
    assert res.json()["found"] is False


def test_get_report_found_true_when_cache_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    # Plant a cache entry
    h = "x" * 20
    data = {
        "domain": "ng", "ontology_mode": "apriori",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_hash": h, "report": "Cached report.",
    }
    save_cache(cache_path(tmp_path, "ng", "apriori", h), data)
    client = TestClient(api_app.app)
    res = client.get("/v1/report/ng?ontology_mode=apriori")
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["report"] == "Cached report."
    assert body["cached"] is True


def test_get_report_unknown_domain_404():
    client = TestClient(api_app.app)
    res = client.get("/v1/report/NOTADOMAIN")
    assert res.status_code == 404


def test_get_report_does_not_call_llm(tmp_path, monkeypatch):
    """GET must never call the LLM, regardless of cache state."""
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    generate_called = {"n": 0}

    async def spy(*a, **kw):
        generate_called["n"] += 1
        return "should not be called"

    with patch("src.engine.api.report.generate_report", new=spy):
        client = TestClient(api_app.app)
        client.get("/v1/report/ng?ontology_mode=apriori")

    assert generate_called["n"] == 0, "GET must not call the LLM"


# ─── TEST-RC-12 to TEST-RC-17: POST /refresh endpoint ────────────────────────

def test_refresh_cache_hit_skips_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()
    call_count = {"n": 0}

    async def counting_generate(*a, **kw):
        call_count["n"] += 1
        return "generated"

    # Pre-populate exact cache for mock snapshot's hash
    h = snapshot_hash(mock_snap.model_dump())
    save_cache(cache_path(tmp_path, "ng", "apriori", h), {
        "domain": "ng", "ontology_mode": "apriori",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_hash": h, "report": "Existing report.",
    })

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)), \
         patch("src.engine.api.report.generate_report", new=counting_generate):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 200
    body = res.json()
    assert body["cached"] is True
    assert body["regenerated"] is False
    assert call_count["n"] == 0


def test_refresh_changed_snapshot_calls_fireworks(tmp_path, monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()
    mock_text = "Fresh Fireworks report."

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)), \
         patch("src.engine.api.report.generate_report", new=AsyncMock(return_value=mock_text)):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 200
    body = res.json()
    assert body["report"] == mock_text
    assert body["cached"] is False
    assert body["regenerated"] is True

    # File written under POE_DATA_DIR/reports/
    cache_files = list((tmp_path / "reports").glob("ng__apriori__*.json"))
    assert len(cache_files) == 1
    stored = json.loads(cache_files[0].read_text())
    assert stored["report"] == mock_text


def test_refresh_no_key_stale_cache_serves_stale(tmp_path, monkeypatch):
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()

    stale_data = {
        "domain": "ng", "ontology_mode": "apriori",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_hash": "stale_000000000000000000",
        "report": "Stale report.",
    }
    save_cache(cache_path(tmp_path, "ng", "apriori", "stale_000000000000000000"), stale_data)

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "Stale report."
    assert body["stale"] is True


def test_refresh_no_key_no_cache_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 503
    assert "FIREWORKS_API_KEY" in res.json()["detail"]


def test_refresh_fireworks_failure_serves_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()

    stale_data = {
        "domain": "ng", "ontology_mode": "apriori",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "snapshot_hash": "old_hash_000000000000000",
        "report": "Previous report.",
    }
    save_cache(cache_path(tmp_path, "ng", "apriori", "old_hash_000000000000000"), stale_data)

    async def failing_generate(*a, **kw):
        raise RuntimeError("Fireworks timeout")

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)), \
         patch("src.engine.api.report.generate_report", new=failing_generate):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "Previous report."
    assert body["stale"] is True


def test_refresh_fireworks_failure_no_cache_returns_502(tmp_path, monkeypatch):
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    mock_snap = _mock_snap_model()

    async def failing_generate(*a, **kw):
        raise RuntimeError("Fireworks timeout")

    with patch("src.engine.api.app.narrative_snapshot", new=AsyncMock(return_value=mock_snap)), \
         patch("src.engine.api.report.generate_report", new=failing_generate):
        client = TestClient(api_app.app)
        res = client.post("/v1/report/ng/refresh?ontology_mode=apriori")

    assert res.status_code == 502


# ─── TEST-RC-19: interpretation_hints excluded from hash ─────────────────────

def test_snapshot_hash_excludes_interpretation_hints():
    """Changing only interpretation_hints must NOT change the hash."""
    snap_a = {
        "metadata": {"evidence_count": 10},
        "interpretation_hints": ["last paradigm shift was 3 days ago"],
    }
    snap_b = {
        "metadata": {"evidence_count": 10},
        "interpretation_hints": ["last paradigm shift was 7 days ago", "evidence base is small"],
    }
    assert snapshot_hash(snap_a) == snapshot_hash(snap_b)


# ─── TEST-RC-20: PROMPT_VERSION drives cache invalidation ────────────────────

def test_prompt_version_changes_cache_path(tmp_path, monkeypatch):
    """Same snapshot hash + different PROMPT_VERSION → different cache path."""
    import src.engine.api.report as _report_mod
    h = snapshot_hash({"evidence_count": 42})
    monkeypatch.setattr(_report_mod, "PROMPT_VERSION", "1")
    path_v1 = cache_path(tmp_path, "ng", "apriori", h)
    monkeypatch.setattr(_report_mod, "PROMPT_VERSION", "2")
    path_v2 = cache_path(tmp_path, "ng", "apriori", h)
    assert path_v1 != path_v2
