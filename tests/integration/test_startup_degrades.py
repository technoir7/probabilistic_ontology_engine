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
    # Art needs only the papers' keys (D28); tests refuse the network, so these are never sent.
    monkeypatch.setenv("GUARDIAN_API_KEY", "test-key")
    monkeypatch.setenv("NYT_API_KEY", "test-key")
    with TestClient(api_app.app) as client:
        assert client.get("/health").status_code == 200
        # Art has its keys, so its scheduler is the only one left running.
        names = [t["name"] for t in client.get("/runtime").json()["schedulers"]]
        assert names == ["art_prestige_regime_v1-evidence-scheduler"]
        assert client.get("/v1/population/status?domain=ng").status_code == 200
