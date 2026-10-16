"""
REFACTOR_SPEC B3: POST /v1/inference/query with a candidate_id must answer
with that candidate's posterior, not the dominant candidate's.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.schemas import InferenceQuery
from tests.fakes import ADMIN, patch_soft_evidence_for_all_domains, running_engine


def test_inference_query_answers_for_the_requested_candidate(monkeypatch):
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        assert client.post("/v1/ingest/backfill?domain=ng&days=21").status_code == 200
        engine = running_engine("ng")
        pop = engine.get_population("natural-gas-v1")
        dominant = pop.dominant()

        def p_true(candidate) -> float:
            query = InferenceQuery(domain_module_id="natural-gas-v1", target_variables=["PriceUp"])
            return engine.inference_service.query_candidate(candidate, query)["posteriors"]["PriceUp"]["True"]

        others = [c for c in pop.active_candidates() if c.candidate_id != dominant.candidate_id]
        other = next(c for c in others if abs(p_true(c) - p_true(dominant)) > 1e-6)

        body = client.post("/v1/inference/query", json={
            "domain": "ng", "target_variable": "PriceUp", "candidate_id": str(other.candidate_id),
        }).json()

    assert body["candidate_id"] == str(other.candidate_id)
    assert abs(body["target_probability"] - p_true(other)) < 1e-12


def test_weighted_avg_answers_for_the_population(monkeypatch):
    """REFACTOR_SPEC D6: aggregation="weighted_avg" (the dashboard sends it) averages
    P(True) over the population by structure weight; the graph stays the candidate's."""
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        assert client.post("/v1/ingest/backfill?domain=ng&days=21").status_code == 200
        engine = running_engine("ng")
        pop = engine.get_population("natural-gas-v1")
        query = InferenceQuery(domain_module_id="natural-gas-v1", target_variables=["PriceUp"])
        expected = sum(
            w * engine.inference_service.query_candidate(c, query)["posteriors"]["PriceUp"]["True"]
            for c, w in zip(pop.active_candidates(), pop.score_weights())
        )
        other = next(c for c in pop.active_candidates() if c.candidate_id != pop.dominant().candidate_id)

        body = client.post("/v1/inference/query", json={
            "domain": "ng", "target_variable": "PriceUp",
            "candidate_id": str(other.candidate_id), "aggregation": "weighted_avg",
        }).json()

    assert body["candidate_id"] == str(other.candidate_id)
    assert abs(body["target_probability"] - expected) < 1e-9
    assert {e["source"] + ">" + e["target"] for e in body["edges"]} == {
        other.get_variable_by_id(e.parent_variable_id).name + ">" + other.get_variable_by_id(e.child_variable_id).name
        for e in other.get_active_edges()
    }
