from evals.artist_records import records


def test_each_artist_year_carries_last_years_signals_and_this_years_acquisitions():
    panel = {"a": {"museum": {2003: 1, 2005: 2}, "nyt": {2004: 3}, "guardian": {2004: 1, 2010: 1}, "approval": {2004: 1}}}
    rows = {r["year"]: r for r in records(panel, range(2003, 2012), ("nyt", "guardian", "approval", "contested"))}
    r = rows[2004]                                   # state 2004, outcome 2005
    assert r["own"] == [0, 1] and r["outcome"] == 2 and r["case"] == "a"
    assert r["features"] == {"nyt": 2, "guardian": 0, "approval": 1, "contested": 0}   # Guardian read from 2010
    assert rows[2010]["features"]["guardian"] == 1
    assert sorted(rows) == list(range(2003, 2011))
