"""The work most likely to succeed (REFACTOR_SPEC D31; abductive_engine
ART-PLAN §12): four kinds of success, each judged by the case engine
offline, shipped as a snapshot with what critics rewarded this year."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from src.domains.art_prestige_regime_v1 import success
from src.engine.api import app as api_app
from src.engine.api import success_narrative


def _kind(leader):
    return {"title": "Museum buys", "outcome": "acquisitions next year", "leader": leader, "leader_since": 2009,
            "gain": 120.5, "mechanisms": [["nyt", 110.0], ["nyt+painting", 112.0]],
            "effects": {"nyt": {"1": 0.8, "2": 1.4}}, "dealt": {"nyt": [-3.0, 1.0, -2.0]}, "placebo": 40.0, "placebo_fair": True,
            "most_raised": [["Yayoi Kusama", 0.2, 0.3]], "years": [[2004, 1.5], [2005, -0.4]]}


def _snapshot():
    return {"year": 2026, "forecast_for": 2026,
            "kinds": {k: dict(_kind(["nyt"]), title=k.title()) for k in success.KINDS},
            "rewarded": [{"kind": "medium", "name": "photography", "approvals": 10, "disapprovals": 2,
                          "approved": ["a: good"], "disapproved": ["b: bad"]}],
            "at_the_top": {"market": {"table_year": 2025, "artists": 300, "themes": {"7": [12, 30]},
                                      "media": {"painting": 13}, "said": {"7": ["a's show: bold"]}}}}


def test_a_snapshot_loads_with_its_four_kinds_and_what_critics_rewarded():
    s = success.load(_snapshot())
    assert set(s.kinds) == set(success.KINDS) and s.kinds["museum"].leader == ("nyt",)
    assert s.kinds["museum"].effects[("nyt", 2)] == 1.4 and s.rewarded[0].name == "photography"
    assert s.kinds["museum"].placebo_fair is True
    assert s.at_the_top["market"].artists == 300 and s.at_the_top["market"].themes["7"] == (12, 30)


@pytest.mark.parametrize("break_it", [
    lambda s: s["kinds"].pop("market"),
    lambda s: s["kinds"]["press"]["leader"].append("unheard_of"),     # a leader outside the pool
    lambda s: s["kinds"]["press"].pop("placebo_fair"),                # unsaid whether the placebo is a fair test
    lambda s: s["at_the_top"].update(fame=s["at_the_top"]["market"]),  # a kind of success there is not
    lambda s: s.pop("at_the_top"),
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
    assert set(body["success"]["kinds"]) == set(success.KINDS + success.APART)


def test_each_kind_says_whether_its_placebo_is_a_fair_test():
    """Next year's claims and articles are part of next year's approvals and
    press, so for those two the year-after features are not a fair control."""
    s = success.current()
    assert {k: v.placebo_fair for k, v in s.kinds.items()} == {
        "approve": False, "press": False, "museum": True, "market": True, "movers": True}


@pytest.mark.parametrize("kind", success.KINDS)
def test_each_kind_has_a_report_snapshot(kind):
    from src.engine.api import success_narrative
    snap = success_narrative.success_snapshot("art", kind)
    assert snap.kind == kind and snap.leader and snap.critics_rewarded_this_year
    assert snap.control_placebo_is_a_fair_test == success.current().kinds[kind].placebo_fair
    s = success.current()
    k = s.kinds[kind]
    others = {v.title for kk, v in s.kinds.items() if kk != kind and kk not in s.apart}
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
        return ("## In short\nBeing written about helps.\n\n## Image prompt\nA photograph of a woman at work."
                "\n\n## Wall text\n*At Work*, photography, 2026\n\nThe artist photographs work.")
    monkeypatch.setattr(report, "generate_report", fake)
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    with TestClient(api_app.app) as client:
        assert client.get("/v1/success/art/museum/report").json()["found"] is False
        body = client.post("/v1/success/art/museum/report/refresh").json()
        assert client.get("/v1/success/art/museum/report").json()["found"] is True
    assert seen == {"prompt": report.SUCCESS_PROMPT_PATH, "kind": "museum"} and "Being written about" in body["report"]
    assert f"A photograph of a woman at work. {report.IMAGE_SETTING}" in body["report"]     # finished by code
    voice = success_narrative.WALL_TEXT_VOICES["museum"]
    assert body["report"].endswith(f"{report.wall_text_label(voice)}\n\n*At Work*, photography, 2026\n\nThe artist photographs work.")
    assert report.REASONS_HEADING in body["report"]


def _verdicts(kind):
    from src.engine.api import success_narrative
    return " ".join(success_narrative.success_snapshot("art", kind).verdicts)


def test_verdicts_are_fixed_by_rule_so_a_report_cannot_soften_them():
    assert "clearly but modestly" in _verdicts("market")                 # +58 over fourteen years (ART-PLAN §12.10)
    assert "overwhelming" in _verdicts("approve")
    assert "comes with this success rather than before it" in _verdicts("market")   # placebo 96 beats 58
    assert "comes before this success" in _verdicts("museum")            # 227 against 191
    assert "no test here" in _verdicts("press")
    assert "photography" in _verdicts("museum").split("adds nothing")[0].rsplit(".", 1)[-1]   # dealt, it scored better
    # new trend joined the press leader in 2025, after the last scored year: untested, not useless
    assert "new trend that year joined the leader only in 2025" in _verdicts("press")
    assert "adds nothing" not in _verdicts("press")


def test_a_verdict_names_what_leads_for_every_kind_and_which_way_it_pushes():
    v = _verdicts("approve")
    assert "NYT coverage that year leads for all four kinds; it helps, except that it hurts for more press." in v


def test_a_verdict_says_for_each_leading_feature_which_other_kinds_it_leads_for():
    v = _verdicts("museum")
    assert ("claims about the artist in an argued-over trend that year also leads for critics approve (helps), "
            "more press (helps); not for market.") in v
    assert "articles on the artist tagged photography that year leads for no other kind." in v


def test_a_fair_year_after_control_says_why_it_is_fair():
    assert "counted apart from the press" in _verdicts("market")


def test_each_feature_says_which_trend_list_or_medium_it_counts():
    s = success.current()
    assert s.lists == {"new_trend": "new", "growing_trend": "growing", "fading_trend": "fading", "argued_trend": "argued"}
    assert s.media == {"painting": "painting", "photography": "photography", "sculpture": "sculpture"}


def _subject(kind):
    from src.engine.api import success_narrative
    return success_narrative.success_snapshot("art", kind).image_subject


def test_the_image_subject_is_chosen_by_rule():
    """ART-PLAN §12.8: the theme the leader's lists push up most, ties to this
    year's net approvals; the leader's medium, else this year's most approved."""
    approve, press, museum = _subject("approve"), _subject("press"), _subject("museum")
    # on growing and argued, as is biennale political controversies, but approved 11 to 0, not 0 to 16
    assert (approve.theme, approve.medium) == ("indigenous and subcontinental art", "painting")
    assert approve.medium_from_the_leading_features is True
    # press's new trend pushes down, so the themes on it lose
    assert "new" not in press.theme_is_on_this_years_lists
    assert (press.theme, press.medium, press.medium_from_the_leading_features) == (
        "women artists' careers", "photography", False)
    assert (museum.theme, museum.medium, museum.medium_from_the_leading_features) == (
        "women artists' careers", "photography", True)
    assert approve.distinctive_words and approve.what_critics_said


