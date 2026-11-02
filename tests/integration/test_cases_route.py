"""GET /v1/cases (REFACTOR_SPEC D29): a domain's case sets, judged by the
case engine; only art has any."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.engine.api import app as api_app


def test_art_reports_its_case_sets_with_leader_shifts_years_and_forecasts():
    with TestClient(api_app.app) as client:
        resp = client.get("/v1/cases", params={"domain": "art"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["domain"] == "art"
    sets = {s["key"]: s for s in body["case_sets"]}
    assert set(sets) == {"artists", "concepts", "trends"}
    artists = sets["artists"]
    assert artists["pool"] == ["nyt", "guardian", "approval", "contested"]
    # abductive_engine ART-PLAN §9 amended: mechanisms combine additively.
    assert artists["leader"] == ["nyt", "approval"]
    assert [s["to"] for s in artists["shifts"]][-1] == ["nyt", "approval"]
    assert artists["gain"] > 100 and artists["years"][0]["year"] == 2001
    assert artists["forecast_year"] == 2025
    row = artists["most_raised"][0]
    assert set(row) == {"case", "label", "own_past", "with_leader"} and len(row["own_past"]) == 3
    assert "nyt" in artists["mechanisms"][0]["features"] and "likeliest" not in artists
    assert sets["concepts"]["leader"] == ["contested", "both_papers", "modality"]
    assert sets["trends"]["gain"] < 3          # abductive_engine ART-PLAN §10: nothing holds over the years


def test_a_domain_without_cases_has_none_and_an_unknown_domain_is_refused():
    with TestClient(api_app.app) as client:
        assert client.get("/v1/cases", params={"domain": "mr"}).json() == {"domain": "mr", "case_sets": []}
        assert client.get("/v1/cases", params={"domain": "nope"}).status_code == 404


def test_art_reports_this_years_trends_and_other_domains_none():
    """REFACTOR_SPEC D30."""
    with TestClient(api_app.app) as client:
        body = client.get("/v1/trends", params={"domain": "art"}).json()
        assert client.get("/v1/trends", params={"domain": "mr"}).json() == {"domain": "mr", "trends": None}
        assert client.get("/v1/trends", params={"domain": "nope"}).status_code == 404
    t = body["trends"]
    assert t["year"] == 2026 and set(t["lists"]) == {"new", "growing", "fading", "argued"}
    first = t["trends"][t["lists"]["new"][0]]
    assert len(first["writers"]) == len(t["years"]) == len(t["all_writers"]) and first["name"]


def test_case_reports_are_computed_once_however_many_ask_at_the_same_time(monkeypatch):
    """The first computation takes over a minute on the server; a request arriving while the
    start-up warm-up runs waits for it rather than starting a second."""
    import threading
    import time
    import uuid
    from types import SimpleNamespace
    from src.engine.runtime import cases as runtime_cases
    key = f"slow-{uuid.uuid4().hex}"     # its own domain, so art's cached reports are left alone
    computed = []

    def slow(case_set):
        computed.append(case_set)
        time.sleep(0.2)
        return case_set
    monkeypatch.setattr(runtime_cases, "case_report", slow)
    monkeypatch.setitem(runtime_cases.BY_KEY, key, SimpleNamespace(case_sets=lambda: ["a", "b"]))
    callers = [threading.Thread(target=runtime_cases.compute_case_reports, args=(key,)) for _ in range(3)]
    for c in callers:
        c.start()
    for c in callers:
        c.join()
    assert computed == ["a", "b"]


def test_the_live_server_warms_the_case_reports_at_start_up(monkeypatch):
    warmed = []
    monkeypatch.setattr(api_app, "warm_case_reports", lambda: warmed.append(1))
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "true")
    for key in ("FRED_API_KEY", "EIA_API_KEY", "GUARDIAN_API_KEY", "NYT_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(api_app.app):
        api_app.app.state.case_warmup.join(timeout=5)
    assert warmed == [1]
