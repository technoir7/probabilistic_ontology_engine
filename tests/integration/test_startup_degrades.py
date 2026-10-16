"""
REFACTOR_SPEC 5.7 / A13: a missing API key disables that scheduler, not the app.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app


def test_missing_api_keys_disable_only_those_schedulers(monkeypatch):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "true")
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with TestClient(api_app.app) as client:
        assert client.get("/health").status_code == 200
        # Art needs no key, so its scheduler is the only one left running.
        names = [t["name"] for t in client.get("/runtime").json()["schedulers"]]
        assert names == ["art_prestige_regime_v1-evidence-scheduler"]
        assert client.get("/v1/population/status?domain=ng").status_code == 200
