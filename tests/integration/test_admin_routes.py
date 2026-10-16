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
from tests.fakes import ADMIN_TOKEN, patch_soft_evidence_for_all_domains

ADMIN_ROUTES = [
    ("POST", "/v1/ingest/backfill", {"domain": "ng", "days": 7}),
    ("POST", "/v1/ingest/art/manual", {"path": "missing.json"}),
    ("POST", "/v1/ingest/art/rebuild", {"months": 1}),
    ("GET", "/v1/ingest/art/rebuild", {}),
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
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as client:
        resp = client.post(
            "/v1/ingest/backfill", params={"domain": "ng", "days": 7},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
    assert resp.status_code == 200, resp.text


def test_dashboard_routes_need_no_token(monkeypatch):
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as client:
        assert client.post("/v1/ingest/trigger", params={"domain": "ng"}).status_code == 200
        assert client.post("/v1/inference/query", json={"domain": "ng", "target_variable": "PriceUp"}).status_code == 200


def test_cors_origins_come_from_the_environment():
    assert Settings.from_env({}).cors_origins == ("*",)
    assert Settings.from_env({"POE_CORS_ORIGINS": "https://a.vercel.app, http://localhost:3000"}).cors_origins == (
        "https://a.vercel.app", "http://localhost:3000",
    )