def test_nothing_is_illustrated_where_the_gain_is_too_small_to_claim_and_nothing_describes_it(monkeypatch):
    from src.engine.api import success_narrative
    snap = _snapshot()
    snap["kinds"]["market"]["gain"] = 2.4
    snap["at_the_top"] = {}
    monkeypatch.setattr(success_narrative, "current_success", lambda key: success.load(snap))
    assert success_narrative.success_snapshot("art", "market").image_subject is None


def test_where_nothing_predicts_the_market_its_prompt_describes_the_artists_at_the_top():
    """ART-PLAN §12.9: the theme naming the most artists in the latest table,
    ties to claims about them; the medium on the most of their articles."""
    from src.engine.runtime.trends import current_trends
    s, t, m = success.current(), current_trends("art"), _subject("market")
    top = s.at_the_top["market"]
    best = max((k for k in top.themes if k in t.trends), key=lambda k: top.themes[k])
    assert m.theme == t.trends[best].name and m.describes_instead
    assert m.medium == max(top.media, key=top.media.get)
    assert m.what_critics_said == list(top.said[best])         # about the artists at the top, not the theme at large
    r = _reasons("market")
    assert "describes" in r and "not what leads to it" in r and f"{top.artists}" in r and f"{top.table_year}" in r
    # by the user's choice the market describes whatever its gain (deviation 6); why, from its verdicts
    assert s.kinds["market"].gain >= 10 and "goes with market success rather than ahead of it" in r
    assert "what critics said about these artists" in r
    assert not _subject("museum").describes_instead


WALL = "\n\n## Wall text\n\n*River Hours*, painting, 2027\n\nThe artist paints a river.\n"
VOICE = "the label of a museum that has just acquired it"


def test_code_finishes_the_image_prompt_so_the_writer_cannot_change_its_label_or_setting():
    from src.engine.api import report
    text = report.finish_success_report("## In short\nA.\n\n## Image prompt\n\nA large painting of a river.\n" + WALL,
                                        ["Why the river.", "Why paint."], VOICE)
    assert text == ("## In short\nA.\n\n" + report.REASONS_HEADING + "\n\nWhy the river.\n\nWhy paint.\n\n"
                    + report.IMAGE_HEADING + "\n\n" + report.IMAGE_LABEL + "\n\n"
                    "A large painting of a river. " + report.IMAGE_SETTING + "\n\n"
                    + report.WALL_HEADING + "\n\n" + report.wall_text_label(VOICE) + "\n\n"
                    "*River Hours*, painting, 2027\n\nThe artist paints a river.")


