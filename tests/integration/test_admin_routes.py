"""
REFACTOR_SPEC D7, A14: backfill and the art operator routes need the admin token.

They are operator tools (up to 1,825 days of upstream calls; a full rebuild
of the art domain from a file) and the dashboard never calls them. The
dashboard's own POSTs (inference query, ingest trigger, report refresh) stay
open: a token shipped to the browser would not be secret.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.runtime.settings import Settings
from tests.fakes import ADMIN_TOKEN, patch_fake_evidence_for_all_domains

ADMIN_ROUTES = [
    ("POST", "/v1/ingest/backfill", {"domain": "ng", "days": 7}),
    ("POST", "/v1/ingest/art/manual", {"path": "missing.json"}),
    ("POST", "/v1/ingest/art/rebuild", {"months": 1}),
    ("GET", "/v1/ingest/art/rebuild", {}),
    ("POST", "/v1/ingest/replace", {"domain": "mr"}),
    ("POST", "/v1/ingest/rebuild", {"domain": "cc", "days": 7}),
    ("GET", "/v1/ingest/rebuild", {"domain": "cc"}),
]


@pytest.mark.parametrize("method,path,params", ADMIN_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": ADMIN_TOKEN}])
def test_admin_routes_refuse_a_missing_or_wrong_token(method, path, params, headers):
    with TestClient(api_app.app) as client:
        resp = client.request(method, path, params=params, headers=headers)
    assert resp.status_code == 401, resp.text
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method,path,params", ADMIN_ROUTES)
def test_admin_routes_are_off_when_no_token_is_configured(monkeypatch, method, path, params):
    monkeypatch.delenv("POE_ADMIN_TOKEN")
    with TestClient(api_app.app) as client:
        resp = client.request(method, path, params=params, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 503
    assert "POE_ADMIN_TOKEN" in resp.json()["detail"]


def test_admin_routes_accept_the_token(monkeypatch):
    patch_fake_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as client:
        resp = client.post(
            "/v1/ingest/backfill", params={"domain": "ng", "days": 7},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
    assert resp.status_code == 200, resp.text


def test_dashboard_routes_need_no_token(monkeypatch):
    patch_fake_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as client:
        assert client.post("/v1/ingest/trigger", params={"domain": "ng"}).status_code == 200
        assert client.post("/v1/inference/query", json={"domain": "ng", "target_variable": "PriceUp"}).status_code == 200


def test_cors_origins_come_from_the_environment():
    assert Settings.from_env({}).cors_origins == ("*",)
    assert Settings.from_env({"POE_CORS_ORIGINS": "https://a.vercel.app, http://localhost:3000"}).cors_origins == (
        "https://a.vercel.app", "http://localhost:3000",
    )


def test_replace_relearns_a_domain_from_the_records_supplied():
    """An operator can replace a domain's evidence with records built
    elsewhere (a clean history, as first published) and relearn from scratch."""
    from datetime import datetime, timedelta, timezone
    from src.domains.macro_regime_v1.domain import get_variables
    from src.engine.schemas import EvidenceRecord, ObservedAssignment

    v = get_variables()
    records = [EvidenceRecord(
        timestamp=datetime(2024, 1, 7, tzinfo=timezone.utc) + timedelta(weeks=i),
        source_ref=f"replay@week-ending-{i}",
        observed_assignments=[ObservedAssignment(variable_id=x.variable_id, observed_value=x.support[(i + k) % 3])
                              for k, x in enumerate(v.values())],
    ).model_dump(mode="json") for i in range(3)]
    with TestClient(api_app.app) as client:
        headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        resp = client.post("/v1/ingest/replace", params={"domain": "mr"}, json=records, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["records_supplied"] == 3 and resp.json()["records_learned"] == 3
        again = client.post("/v1/ingest/replace", params={"domain": "mr"}, json=records[:1], headers=headers)
        assert again.json()["records_learned"] == 1  # forgot the first three


def test_replace_refuses_what_is_not_a_list_of_records():
    with TestClient(api_app.app) as client:
        resp = client.post("/v1/ingest/replace", params={"domain": "mr"}, json={"not": "records"},
                           headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 422


def test_soft_evidence_survives_the_trip_through_json():
    """JSON has only string keys, so a soft observation's {True: p, False: q}
    arrives as {"true": p, "false": q}; it must be read back as booleans, or
    learning mixes str and bool keys (found replacing the live macro history)."""
    import json
    import uuid
    from src.engine.schemas import ObservedAssignment
    a = ObservedAssignment(variable_id=uuid.uuid4(), observed_value=True, missingness="SOFT_OBSERVED",
                           probabilities={True: 0.7, False: 0.3})
    back = ObservedAssignment.model_validate(json.loads(json.dumps(a.model_dump(mode="json"))))
    assert back.probabilities == {True: 0.7, False: 0.3}


def test_replace_refuses_a_value_a_variable_cannot_take():
    """Checked before the domain is forgotten: macro's signals are levels (D25),
    so a yes/no for one is refused and nothing is replaced."""
    from datetime import datetime, timezone
    from src.domains.macro_regime_v1.domain import get_variables
    from src.engine.schemas import EvidenceRecord, ObservedAssignment

    x = get_variables()["InflationShock"]
    bad = [EvidenceRecord(timestamp=datetime(2024, 1, 7, tzinfo=timezone.utc),
                          observed_assignments=[ObservedAssignment(variable_id=x.variable_id, observed_value=True)],
                          ).model_dump(mode="json")]
    with TestClient(api_app.app) as client:
        resp = client.post("/v1/ingest/replace", params={"domain": "mr"}, json=bad,
                           headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 422
    assert "InflationShock" in resp.text and "True" in resp.text


def test_replace_learns_soft_evidence():
    from datetime import datetime, timedelta, timezone
    from src.domains.macro_regime_v1.domain import get_variables
    from src.engine.schemas import EvidenceRecord, ObservedAssignment

    v = get_variables()
    records = [EvidenceRecord(
        timestamp=datetime(2024, 1, 7, tzinfo=timezone.utc) + timedelta(weeks=i),
        observed_assignments=[ObservedAssignment(variable_id=x.variable_id, observed_value="high",
                                                 missingness="SOFT_OBSERVED",
                                                 probabilities={"low": 0.1, "mid": 0.3, "high": 0.6})
                              for x in v.values()],
    ).model_dump(mode="json") for i in range(3)]
    with TestClient(api_app.app) as client:
        resp = client.post("/v1/ingest/replace", params={"domain": "mr"}, json=records,
                           headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["records_learned"] == 3
