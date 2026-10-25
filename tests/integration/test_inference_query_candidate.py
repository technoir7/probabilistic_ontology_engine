"""
REFACTOR_SPEC B3: POST /v1/inference/query with a candidate_id must answer
with that candidate's posterior, not the dominant candidate's.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.schemas import InferenceQuery, MissingnessType
from tests.fakes import ADMIN, domain_variables, patch_evidence_fetch, running_engine, fake_record


def price_follows_storage(monkeypatch) -> None:
    """Natural-gas evidence in which PriceUp copies StorageDraw, so the engine,
    which begins with no hypotheses (D24), has a connection to form and the
    population holds rivals that answer differently about PriceUp."""
    async def fetch(domain_key, target_date):
        record = fake_record(domain_variables(domain_key), target_date, seed=domain_key)
        by_name = {v.variable_id: v.name for v in domain_variables(domain_key)}
        storage = next(a for a in record.observed_assignments if by_name[a.variable_id] == "StorageDraw")
        seen = {"variable_id": None, "observed_value": storage.observed_value,
                "missingness": MissingnessType.OBSERVED, "probabilities": None}
        return record.model_copy(update={"observed_assignments": [
            a.model_copy(update={**seen, "variable_id": a.variable_id})
            if by_name[a.variable_id] in ("StorageDraw", "PriceUp") else a
            for a in record.observed_assignments]})
    patch_evidence_fetch(monkeypatch, fetch)


def test_inference_query_answers_for_the_requested_candidate(monkeypatch):
    price_follows_storage(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        assert client.post("/v1/ingest/backfill?domain=ng&days=21").status_code == 200
        engine = running_engine("ng")
        pop = engine.get_population("natural-gas-v1")
        dominant = pop.dominant()

        def posterior(candidate) -> dict[str, float]:
            query = InferenceQuery(domain_module_id="natural-gas-v1", target_variables=["PriceUp"])
            return engine.inference_service.query_candidate(candidate, query)["posteriors"]["PriceUp"]

        def differ(a: dict, b: dict) -> bool:
            return any(abs(a[k] - b[k]) > 1e-6 for k in a)

        others = [c for c in pop.active_candidates() if c.candidate_id != dominant.candidate_id]
        other = next(c for c in others if differ(posterior(c), posterior(dominant)))

        body = client.post("/v1/inference/query", json={
            "domain": "ng", "target_variable": "PriceUp", "candidate_id": str(other.candidate_id),
        }).json()

    assert body["candidate_id"] == str(other.candidate_id)
    expected = posterior(other)
    assert body["target_distribution"].keys() == expected.keys()
    assert all(abs(body["target_distribution"][k] - expected[k]) < 1e-12 for k in expected)


def test_weighted_avg_answers_for_the_population(monkeypatch):
    """REFACTOR_SPEC D6: aggregation="weighted_avg" (the dashboard sends it) averages
    the posterior over the population by structure weight; the graph stays the candidate's."""
    price_follows_storage(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        assert client.post("/v1/ingest/backfill?domain=ng&days=21").status_code == 200
        engine = running_engine("ng")
        pop = engine.get_population("natural-gas-v1")
        query = InferenceQuery(domain_module_id="natural-gas-v1", target_variables=["PriceUp"])
        expected: dict[str, float] = {}
        for c, w in zip(pop.active_candidates(), pop.score_weights()):
            for value, p in engine.inference_service.query_candidate(c, query)["posteriors"]["PriceUp"].items():
                expected[value] = expected.get(value, 0.0) + w * p
        other = next(c for c in pop.active_candidates() if c.candidate_id != pop.dominant().candidate_id)

        body = client.post("/v1/inference/query", json={
            "domain": "ng", "target_variable": "PriceUp",
            "candidate_id": str(other.candidate_id), "aggregation": "weighted_avg",
        }).json()

    assert body["candidate_id"] == str(other.candidate_id)
    assert all(abs(body["target_distribution"][k] - expected[k]) < 1e-9 for k in expected)
    assert {e["source"] + ">" + e["target"] for e in body["edges"]} == {
        other.get_variable_by_id(e.parent_variable_id).name + ">" + other.get_variable_by_id(e.child_variable_id).name
        for e in other.get_active_edges()
    }
