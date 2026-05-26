from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from src.domains.agriculture_weekly import (
    latest_week_ending_on_or_before,
    weekly_backfill_dates,
)
from src.domains.corn_v1.domain import CornV1, get_variables as corn_variables
from src.domains.corn_v1.ingestion.nasdaq_client import CornNASDAQSnapshot
from src.domains.corn_v1.ingestion.pipeline import CornPipeline
from src.domains.corn_v1.ingestion.usda_nass_client import CornNASSSnapshot
from src.domains.natural_gas_v1.domain import NaturalGasV1
from src.domains.test_domain_v1.domain import TestDomainV1, get_variables as _test_variables
from src.engine.api import app as api_app
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
)
from src.engine.variable_identity import stable_variable_id


def test_stable_variable_id_determinism():
    assert stable_variable_id("corn-v1", "CornPriceUp") == stable_variable_id(
        "corn-v1", "CornPriceUp"
    )
    assert stable_variable_id("corn-v1", "CornPriceUp") != stable_variable_id(
        "soybean-v1", "SoyPriceUp"
    )
    assert corn_variables()["CornPriceUp"].variable_id == stable_variable_id(
        "corn-v1", "CornPriceUp"
    )


def test_legacy_persisted_evidence_remains_readable_by_position(tmp_path):
    db_path = str(tmp_path / "legacy_identity.db")
    domain_id = TestDomainV1().module_id()
    legacy_vars = list(_test_variables().values())
    legacy_record = EvidenceRecord(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        observed_assignments=[
            ObservedAssignment(variable_id=uuid4(), observed_value=True)
            for _ in legacy_vars
        ],
        source_type=SourceType.API,
        source_ref="legacy-random-variable-ids",
    )

    first = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    first.evidence_store.append(legacy_record, domain_id)

    restarted = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    restarted.register_domain(TestDomainV1())
    dom = restarted.get_population(domain_id).dominant()

    assert dom is not None
    assert dom.evidence_count == 1
    assert math.isfinite(dom.log_score)
    migrated = restarted.evidence_store.load_all(domain_id)[0]
    assert {
        assignment.variable_id for assignment in migrated.observed_assignments
    } == {variable.variable_id for variable in legacy_vars}


def test_weekly_backfill_dates_step_by_iso_week():
    dates = weekly_backfill_dates(15, today=date(2026, 5, 26))

    assert dates == [date(2026, 5, 10), date(2026, 5, 17), date(2026, 5, 24)]
    assert all(day.weekday() == 6 for day in dates)


def test_corn_pipeline_uses_weekly_canonical_timestamp():
    target = date(2026, 5, 20)  # Wednesday
    nass = CornNASSSnapshot(
        target_date=target,
        planting_progress_pct=75.0,
        planting_5yr_avg_pct=85.0,
        condition_good_exc_pct=50.0,
        yield_forecast_bu_ac=178.0,
        yield_prior_year_bu_ac=183.1,
        planting_delayed=True,
        drought_index=True,
        yield_forecast_down=True,
    )
    nasdaq = CornNASDAQSnapshot(
        target_date=target,
        settle_cents_per_bushel=540.0,
        rolling_20d_avg_cents=520.0,
        price_up=True,
    )

    record = CornPipeline.build_evidence_record(nass, nasdaq)

    assert record.timestamp.date() == date(2026, 5, 17)
    assert record.timestamp.tzinfo is not None
    assert "iso-week-ending:2026-05-17" in record.source_ref


def test_corn_scheduler_suppresses_duplicate_week_state():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = CornV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    variables = corn_variables()

    def record_for(day: date) -> EvidenceRecord:
        week_end = latest_week_ending_on_or_before(day)
        return EvidenceRecord(
            timestamp=datetime(week_end.year, week_end.month, week_end.day, tzinfo=timezone.utc),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=variables["PlantingDelayed"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["DroughtIndex"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["YieldForecastDown"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["CornPriceUp"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.SOFT_OBSERVED,
                    probabilities={True: 0.1, False: 0.9},
                ),
            ],
            source_type=SourceType.API,
            source_ref=f"test-week@{week_end}",
        )

    class Pipeline:
        async def fetch_evidence(self, target_date: date) -> EvidenceRecord:
            return record_for(target_date)

    from src.domains.corn_v1.scheduler import IngestionScheduler

    scheduler = IngestionScheduler(engine, Pipeline(), backfill_days=0)
    asyncio.run(scheduler.run_once(date(2026, 5, 20)))
    asyncio.run(scheduler.run_once(date(2026, 5, 21)))

    assert engine.evidence_store.count("corn-v1") == 1


def test_api_agriculture_backfill_steps_weekly(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    seen_dates: list[date] = []

    async def fake_fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        assert domain_key == "zc"
        assert target_date.weekday() == 6
        seen_dates.append(target_date)
        variables = corn_variables()
        price_up = len(seen_dates) % 2 == 1
        return EvidenceRecord(
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=variables["PlantingDelayed"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["DroughtIndex"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["YieldForecastDown"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                    confidence=0.0,
                ),
                ObservedAssignment(
                    variable_id=variables["CornPriceUp"].variable_id,
                    observed_value=price_up,
                    missingness=MissingnessType.OBSERVED,
                ),
            ],
            source_type=SourceType.API,
            source_ref=f"weekly-test@{target_date}",
        )

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch)

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/backfill?domain=zc&days=15")

    assert response.status_code == 200
    assert len(seen_dates) <= 3
    assert len(seen_dates) >= 2
    assert seen_dates == sorted(set(seen_dates))


def test_evidence_geometry_endpoint_exposes_weekly_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as client:
        body = client.get("/v1/debug/evidence-geometry?domain=zc").json()

    assert "cadence_detected" in body
    assert "weekly_compression_ratio" in body
    assert "effective_state_density" in body
    assert "effective_transitions_per_month" in body
    assert "variable_id_match_ratio" in body
    assert "variable_id_mismatch_count" in body


def test_ng_scheduler_backfill_dates_remain_daily(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    seen_dates: list[date] = []

    async def fake_fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        assert domain_key == "ng"
        seen_dates.append(target_date)
        variables = NaturalGasV1().initial_candidates()[0].variables
        return EvidenceRecord(
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=[
                ObservedAssignment(variable_id=variable.variable_id, observed_value=True)
                for variable in variables
            ],
            source_type=SourceType.API,
            source_ref=f"ng-daily@{target_date}",
        )

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch)

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/backfill?domain=ng&days=3")

    assert response.status_code == 200
    assert len(seen_dates) == 3
    assert [(right - left).days for left, right in zip(seen_dates, seen_dates[1:])] == [1, 1]
