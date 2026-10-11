"""
REFACTOR_SPEC 5.7 / A13: one missing piece disables that piece, not the app.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.runtime import art


def test_missing_api_keys_disable_only_those_schedulers(monkeypatch):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "true")
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with TestClient(api_app.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/runtime").json()["schedulers"] == []
        assert client.get("/v1/population/status?domain=ng").status_code == 200


def test_missing_art_package_disables_only_the_art_domain(monkeypatch):
    def missing(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'art_prestige_regime_v1'", name="art_prestige_regime_v1")

    monkeypatch.setattr(art, "import_art_module", missing)
    with TestClient(api_app.app) as client:
        assert client.get("/v1/population/status?domain=mr").status_code == 200
        resp = client.get("/v1/population/status?domain=art")
        assert resp.status_code == 503
