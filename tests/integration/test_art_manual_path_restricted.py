"""
REFACTOR_SPEC A14: the unauthenticated manual-ingest route must only read
files inside the configured manual-ingest directory.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import ADMIN


def test_manual_ingest_refuses_paths_outside_its_directory(monkeypatch, tmp_path):
    allowed = tmp_path / "manual"
    allowed.mkdir()
    monkeypatch.setenv("POE_ART_MANUAL_DIR", str(allowed))
    outside = tmp_path / "secrets.json"
    outside.write_text("{}", encoding="utf-8")

    with TestClient(api_app.app, headers=ADMIN) as client:
        for path in (str(outside), str(allowed / ".." / "secrets.json"), "/etc/hosts"):
            resp = client.post("/v1/ingest/art/manual", params={"path": path})
            assert resp.status_code == 400, (path, resp.text)
            assert "manual-ingest directory" in resp.json()["detail"]