def test_the_wall_text_label_names_the_voice_and_says_it_is_fiction():
    from src.engine.api import report
    label = report.wall_text_label(VOICE)
    assert VOICE in label and "fictional" in label and "not" in label


def test_words_the_writer_adds_to_the_image_prompt_heading_are_not_part_of_the_prompt():
    from src.engine.api import report
    text = report.finish_success_report("## In short\nA.\n\n## Image prompt: a vision\nA river." + WALL, ["Why."], VOICE)
    assert ("\n\nA river. " + report.IMAGE_SETTING + "\n\n" + report.WALL_HEADING) in text and "vision" not in text


@pytest.mark.parametrize("written", [
    "## In short\nA.",
    "## In short\nA.\n\n## Image prompt\n\n" + WALL,
    "## In short\nA.\n\n## Image prompt\n\nA river.",
    "## In short\nA.\n\n## Image prompt\n\nA river.\n\n## Wall text\n\n",
])
def test_an_image_prompt_or_wall_text_wanted_but_not_written_is_an_error(written):
    from src.engine.api import report
    with pytest.raises(ValueError):
        report.finish_success_report(written, ["Why."], VOICE)


def test_where_nothing_is_illustrated_code_says_so_whatever_the_writer_wrote():
    from src.engine.api import report
    for written in ("## In short\nA.", "## In short\nA.\n\n## Image prompt\nA bird." + WALL):
        assert report.finish_success_report(written, None, None) == (
            "## In short\nA.\n\n" + report.IMAGE_HEADING + "\n\n" + report.NOTHING_TO_ILLUSTRATE)


@pytest.mark.parametrize("kind, words", [("museum", "acquired"), ("market", "for sale"), ("movers", "for sale"),
                                         ("approve", "exhibition"), ("press", "exhibition")])
def test_who_speaks_in_the_wall_text_is_fixed_by_kind(kind, words):
    """ART-PLAN §12.11: a voice, not a finding."""
    assert words in success_narrative.WALL_TEXT_VOICES[kind]
    subject = _subject(kind)
    if subject:
        assert subject.wall_text_voice == success_narrative.WALL_TEXT_VOICES[kind]


def _reasons(kind):
    return " ".join(_subject(kind).reasons)


def test_the_reasons_for_the_theme_say_the_lists_the_tie_and_what_came_next():
    r = _reasons("approve")
    assert "indigenous and subcontinental art" in r and "growing" in r and "argued over" in r
    assert "11 for, none against" in r and "biennale political controversies (none for, 16 against)" in r
    assert "not this theme in particular" in r
    assert "count against" in _reasons("press") and "new" in _reasons("press")     # press's new list pushes down
    assert "count against" not in r


def test_the_reasons_for_the_medium_say_whether_it_was_tested_and_what_it_adds():
    assert "adds almost nothing" in _reasons("approve")                 # painting adds about 2
    assert "adds nothing" in _reasons("museum")                         # photography, dealt, scored better
    press = _reasons("press")
    assert "not a tested finding" in press and "788 for, 138 against" in press
    # only the tagged media were tested; the media critics judged that never could be are named from the data
    for m in ("ceramics", "drawing", "installation", "video"):
        assert m in press


def test_the_reasons_say_the_details_and_setting_are_not_findings():
    assert "not findings" in _reasons("museum") and "the same for every prompt" in _reasons("museum")


def test_each_push_comes_with_its_odds_worked_out_so_the_writer_does_no_arithmetic():
    """The v5 reports turned a push of 0.63 into "two and a half times" the
    odds, and read two pushes against none as one against the other."""
    import math
    for e in success_narrative.success_snapshot("art", "market").leader_effects:
        assert e.times_the_odds_of_an_artist_with_the_same_past_and_none == round(math.exp(e.push), 1)


def test_a_kind_kept_apart_is_compared_with_the_four_but_never_counted_among_them(monkeypatch):
    """ART-PLAN §13: market movers has its own panel and report."""
    snap = _snapshot()
    snap["kinds"]["movers"] = dict(_kind(["nyt"]), title="Market movers")
    snap["kinds"]["movers"]["effects"] = {"nyt": {"1": -0.5, "2": -0.6}}      # hurts movers
    monkeypatch.setattr(success_narrative, "current_success", lambda key: success.load(snap))
    approve = success_narrative.success_snapshot("art", "approve")
    assert "Market movers" not in approve.other_kinds
    assert "leads for all four kinds; it helps in all four." in " ".join(approve.verdicts)
    movers = success_narrative.success_snapshot("art", "movers")
    assert set(movers.other_kinds) == {k.title() for k in success.KINDS}
    assert "leads for every kind of success too; it helps in all of them." in " ".join(movers.verdicts)


def test_only_the_kinds_kept_apart_may_join_the_four():
    snap = _snapshot()
    snap["kinds"]["fame"] = snap["kinds"]["market"]
    with pytest.raises(ValueError):
        success.load(snap)
