"""A written report for each of art's trend lists (REFACTOR_SPEC D30):
read from cache, refreshed only when the list changes, written from its
own prompt."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.api.narrative import trend_list_snapshot
from src.engine.api.report import TREND_PROMPT_PATH


def test_a_lists_snapshot_carries_its_rule_and_up_to_twelve_trends_with_claims():
    snap = trend_list_snapshot("art", "fading")
    assert snap.list == "fading" and "half" in snap.rule
    assert 1 <= len(snap.trends) <= 12
    assert all(t.what_critics_said or t.writers_this_year == 0 for t in snap.trends)


def test_a_list_report_is_found_only_once_written(tmp_path, monkeypatch):
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    client = TestClient(api_app.app)
    assert client.get("/v1/trends/art/growing/report").json() == {"found": False, "domain": "art"}
    assert client.get("/v1/trends/art/sideways/report").status_code == 404
    assert client.get("/v1/trends/mr/growing/report").status_code == 404


def test_refresh_writes_a_list_report_from_its_own_prompt_and_then_serves_it(tmp_path, monkeypatch):
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    generate = AsyncMock(return_value="## In short\nTheft is up.")
    with patch("src.engine.api.report.generate_report", new=generate):
        client = TestClient(api_app.app)
        first = client.post("/v1/trends/art/growing/report/refresh").json()
        second = client.post("/v1/trends/art/growing/report/refresh").json()
        read = client.get("/v1/trends/art/growing/report").json()
    assert first["regenerated"] is True and second["cached"] is True and read["report"] == "## In short\nTheft is up."
    assert generate.await_count == 1
    kwargs = generate.await_args.kwargs
    assert kwargs["prompt_path"] == TREND_PROMPT_PATH
    assert kwargs["snapshot"]["list"] == "growing" and kwargs["snapshot"]["trends"]
    assert list((tmp_path / "reports").glob("art-trends-growing__*.json"))
    # The domain's own report is a different file, untouched.
    assert client.get("/v1/report/art").json()["found"] is False
