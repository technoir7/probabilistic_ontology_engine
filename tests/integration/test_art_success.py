"""The work most likely to succeed (REFACTOR_SPEC D31; abductive_engine
ART-PLAN §12): four kinds of success, each judged by the case engine
offline, shipped as a snapshot with what critics rewarded this year."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from src.domains.art_prestige_regime_v1 import success
from src.engine.api import app as api_app


def _kind(leader):
    return {"title": "Museum buys", "outcome": "acquisitions next year", "leader": leader, "leader_since": 2009,
            "gain": 120.5, "mechanisms": [["nyt", 110.0], ["nyt+painting", 112.0]],
            "effects": {"nyt": {"1": 0.8, "2": 1.4}}, "dealt": {"nyt": [-3.0, 1.0, -2.0]}, "placebo": 40.0, "placebo_fair": True,
            "most_raised": [["Yayoi Kusama", 0.2, 0.3]], "years": [[2004, 1.5], [2005, -0.4]]}


def _snapshot():
    return {"year": 2026, "forecast_for": 2026,
            "kinds": {k: _kind(["nyt"]) for k in success.KINDS},
            "rewarded": [{"kind": "medium", "name": "photography", "approvals": 10, "disapprovals": 2,
                          "approved": ["a: good"], "disapproved": ["b: bad"]}]}


def test_a_snapshot_loads_with_its_four_kinds_and_what_critics_rewarded():
    s = success.load(_snapshot())
    assert set(s.kinds) == set(success.KINDS) and s.kinds["museum"].leader == ("nyt",)
    assert s.kinds["museum"].effects[("nyt", 2)] == 1.4 and s.rewarded[0].name == "photography"
    assert s.kinds["museum"].placebo_fair is True


@pytest.mark.parametrize("break_it", [
    lambda s: s["kinds"].pop("market"),
    lambda s: s["kinds"]["press"]["leader"].append("unheard_of"),     # a leader outside the pool
    lambda s: s["kinds"]["press"].pop("placebo_fair"),                # unsaid whether the placebo is a fair test
])
def test_a_snapshot_that_does_not_hang_together_is_refused(break_it):
    snap = copy.deepcopy(_snapshot())
    break_it(snap)
    with pytest.raises((ValueError, KeyError)):
        success.load(snap)


def test_the_domain_ships_its_success_snapshot_and_serves_it():
    assert success.current() is not None
    with TestClient(api_app.app) as client:
        body = client.get("/v1/success", params={"domain": "art"}).json()
        assert client.get("/v1/success", params={"domain": "mr"}).json() == {"domain": "mr", "success": None}
    assert set(body["success"]["kinds"]) == set(success.KINDS)


def test_each_kind_says_whether_its_placebo_is_a_fair_test():
    """Next year's claims and articles are part of next year's approvals and
    press, so for those two the year-after features are not a fair control."""
    s = success.current()
    assert {k: v.placebo_fair for k, v in s.kinds.items()} == {
        "approve": False, "press": False, "museum": True, "market": True}


@pytest.mark.parametrize("kind", success.KINDS)
def test_each_kind_has_a_report_snapshot(kind):
    from src.engine.api import narrative
    snap = narrative.success_snapshot("art", kind)
    assert snap.kind == kind and snap.leader and snap.critics_rewarded_this_year
    assert snap.control_placebo_is_a_fair_test == success.current().kinds[kind].placebo_fair
    s = success.current()
    k = s.kinds[kind]
    others = {v.title for kk, v in s.kinds.items() if kk != kind}
    assert set(snap.other_kinds) == others
    for title, o in snap.other_kinds.items():
        theirs = next(v for v in s.kinds.values() if v.title == title)
        assert len(o.leading_features) == len(theirs.leader)        # only what leads there, in words
    # What each leading feature adds: the gain lost when it alone is dealt at random
    adds = {a.feature: a.nats for a in snap.each_leading_feature_adds}
    assert len(adds) == len(k.dealt)
    f, deals = next(iter(k.dealt.items()))
    assert adds[s.meanings[f]] == round(k.gain - sum(deals) / len(deals), 1)
    assert snap.scored_years == len(k.years)


def test_an_unknown_kind_or_a_domain_without_success_has_no_report():
    with TestClient(api_app.app) as client:
        assert client.get("/v1/success/art/fame/report").status_code == 404
        assert client.get("/v1/success/mr/museum/report").status_code == 404


def test_a_success_report_is_written_from_its_own_prompt(monkeypatch, tmp_path):
    from src.engine.api import report
    seen = {}

    async def fake(snapshot, *, prompt_path, **_):
        seen["prompt"], seen["kind"] = prompt_path, snapshot["kind"]
        return "## In short\nBeing written about helps."
    monkeypatch.setattr(report, "generate_report", fake)
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    with TestClient(api_app.app) as client:
        assert client.get("/v1/success/art/museum/report").json()["found"] is False
        body = client.post("/v1/success/art/museum/report/refresh").json()
        assert client.get("/v1/success/art/museum/report").json()["found"] is True
    assert seen == {"prompt": report.SUCCESS_PROMPT_PATH, "kind": "museum"} and "Being written about" in body["report"]


def _verdicts(kind):
    from src.engine.api import narrative
    return " ".join(narrative.success_snapshot("art", kind).verdicts)


def test_verdicts_are_fixed_by_rule_so_a_report_cannot_soften_them():
    assert "too small to claim" in _verdicts("market")                   # +2.4 over seven years
    assert "overwhelming" in _verdicts("approve")
    assert "comes with this success rather than before it" in _verdicts("market")   # placebo 7.2 beats 2.4
    assert "comes before this success" in _verdicts("museum")            # 227 against 191
    assert "no test here" in _verdicts("press")
    assert "photography" in _verdicts("museum").split("adds nothing")[0].rsplit(".", 1)[-1]   # dealt, it scored better
    # new trend joined the press leader in 2025, after the last scored year: untested, not useless
    assert "new trend that year joined the leader only in 2025" in _verdicts("press")
    assert "adds nothing" not in _verdicts("press")


def test_a_verdict_names_what_leads_for_every_kind_and_which_way_it_pushes():
    v = _verdicts("approve")
    assert "Leads for all four kinds of success: NYT coverage" in v and "hurts for more press" in v
