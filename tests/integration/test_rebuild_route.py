"""Rebuilding any domain from its own sources (admin): forget it and refetch
a window of history with the current code, in the background. For histories
written before unavailable inputs were recorded as MISSING (D10)."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.api.context import utcnow
from src.engine.runtime.registry import BY_KEY
from tests.fakes import ADMIN_TOKEN, patch_soft_evidence_for_all_domains, running_engine

H = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _finished(client, domain, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while True:
        body = client.get("/v1/ingest/rebuild", params={"domain": domain}, headers=H).json()
        if body["state"] != "running":
            return body
        assert time.monotonic() < deadline, body
        time.sleep(0.02)


def test_rebuild_refetches_the_window_and_replaces_the_history(monkeypatch):
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app) as client:
        client.post("/v1/ingest/backfill", params={"domain": "cc", "days": 21}, headers=H)
        before = running_engine("cc").evidence_store.count("credit-cycle-v1")
        started = client.post("/v1/ingest/rebuild", params={"domain": "cc", "days": 42}, headers=H)
        assert started.status_code == 202, started.text
        body = _finished(client, "cc")
        weeks = len(BY_KEY["cc"].cadence.window_targets(42, utcnow().date()))
        assert body["state"] == "done" and body["records_learned"] == weeks
        assert running_engine("cc").evidence_store.count("credit-cycle-v1") == weeks
    assert 0 < before < weeks


def test_no_rebuild_yet_is_idle():
    with TestClient(api_app.app) as client:
        assert client.get("/v1/ingest/rebuild", params={"domain": "gp"}, headers=H).json()["state"] == "idle"


def test_art_has_its_own_rebuild():
    with TestClient(api_app.app) as client:
        assert client.post("/v1/ingest/rebuild", params={"domain": "art", "days": 30}, headers=H).status_code == 400
