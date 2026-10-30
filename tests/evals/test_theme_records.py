"""Which themes help (abductive_engine ART-PLAN §14): a theme's track record
for one kind of success, learned only from earlier years, and the two
features it gives each artist-year."""
import pytest

from evals.theme_records import PRIOR, track_records, with_theme_features


def _rows():
    """Ten artists a year, 2001–2003, none with any success so far; in 2001
    the two named in theme A succeed next year, the one named in B does not,
    and one more artist succeeds unnamed."""
    rows = []
    for y in (2001, 2002, 2003):
        for i in range(10):
            outcome = None if y == 2003 else int(y == 2001 and i in (0, 1, 3))
            rows.append({"year": y, "own": [0, 0], "features": {}, "outcome": outcome, "case": f"c{i}"})
    return rows


CLAIMS = {("c0", 2001): {"A": 1}, ("c1", 2001): {"A": 2}, ("c2", 2001): {"B": 1},
          ("c0", 2002): {"A": 1, "B": 1}, ("c2", 2003): {"A": 1}}


def test_a_record_is_successes_less_expected_among_artists_with_the_same_amount_so_far():
    records = track_records(_rows(), CLAIMS)
    assert records[2001] == {}                                    # nothing before the first year
    # 2001: 3 of 10 with none so far succeed, so each is expected 0.3
    assert records[2002]["A"] == pytest.approx((2 - 0.6) / (0.6 + PRIOR))
    assert records[2002]["B"] == pytest.approx((0 - 0.3) / (0.3 + PRIOR))


def test_a_record_uses_only_years_whose_outcome_was_known():
    records = track_records(_rows(), CLAIMS)
    # 2002's outcomes are all failures, known by 2003; c0's 2002 claims count then
    assert records[2003]["A"] == pytest.approx((2 - 0.6 - 0.0) / (0.6 + 0.0 + PRIOR))
    assert records[2003]["B"] == pytest.approx((0 - 0.3 - 0.0) / (0.3 + 0.0 + PRIOR))


def test_each_artist_year_counts_claims_in_good_and_poor_record_themes():
    rows = with_theme_features(_rows(), CLAIMS, track_records(_rows(), CLAIMS))
    c0_2002 = next(r for r in rows if r["case"] == "c0" and r["year"] == 2002)
    assert c0_2002["features"] == {"good_theme": 1, "poor_theme": 1}
    c2_2003 = next(r for r in rows if r["case"] == "c2" and r["year"] == 2003)
    assert c2_2003["features"] == {"good_theme": 1, "poor_theme": 0}
    c0_2001 = next(r for r in rows if r["case"] == "c0" and r["year"] == 2001)
    assert c0_2001["features"] == {"good_theme": 0, "poor_theme": 0}       # no record yet
