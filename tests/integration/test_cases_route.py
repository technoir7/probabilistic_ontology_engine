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
    assert artists["leader"] == ["nyt"]                       # evals/README.md replay 18
    assert [s["to"] for s in artists["shifts"]][-1] == ["nyt"]
    assert artists["gain"] > 100 and artists["years"][0]["year"] == 2001
    assert artists["forecast_year"] == 2025
    row = artists["most_raised"][0]
    assert set(row) == {"case", "label", "own_past", "with_leader"} and len(row["own_past"]) == 3
    assert artists["mechanisms"][0]["features"] == ["nyt"] and "likeliest" not in artists
    assert sets["concepts"]["leader"] == ["contested"]
    assert sets["trends"]["leader"] == [] and sets["trends"]["gain"] < 0   # abductive_engine ART-PLAN §10: none holds


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
