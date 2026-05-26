"""
Structure-learning diagnostics tests (SD-01 … SD-06).

All tests use TestClient + monkeypatching to avoid real API calls, following
the same pattern as test_api_ingest_trigger.py.

SD-01  GET /v1/debug/structure returns 200 with the expected top-level shape.
SD-02  Every candidate entry has bic_score_strict and bic_score_explore.
SD-03  bic_score_explore >= bic_score_strict for any candidate with evidence.
SD-04  last_mutation_cycle carries total_attempts and introduced counts after
       at least one learning cycle.
SD-05  POE_STRUCTURE_MODE=explore changes env_mode / env_bic_multiplier.
SD-06  bic_score_explore and bic_score_strict agree when evidence_count == 0
       (both -inf, no division by zero, no NaN).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.domains.natural_gas_v1.domain import get_variables
from src.engine.api import app as api_app
from src.engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)


# ── Shared fake evidence factory ──────────────────────────────────────────────

def _make_ng_record(target_date: date) -> EvidenceRecord:
    """Hard-observed all-True NatGas record (no network required)."""
    variables = get_variables()
    return EvidenceRecord(
        timestamp=datetime(
            target_date.year, target_date.month, target_date.day,
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
        source_ref=f"sd-test@{target_date}",
        confidence=1.0,
    )


def _patch_fetch(monkeypatch):
    """Replace _fetch_evidence_record with a no-network stub."""
    async def fake_fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        return _make_ng_record(target_date)

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch)


# ── SD-01: endpoint returns 200 with correct top-level shape ──────────────────

def test_sd01_structure_endpoint_returns_200_with_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POE_STRUCTURE_MODE", raising=False)

    with TestClient(api_app.app) as client:
        response = client.get("/v1/debug/structure?domain=ng")

    assert response.status_code == 200, response.text
    body = response.json()

    # Top-level keys
    assert "domain" in body
    assert "domain_module_id" in body
    assert "env_mode" in body
    assert "env_bic_multiplier" in body
    assert "total_evidence_records" in body
    assert "candidates" in body
    assert "last_mutation_cycle" in body

    # Sensible defaults (no evidence ingested yet)
    assert body["env_mode"] == "strict"
    assert body["env_bic_multiplier"] == 1.0
    assert isinstance(body["candidates"], list)
    assert len(body["candidates"]) > 0          # initial candidates are always present


# ── SD-02: every candidate has bic_score_strict and bic_score_explore ─────────

def test_sd02_candidates_have_bic_score_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POE_STRUCTURE_MODE", raising=False)

    with TestClient(api_app.app) as client:
        body = client.get("/v1/debug/structure?domain=ng").json()

    for cd in body["candidates"]:
        assert "bic_score_strict" in cd, f"Missing bic_score_strict in {cd}"
        assert "bic_score_explore" in cd, f"Missing bic_score_explore in {cd}"
        # Also check the decomposition fields exist
        assert "avg_ll" in cd
        assert "bic_penalty_raw" in cd
        assert "active_edge_count" in cd
        assert "total_edge_count" in cd
        assert "evidence_count" in cd
        assert "is_dominant" in cd


# ── SD-03: bic_score_explore >= bic_score_strict when evidence_count > 0 ─────

def test_sd03_explore_score_geq_strict_after_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POE_STRUCTURE_MODE", raising=False)
    _patch_fetch(monkeypatch)

    with TestClient(api_app.app) as client:
        # Ingest 3 records so some candidates accumulate evidence
        for _ in range(3):
            client.post("/v1/ingest/trigger?domain=ng")

        body = client.get("/v1/debug/structure?domain=ng").json()

    for cd in body["candidates"]:
        if cd["evidence_count"] > 0:
            s = cd["bic_score_strict"]
            e = cd["bic_score_explore"]
            assert math.isfinite(s) and math.isfinite(e), (
                f"Candidate {cd['candidate_id']} has non-finite scores: "
                f"strict={s}, explore={e}"
            )
            assert e >= s - 1e-9, (
                f"Candidate {cd['candidate_id']}: explore score {e:.6f} < "
                f"strict score {s:.6f}  (explore penalty should be smaller)"
            )


# ── SD-04: last_mutation_cycle has valid counts after a learning cycle ─────────

def test_sd04_mutation_cycle_diagnostics_populated_after_learning(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POE_STRUCTURE_MODE", raising=False)
    _patch_fetch(monkeypatch)

    with TestClient(api_app.app) as client:
        # At least one ingest triggers one learning cycle → introduce_variants runs
        client.post("/v1/ingest/trigger?domain=ng")
        body = client.get("/v1/debug/structure?domain=ng").json()

    mc = body["last_mutation_cycle"]
    assert "total_attempts" in mc
    assert "dag_violations" in mc
    assert "duplicate_rejections" in mc
    assert "introduced" in mc

    # After one learning cycle the manager has run introduce_variants at least once;
    # total_attempts must be >= introduced (we can't introduce more than we attempt)
    assert mc["total_attempts"] >= mc["introduced"]
    assert mc["dag_violations"] >= 0
    assert mc["duplicate_rejections"] >= 0


# ── SD-05: POE_STRUCTURE_MODE=explore changes env_mode and env_bic_multiplier ─

def test_sd05_explore_mode_env_var_reflected_in_response(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POE_STRUCTURE_MODE", "explore")

    with TestClient(api_app.app) as client:
        body = client.get("/v1/debug/structure?domain=ng").json()

    assert body["env_mode"] == "explore"
    assert body["env_bic_multiplier"] == pytest.approx(0.25, rel=1e-6)


# ── SD-06: zero-evidence candidates have -inf BIC scores, not NaN / errors ────

def test_sd06_zero_evidence_candidates_have_neg_inf_bic(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POE_STRUCTURE_MODE", raising=False)

    with TestClient(api_app.app) as client:
        body = client.get("/v1/debug/structure?domain=ng").json()

    # The diagnostic uses -1e300 as a JSON-safe "no data" sentinel
    # (Python float("-inf") would serialise to JSON null, losing information).
    _NO_DATA = -1e300

    for cd in body["candidates"]:
        if cd["evidence_count"] == 0:
            strict = cd["bic_score_strict"]
            explore = cd["bic_score_explore"]

            assert strict is not None, "bic_score_strict must not be null"
            assert explore is not None, "bic_score_explore must not be null"
            assert not math.isnan(strict), "strict score must not be NaN"
            assert not math.isnan(explore), "explore score must not be NaN"

            # Both must equal the no-data sentinel (both represent "undefined")
            assert strict == pytest.approx(_NO_DATA, rel=1e-6), (
                f"Expected no-data sentinel {_NO_DATA} for zero-evidence candidate, got {strict}"
            )
            assert explore == pytest.approx(_NO_DATA, rel=1e-6), (
                f"Expected no-data sentinel {_NO_DATA} for zero-evidence candidate, got {explore}"
            )
