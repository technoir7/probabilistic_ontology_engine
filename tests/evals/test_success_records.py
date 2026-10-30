"""The work most likely to succeed (abductive_engine ART-PLAN §12.3): each
artist-year with its trend and medium features and four kinds of success
next year."""
from evals.success_records import count_records, market_level, market_records

POOL = ("nyt", "painting")


def test_a_count_outcome_reads_next_year_and_grades_the_own_past_finely():
    people = {"a": {"approval": {2004: 1, 2005: 3}, "nyt": {2004: 2}, "painting": {2004: 1}}}
    rows = count_records(people, ("approval",), [2004, 2005], POOL)
    first, last = rows
    assert (first["year"], first["own"], first["features"], first["outcome"]) == (2004, [1, 0], {"nyt": 2, "painting": 1}, 2)
    assert last["outcome"] is None and last["own"] == [3, 1]          # 3 this year (doubling 3), 1 before


def test_press_sums_both_papers():
    people = {"a": {"nyt": {2005: 1}, "guardian": {2005: 1}}}
    rows = count_records(people, ("nyt", "guardian"), [2004, 2005], POOL)
    assert rows[0]["outcome"] == 2


def test_market_levels_are_top_100_ranks_up_to_500_or_not_listed():
    assert [market_level(r) for r in (None, 1, 100, 101, 500)] == [0, 2, 2, 1, 1]


def test_a_market_case_needs_a_table_this_year_next_year_and_before_never_reading_a_gap_as_unlisted():
    ranks = {"a": {2016: 40, 2017: 50, 2018: 300, 2020: 300}}
    rows = market_records({"a": {}}, ranks, covered={2016, 2017, 2018, 2020, 2021}, years=range(2016, 2022), pool=POOL)
    by_year = {r["year"]: r for r in rows}
    # 2016: no table before, so no known own past for press to stand in for
    # (ART-PLAN §12 deviation 3); 2018: no 2019 table; 2019: none this year
    assert set(by_year) == {2017, 2020, 2021}
    assert by_year[2017]["own"] == [2, 2] and by_year[2017]["outcome"] == 1
    assert by_year[2020]["own"] == [1, 2] and by_year[2020]["outcome"] == 0   # not listed in 2021
    assert by_year[2021]["outcome"] is None          # the open year


def test_at_the_top_counts_what_the_press_says_about_artists_in_the_latest_table():
    from evals.success_records import at_the_top
    ranks = {"a": {2025: 3}, "b": {2025: 400, 2024: 10}, "c": {2024: 1}}      # c is not in the latest table
    claims = [("a", "7"), ("a", "7"), ("b", "7"), ("c", "7"), ("b", "9")]
    media = [("a", "painting"), ("c", "painting"), ("b", "sculpture"), ("b", "painting")]
    top = at_the_top(ranks, 2025, claims, media)
    assert top["artists"] == 2 and top["table_year"] == 2025
    assert top["themes"] == {"7": [2, 3], "9": [1, 1]}           # artists named, claims about them
    assert top["media"] == {"painting": 2, "sculpture": 1}
