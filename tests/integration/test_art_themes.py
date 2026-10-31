"""Which themes help (abductive_engine ART-PLAN §14): a theme's track record,
tested on top of each kind of success's leader, shipped in the success
snapshot with its own report."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.domains.art_prestige_regime_v1 import success
from src.engine.api import app as api_app
from src.engine.api import success_narrative


def test_each_kind_ships_its_theme_test():
    s = success.current()
    assert set(s.themes) == set(success.KINDS)
    museum = s.themes["museum"]
    assert "good_theme" in museum.leader and museum.gain > museum.gain_without
    assert museum.best and museum.worst and all(r > 0 for _, r in museum.best) and all(r < 0 for _, r in museum.worst)
    assert "good_theme" not in s.themes["press"].leader


def _verdicts(kind):
    out = success_narrative.themes_snapshot("art")
    return " ".join(next(k for k in out.kinds if k.kind == kind).verdicts)


def test_verdicts_say_by_rule_where_a_themes_record_helps():
    assert "joins what leads" in _verdicts("museum") and "clearly but modestly" in _verdicts("museum")
    assert "comes before" in _verdicts("museum")                      # placebo 233 below 243
    assert "adds nothing" in _verdicts("press") and "no test here" in _verdicts("press")
    # since §16 (makers who are artists) market's record joins the leader, by too little to claim anything
    assert "too little to claim anything" in _verdicts("market")


def test_the_theme_report_has_its_own_route_and_prompt(monkeypatch, tmp_path):
    from src.engine.api import report
    seen = {}

    async def fake(snapshot, *, prompt_path, **_):
        seen["prompt"], seen["kinds"] = prompt_path, [k["kind"] for k in snapshot["kinds"]]
        return "## In short\nCareer themes help museum buys."
    monkeypatch.setattr(report, "generate_report", fake)
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    with TestClient(api_app.app) as client:
        assert client.get("/v1/success/art/themes/report").json()["found"] is False
        body = client.post("/v1/success/art/themes/report/refresh").json()
        assert client.get("/v1/success/mr/themes/report").status_code == 404
        served = client.get("/v1/success", params={"domain": "art"}).json()["success"]
    assert seen == {"prompt": report.THEMES_PROMPT_PATH, "kinds": list(success.KINDS)}
    assert body["report"].startswith("## In short")
    assert served["themes"]["museum"]["best"]
