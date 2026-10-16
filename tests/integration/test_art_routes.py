"""
The art operator routes: report ingest and rebuild (both need the admin token).

Reports are learned once each, by evidence id; a rebuild forgets the domain
and relearns fetched months and reports together, oldest first. A rebuild
outlasts Railway's 5-minute request limit (GDELT allows one request per 5 s
and throttles beyond that), so it runs in the background and is polled.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import (
    ADMIN,
    domain_variables,
    freeze_clock,
    patch_evidence_fetch,
    patch_soft_evidence_for_all_domains,
    running_engine,
    soft_record,
)

DOMAIN_ID = "art_prestige_regime_v1"


def _report(tmp_path, name="report.json", published="2026-05-01", url="https://example.test/a"):
    (tmp_path / name).write_text(json.dumps({
        "title": "Art market signal", "url": url, "published_at": published,
        "assignments": {"AIImageSaturation": {"value": True, "confidence": 0.8},
                        "BlueChipConcentration": {"value": False, "confidence": 0.7}},
    }), encoding="utf-8")


def test_reports_are_learned_once(tmp_path):
    _report(tmp_path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with TestClient(api_app.app, headers=ADMIN) as client:
        first = client.post("/v1/ingest/art/manual").json()
        second = client.post("/v1/ingest/art/manual").json()
        engine = running_engine("art")
        stored = engine.evidence_store.count(DOMAIN_ID)

    assert first["records_found"] == 1 and first["records_learned"] == 1
    assert first["files_scanned"] == 2 and len(first["failed"]) == 1 and "broken.json" in first["failed"][0]
    assert second["records_learned"] == 0 and second["records_skipped_duplicates"] == 1
    assert stored == 1


def _finished_rebuild(client, timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        body = client.get("/v1/ingest/art/rebuild").json()
        if body["state"] != "running":
            return body
        assert time.monotonic() < deadline, body
        time.sleep(0.02)


def _gated_fetch(monkeypatch) -> threading.Event:
    """Art fetches block until the returned event is set."""
    gate = threading.Event()

    async def fetch(domain_key, target_date):
        await asyncio.to_thread(gate.wait, 15)
        return soft_record(domain_variables(domain_key), target_date, seed=domain_key)

    patch_evidence_fetch(monkeypatch, fetch)
    return gate


def test_no_rebuild_yet_is_idle():
    with TestClient(api_app.app, headers=ADMIN) as client:
        body = client.get("/v1/ingest/art/rebuild").json()
    assert body["state"] == "idle" and body["records_learned"] is None


def test_rebuild_relearns_months_and_reports_in_date_order(monkeypatch, tmp_path):
    freeze_clock(monkeypatch, datetime(2026, 6, 15, tzinfo=timezone.utc))
    calls = patch_soft_evidence_for_all_domains(monkeypatch)
    _report(tmp_path, published="2026-04-10")
    with TestClient(api_app.app, headers=ADMIN) as client:
        client.post("/v1/ingest/art/manual")  # learned before the rebuild; must not survive twice
        started = client.post("/v1/ingest/art/rebuild", params={"months": 3})
        body = _finished_rebuild(client)
        stored = running_engine("art").evidence_store.load_all(DOMAIN_ID)

    assert started.status_code == 202 and started.json()["state"] == "running"
    art_months = [d for key, d in calls if key == "art"]
    assert art_months[-3:] == [date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31)]
    assert body["state"] == "done" and body["months_requested"] == 3
    assert body["records_learned"] == 4 and body["reports_found"] == 1
    assert body["finished_at"] is not None
    assert [r.timestamp.date() for r in stored] == [
        date(2026, 3, 31), date(2026, 4, 10), date(2026, 4, 30), date(2026, 5, 31),
    ]


def test_a_second_rebuild_is_refused_while_one_runs(monkeypatch, tmp_path):
    gate = _gated_fetch(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        first = client.post("/v1/ingest/art/rebuild", params={"months": 1})
        second = client.post("/v1/ingest/art/rebuild", params={"months": 1})
        running = client.get("/v1/ingest/art/rebuild").json()
        gate.set()
        body = _finished_rebuild(client)

    assert first.status_code == 202
    assert second.status_code == 409
    assert running["state"] == "running" and running["finished_at"] is None
    assert body["state"] == "done"


def test_a_rebuild_that_fails_says_so(monkeypatch, tmp_path):
    patch_soft_evidence_for_all_domains(monkeypatch)
    with TestClient(api_app.app, headers=ADMIN) as client:
        def broken_reset(domain_id):
            raise RuntimeError("disk full")

        monkeypatch.setattr(running_engine("art"), "reset_domain", broken_reset)
        client.post("/v1/ingest/art/rebuild", params={"months": 1})
        body = _finished_rebuild(client)
        again = client.post("/v1/ingest/art/rebuild", params={"months": 1})  # a failed run does not block the next

    assert body["state"] == "failed" and "disk full" in body["error"]
    assert again.status_code == 202
