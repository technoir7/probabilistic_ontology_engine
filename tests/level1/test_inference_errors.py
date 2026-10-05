"""
REFACTOR_SPEC E2: inference fails loudly. An evidence value outside a
variable's support used to be encoded as state 0, and any failure came back
as an {"error": ...} dict or a uniform distribution, which looks like
"maximally uncertain" rather than "broken".
"""
from __future__ import annotations

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1, get_variables
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.errors import EngineError, UnknownValue
from src.engine.schemas import InferenceQuery, ObservedAssignment
from src.engine.services.bn_model import encode_value


def test_encode_value_rejects_values_outside_the_support():
    assert encode_value(False, [True, False]) == 1
    assert encode_value("True", [True, False]) == 0
    with pytest.raises(UnknownValue):
        encode_value("maybe", [True, False])


def test_query_with_an_impossible_condition_raises():
    engine = ProbabilisticOntologyEngine(db_path=":memory:")
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    query = InferenceQuery(
        domain_module_id="test-domain-v1",
        target_variables=["C"],
        conditioned_on=[ObservedAssignment(variable_id=get_variables()["A"].variable_id, observed_value="maybe")],
    )
    with pytest.raises(UnknownValue):
        engine.query(query)


def test_unknown_value_is_an_engine_error():
    assert issubclass(UnknownValue, EngineError)


def test_api_maps_engine_errors_to_http_status(monkeypatch):
    from fastapi.testclient import TestClient

    from src.engine.api import app as api_app
    from src.engine.model.errors import InferenceFailed
    from tests.fakes import running_engine

    with TestClient(api_app.app) as client:
        service = running_engine("ng").inference_service

        def broken(*_args, **_kwargs):
            raise InferenceFailed("pgmpy exploded")

        monkeypatch.setattr(service, "query_candidate", broken)
        resp = client.post("/v1/inference/query", json={"domain": "ng", "target_variable": "PriceUp"})
        assert resp.status_code == 500
        assert "InferenceFailed: pgmpy exploded" in resp.json()["detail"]
