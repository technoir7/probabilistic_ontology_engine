from evals.artist_records import records


def test_each_artist_year_carries_last_years_signals_and_this_years_acquisitions():
    panel = {"a": {"museum": {2003: 1, 2005: 2}, "nyt": {2004: 3}, "guardian": {2004: 1, 2010: 1}, "approval": {2004: 1}}}
    rows = {r["year"]: r for r in records(panel, range(2003, 2012), ("nyt", "guardian", "approval", "contested"))}
    r = rows[2004]                                   # state 2004, outcome 2005
    assert r["outcome"] == 2 and r["case"] == "a"
    assert r["features"] == {"nyt": 2, "guardian": 0, "approval": 1, "contested": 0}   # Guardian read from 2010
    assert rows[2010]["features"]["guardian"] == 1
    assert sorted(rows) == list(range(2003, 2012))


def test_own_past_is_this_years_and_earlier_acquisitions_graded_finely():
    panel = {"a": {"museum": {2001: 3, 2002: 1, 2003: 6}}}
    rows = {r["year"]: r for r in records(panel, range(2001, 2005), ("nyt",))}
    assert rows[2002]["own"] == [1, 3]               # 1 this year; 3 before (3-4)
    assert rows[2003]["own"] == [4, 3]               # 6 this year (5-8); 4 before (3-4)


def test_the_last_year_is_open_its_outcome_still_to_come():
    rows = {r["year"]: r for r in records({"a": {"museum": {2004: 1}}}, range(2003, 2005), ("nyt",))}
    assert rows[2003]["outcome"] == 1 and rows[2004]["outcome"] is None


def test_an_artist_is_shown_by_the_name_chicago_gives_them():
    from evals.artist_records import display_names
    museums = {"aic": {"agents": {"1": ["André Cadere", 1934, "Individual"], "2": ["", None, "Individual"]}}}
    assert display_names(museums, {"andre cadere", "jo smith"}) == {"andre cadere": "André Cadere", "jo smith": "Jo Smith"}
