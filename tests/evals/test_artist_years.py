"""Replay 17's scoring (evals/README.md): rivals judged by prequential
evidence, artist-years in year order, against a shuffled-years control."""
import random

from evals.artist_years import compare, level, shuffled


def test_counts_are_read_as_none_one_several():
    assert [level(c) for c in (0, 1, 2, 7)] == [0, 1, 2, 2]


def _world(order: bool, n=600, years=range(2000, 2012), seed=0):
    """Artists with a fame; press each year at random by fame; acquisitions
    either follow last year's press (order) or, like press, fame alone."""
    rng = random.Random(seed)
    panel = {}
    for a in range(n):
        fame = rng.random()
        press = {y: int(rng.random() < 0.6 * fame) for y in years}
        if order:
            acq = {y: int(press.get(y - 1, 0) == 1 and rng.random() < 0.8) for y in years}
        else:
            acq = {y: int(rng.random() < 0.6 * fame) for y in years}
        panel[f"a{a}"] = {"press": press, "museum": acq}
    return panel


def test_press_that_comes_first_is_found_and_shuffling_years_removes_it():
    panel = _world(order=True)
    real = compare(panel, target="museum", other="press", years=range(2000, 2012))
    control = compare(shuffled(panel, random.Random(1), range(2000, 2012)), target="museum", other="press", years=range(2000, 2012))
    assert real.gain > 200 and control.gain < real.gain / 5


def test_fame_alone_gives_no_gain_beyond_what_a_shuffle_gives():
    panel = _world(order=False)
    real = compare(panel, target="museum", other="press", years=range(2000, 2012))
    control = compare(shuffled(panel, random.Random(1), range(2000, 2012)), target="museum", other="press", years=range(2000, 2012))
    assert abs(real.gain - control.gain) < 40


def test_each_year_is_predicted_only_from_earlier_years():
    # A world whose rule flips in 2006: before, press leads; after, nothing does.
    panel = _world(order=True, years=range(2000, 2006))
    late = _world(order=False, years=range(2006, 2012), seed=3)
    for a in panel:
        for s in panel[a]:
            panel[a][s] |= late[a][s]
    by_year = compare(panel, target="museum", other="press", years=range(2000, 2012)).by_year
    assert by_year[2004] > 0.1
    assert by_year[2011] < by_year[2004]


def test_a_shuffle_moves_empty_years_too():
    panel = {"a": {"museum": {2001: 3}}}
    seen = {next(iter(shuffled(panel, random.Random(s), range(2000, 2010))["a"]["museum"])) for s in range(30)}
    assert len(seen) > 3


def test_the_placebo_reads_the_other_body_next_year_instead():
    # Acquisitions follow last year's press: last year's press helps, next year's does not.
    panel = _world(order=True)
    before = compare(panel, target="museum", other="press", years=range(2000, 2012), lag=1).gain
    after = compare(panel, target="museum", other="press", years=range(2000, 2012), lag=-1).gain
    assert before > 200 and after < before / 5
