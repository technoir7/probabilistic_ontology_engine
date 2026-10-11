"""model.cadence and the D12 re-dating of stored weekly evidence."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.domains.sovereign_debt_v1.domain import SovereignDebtV1, get_variables
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.cadence import Daily, Weekly
from src.engine.runtime.data_migrations import move_friday_weekly_records_to_sunday
from src.engine.runtime.registry import REGISTRY
from tests.fakes import soft_record

WED = date(2026, 3, 4)


def test_weekly_dates_are_sundays_and_runs_are_mondays():
    weekly = Weekly()
    assert weekly.default_target(WED) == date(2026, 3, 1)
    assert weekly.default_target(date(2026, 3, 2)) == date(2026, 3, 1)  # Monday run → yesterday
    assert weekly.align(date(2026, 2, 27)) == date(2026, 2, 22)
    assert weekly.window_targets(14, WED) == [date(2026, 2, 15), date(2026, 2, 22), date(2026, 3, 1)]
    noon = datetime(2026, 3, 4, 12, tzinfo=timezone.utc)
    assert weekly.next_run(noon, 9) == datetime(2026, 3, 9, 9, tzinfo=timezone.utc)
    monday_late = datetime(2026, 3, 9, 10, tzinfo=timezone.utc)
    assert weekly.next_run(monday_late, 9) == datetime(2026, 3, 16, 9, tzinfo=timezone.utc)


def test_daily_dates():
    daily = Daily()
    assert daily.default_target(WED) == date(2026, 3, 3)
    assert daily.window_targets(3, WED) == [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)]


def test_every_entry_point_reads_one_cadence_per_domain():
    cadences = {r.key: type(r.cadence).__name__ for r in REGISTRY}
    assert cadences == {
        "ng": "Daily", "art": "Daily",
        **{k: "Weekly" for k in ("mr", "ai", "sd", "cc", "er", "lm", "cr", "gp", "sf")},
    }


def test_friday_records_move_to_their_sunday_and_duplicates_drop():
    engine = ProbabilisticOntologyEngine(db_path=":memory:")
    engine.register_domain(SovereignDebtV1())
    engine.activate_domain("sovereign-debt-v1")
    variables = get_variables().values()
    for day in (date(2026, 2, 20), date(2026, 2, 27), date(2026, 3, 1), date(2026, 3, 4)):
        engine.ingest(soft_record(variables, day, seed="m"))  # Fri, Fri, Sun, Wed

    move_friday_weekly_records_to_sunday(engine, "sovereign-debt-v1")
    stamps = sorted(r.timestamp.date() for r in engine.evidence_store.load_all("sovereign-debt-v1"))
    # 2/20 → 2/22; 2/27 → 3/1, which exists, so it is dropped; Wednesday is untouched.
    assert stamps == [date(2026, 2, 22), date(2026, 3, 1), date(2026, 3, 4)]

    move_friday_weekly_records_to_sunday(engine, "sovereign-debt-v1")
    assert len(engine.evidence_store.load_all("sovereign-debt-v1")) == 3
