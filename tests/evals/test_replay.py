"""The historical replay: its inputs, the run, and how it is scored."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from evals import fred_history as fh
from evals import replay, scoring
from src.domains.macro_regime_v1.ingestion.fred_client import FRED_SERIES
from src.domains.sources.fred import FREDObservation


def obs(sid, d, v):
    return FREDObservation(obs_date=d, value=v, series_id=sid)


class TestFredHistory:
    def test_parses_fred_csv_skipping_missing_values(self):
        text = "observation_date,T10Y2Y\n2024-01-02,0.5\n2024-01-03,.\n2024-01-04,-0.25\n"
        out = fh.parse_csv(text, "T10Y2Y")
        assert [(o.obs_date, o.value) for o in out] == [(date(2024, 1, 2), 0.5), (date(2024, 1, 4), -0.25)]

    def test_a_week_sees_only_what_was_published_by_then(self):
        history = {"CPIAUCSL": [obs("CPIAUCSL", date(2024, m, 1), m) for m in range(1, 7)]}
        seen = fh.observations_at(history, "CPIAUCSL", date(2024, 5, 3))
        # March CPI comes out in mid-April; April CPI not until mid-May.
        assert [o.obs_date for o in seen] == [date(2024, 3, 1), date(2024, 2, 1), date(2024, 1, 1)]

    def test_a_lagged_series_keeps_a_full_lookback(self):
        history = {"CPIAUCSL": [obs("CPIAUCSL", date(2022, 1, 1) + timedelta(days=31 * i), i) for i in range(30)]}
        for days in range(0, 60, 3):
            target = date(2024, 4, 1) + timedelta(days=days)
            assert len(fh.observations_at(history, "CPIAUCSL", target)) >= 13, target

    def test_newest_first_and_within_the_live_lookback(self):
        start = date(2023, 1, 1)
        history = {"T10Y2Y": [obs("T10Y2Y", start + timedelta(days=i), float(i)) for i in range(200)]}
        target = start + timedelta(days=199)
        seen = fh.observations_at(history, "T10Y2Y", target)
        assert seen[0].obs_date == target
        assert all(a.obs_date > b.obs_date for a, b in zip(seen, seen[1:]))
        assert seen[-1].obs_date >= target - timedelta(days=35)

    def test_the_credit_spread_comes_from_the_stand_in(self):
        d = date(2010, 1, 8)
        history = {sid: [] for sid in fh.SERIES}
        history[fh.CREDIT_STAND_IN] = [obs(fh.CREDIT_STAND_IN, d, 3.1)]
        week = fh.week_inputs(history, d)
        assert set(week) == set(FRED_SERIES.values())
        assert [o.value for o in week["BAMLH0A0HYM2"]] == [3.1]

    def test_can_use_the_real_series_instead(self):
        d = date(2025, 1, 10)
        history = {sid: [] for sid in fh.SERIES}
        history["BAMLH0A0HYM2"] = [obs("BAMLH0A0HYM2", d, 3.0)]
        history[fh.CREDIT_STAND_IN] = [obs(fh.CREDIT_STAND_IN, d, 1.7)]
        assert [o.value for o in fh.week_inputs(history, d, credit="BAMLH0A0HYM2")["BAMLH0A0HYM2"]] == [3.0]


class TestWeeks:
    def test_fridays_between_two_dates(self):
        weeks = replay.fridays(date(2024, 1, 1), date(2024, 1, 31))
        assert weeks == [date(2024, 1, 5), date(2024, 1, 12), date(2024, 1, 19), date(2024, 1, 26)]


def synthetic_history(weeks: int) -> dict:
    """Enough of every series for the pipeline to compute every signal."""
    end = date(2024, 6, 28)
    start = end - timedelta(days=7 * weeks + 1200)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    months = [d for d in days if d.day == 1]
    out = {}
    for sid in fh.SERIES:
        if sid in ("CPIAUCSL", "UNRATE"):
            out[sid] = [obs(sid, d, 100 + i * 0.3 if sid == "CPIAUCSL" else 4 + (i % 5) * 0.1) for i, d in enumerate(months)]
        elif sid == "WALCL":
            out[sid] = [obs(sid, d, 8e6 + (i % 9) * 1e4) for i, d in enumerate(days) if d.weekday() == 2]
        else:
            out[sid] = [obs(sid, d, 1 + (i % 17) * 0.05) for i, d in enumerate(days) if d.weekday() < 5]
    return out


@pytest.fixture(scope="module")
def rows():
    history = synthetic_history(12)
    end = date(2024, 6, 28)
    return replay.run(history, seed=0, start=end - timedelta(days=7 * 11), end=end)


class TestTheRun:

    def test_learns_one_week_at_a_time(self, rows):
        assert len(rows) == 12
        assert [r["week"] for r in rows] == sorted(r["week"] for r in rows)

    def test_records_the_leader_and_its_family(self, rows):
        # The programme of nothing yet, or one founded by a prompted connection (D24).
        assert all(r["family"] == "unconnected" or "–" in r["family"] for r in rows)

    def test_counts_the_active_candidates_of_each_family(self, rows):
        for r in rows:
            assert sum(r["active_families"].values()) == r["active"]

    def test_scores_each_week_before_learning_it_against_independence(self, rows):
        for r in rows:
            assert r["leader_ll"] <= 0 and r["independent_ll"] <= 0
            assert r["observed"] == 8

    def test_is_the_same_for_the_same_seed(self, rows):
        history = synthetic_history(12)
        end = date(2024, 6, 28)
        again = replay.run(history, seed=0, start=end - timedelta(days=7 * 11), end=end)
        # Candidate ids are random; what led, and its structure, are not.
        assert [(r["family"], r["edges"]) for r in again] == [(r["family"], r["edges"]) for r in rows]


def rows_with(families, start=date(2007, 1, 5)):
    return [{"week": (start + timedelta(weeks=i)).isoformat(), "family": f, "leader_ll": -4.0,
             "independent_ll": -5.0, "observed": 8} for i, f in enumerate(families)]


class TestScoring:
    def test_a_family_change_is_when_the_leaders_family_differs_from_last_week(self):
        rows = rows_with(["A", "A", "B", "B", "A"])
        assert [(c["week"], c["from"], c["to"]) for c in scoring.family_changes(rows)] == [
            (rows[2]["week"], "A", "B"), (rows[4]["week"], "B", "A")]

    def test_an_event_is_caught_by_a_change_within_the_window_after_it(self):
        rows = rows_with(["A"] * 10 + ["B"] * 40)
        events = [("hit", date(2007, 1, 1)), ("miss", date(2007, 4, 1))]
        caught = scoring.events_caught(scoring.family_changes(rows), events, window_weeks=26)
        assert caught == {"hit": True, "miss": False}

    def test_changes_away_from_every_event(self):
        rows = rows_with(["A"] * 10 + ["B"] * 30 + ["A"] * 10)
        away = scoring.changes_away_from_events(scoring.family_changes(rows), [("e", date(2007, 1, 1))], 26)
        assert [c["to"] for c in away] == ["A"]

    def test_chance_is_reproducible_and_a_share(self):
        weeks = [r["week"] for r in rows_with(["A"] * 300)]
        a = scoring.chance(weeks, 3, [("e", date(2008, 1, 1))], 26, draws=500)
        b = scoring.chance(weeks, 3, [("e", date(2008, 1, 1))], 26, draws=500)
        assert a == b and 0 <= a["mean_share_caught"] <= 1

    def test_structure_beats_independence_by_the_average_gap(self):
        rows = rows_with(["A", "A", "A"])
        rows[1]["observed"] = 7  # not every signal: left out
        assert scoring.fit_gap(rows) == {"weeks": 2, "mean_gap_nats": 1.0}

    def test_weeks_each_family_led_in_a_period(self):
        rows = rows_with(["A", "A", "B"])
        assert scoring.weeks_led(rows, date(2007, 1, 1), date(2007, 12, 31)) == {"A": 2, "B": 1}


class TestAsFirstPublished:
    def test_parses_an_alfred_vintage(self):
        text = "observation_date,CPIAUCSL_20100115\n2009-11-01,217.250\n2009-12-01,217.541\n"
        assert [(o.obs_date, o.value) for o in fh.parse_csv(text, "CPIAUCSL")] == [
            (date(2009, 11, 1), 217.25), (date(2009, 12, 1), 217.541)]

    def test_a_week_uses_the_latest_vintage_taken_by_then(self):
        vintages = {"CPIAUCSL": {
            "2010-01-16": [["2009-11-01", 217.25], ["2009-12-01", 217.541]],
            "2010-02-16": [["2009-12-01", 217.6], ["2010-01-01", 218.0]],
        }}
        history = fh.as_first_published({"CPIAUCSL": []}, vintages)
        seen = fh.observations_at(history, "CPIAUCSL", date(2010, 2, 5))
        assert [(o.obs_date, o.value) for o in seen] == [(date(2009, 12, 1), 217.541), (date(2009, 11, 1), 217.25)]
        later = fh.observations_at(history, "CPIAUCSL", date(2010, 2, 19))
        assert later[0].value == 218.0 and later[1].value == 217.6

    def test_before_the_first_vintage_nothing_is_known(self):
        history = fh.as_first_published({"CPIAUCSL": []}, {"CPIAUCSL": {"2010-01-16": [["2009-12-01", 1.0]]}})
        assert fh.observations_at(history, "CPIAUCSL", date(2010, 1, 8)) == []

    def test_unrevised_series_are_untouched(self):
        plain = {"T10Y2Y": [obs("T10Y2Y", date(2010, 1, 4), 2.0)]}
        assert fh.as_first_published(plain, {})["T10Y2Y"] == plain["T10Y2Y"]


class TestExportForTheLiveApp:
    def test_one_sunday_stamped_record_a_week_built_by_the_live_pipeline(self):
        from evals import export
        history = synthetic_history(4)
        records = export.weekly_records(history, date(2024, 6, 1), date(2024, 6, 30))
        assert [r.timestamp.date().weekday() for r in records] == [6] * len(records)
        assert [r.timestamp.date() for r in records] == [date(2024, 6, 2), date(2024, 6, 9), date(2024, 6, 16),
                                                         date(2024, 6, 23), date(2024, 6, 30)]
        assert all(r.source_ref.endswith(f"week-ending-{r.timestamp.date()}") for r in records)
        assert all(len(r.observed_assignments) == 8 for r in records)


def test_rows_round_trip_gzipped(tmp_path):
    rows = [{"week": "2024-01-05", "family": "T_null"}, {"week": "2024-01-12", "family": "T_credit"}]
    replay.write_rows(tmp_path / "seed0.jsonl.gz", rows)
    assert replay.read_rows(tmp_path / "seed0.jsonl.gz") == rows


def test_records_only_the_links_the_leader_uses():
    # Level 2 switches a link off when the evidence makes it unlikely to exist;
    # the engine no longer reasons with it, so the replay must not count it held.
    from uuid import uuid4
    from src.domains.test_domain_v1.domain import _var_list
    from src.engine.schemas import DependencyEdge
    from src.engine.services.programmes import unconnected
    start = unconnected("test-domain-v1", _var_list())
    a, b, c = (start.get_variable_by_name(n).variable_id for n in "ABC")
    used = DependencyEdge(edge_id=uuid4(), parent_variable_id=a, child_variable_id=b)
    off = DependencyEdge(edge_id=uuid4(), parent_variable_id=b, child_variable_id=c, enabled=False)
    leader = start.model_copy(update={"edges": [used, off]})
    assert replay.held_links(leader) == [f"{a}>{b}"]
