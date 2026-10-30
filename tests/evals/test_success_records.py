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
    claims = [("a", "7", "a's show: bold", "2026-01-02 g x"), ("a", "7", "a's paintings: thin", "2026-03-01 g y"),
              ("b", "7", "b: big", "2026-02-01 n z"), ("c", "7", "c: not at the top", "2026-04-01 g w"),
              ("b", "9", "b's bronzes: heavy", "2026-01-01 g v")]
    media = [("a", "painting"), ("c", "painting"), ("b", "sculpture"), ("b", "painting")]
    top = at_the_top(ranks, 2025, claims, media)
    assert top["artists"] == 2 and top["table_year"] == 2025
    assert top["themes"] == {"7": [2, 3], "9": [1, 1]}           # artists named, claims about them
    assert top["media"] == {"painting": 2, "sculpture": 1}
    # what critics said about those at the top, most recent first (ART-PLAN §12.9 amended)
    assert top["said"] == {"7": ["a's paintings: thin", "b: big", "a's show: bold"], "9": ["b's bronzes: heavy"]}


def test_at_the_top_keeps_only_the_most_recent_claims_of_a_theme():
    from evals.success_records import SAID, at_the_top
    claims = [("a", "7", f"claim {i}", f"2026-01-{i:02d}") for i in range(1, SAID + 3)]
    assert at_the_top({"a": {2025: 1}}, 2025, claims, [])["said"]["7"][0] == f"claim {SAID + 2}"
    assert len(at_the_top({"a": {2025: 1}}, 2025, claims, [])["said"]["7"]) == SAID


def test_market_bands_run_from_not_listed_to_the_top_25():
    from evals.success_records import market_band
    assert [market_band(r) for r in (None, 500, 251, 250, 101, 100, 26, 25, 1)] == [0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_a_mover_case_is_next_years_move_between_bands_with_the_market_cases_gaps():
    """ART-PLAN §13 deviation 1: not up (down or the same band), up one band,
    up two or more; outcome 0 is what the case engine reads as none."""
    from evals.success_records import movers_records
    ranks = {"a": {2016: 300, 2017: 90, 2018: 95, 2020: 400}}
    rows = movers_records({"a": {}}, ranks, covered={2016, 2017, 2018, 2020, 2021}, years=range(2016, 2022), pool=POOL)
    by_year = {r["year"]: r for r in rows}
    assert set(by_year) == {2017, 2020, 2021}                     # as market_records
    assert by_year[2017]["own"] == [3, 1] and by_year[2017]["outcome"] == 0     # 26–100 both years: not up
    assert by_year[2020]["own"] == [1, 3] and by_year[2020]["outcome"] == 0     # 251–500, then not listed: not up
    assert by_year[2021]["outcome"] is None
    rows = movers_records({"b": {}}, {"b": {2017: 400, 2018: 20}}, covered={2016, 2017, 2018}, years=range(2016, 2019),
                          pool=POOL)
    assert {r["year"]: r["outcome"] for r in rows}[2017] == 2                    # 251–500 to 1–25: up three
    rows = movers_records({"c": {}}, {"c": {2017: 120, 2018: 90}}, covered={2016, 2017, 2018}, years=range(2016, 2019),
                          pool=POOL)
    assert {r["year"]: r["outcome"] for r in rows}[2017] == 1                    # 101–250 to 26–100: up one


def test_an_unknown_band_is_not_a_band():
    from evals.success_records import movers_records
    rows = movers_records({"a": {}}, {"a": {2016: 30}}, covered={2016}, years=range(2016, 2018), pool=POOL)
    assert rows[-1]["year"] == 2017 and rows[-1]["own"][0] == 5       # the open year without a table
