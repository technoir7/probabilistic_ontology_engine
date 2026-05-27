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
from src.domains.sovereign_debt_v1.domain import SovereignDebtV1, get_variables as sd_variables
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
    """stable_variable_id is deterministic and module-scoped."""
    assert stable_variable_id("sovereign-debt-v1", "USYieldSpiking") == stable_variable_id(
        "sovereign-debt-v1", "USYieldSpiking"
    )
    assert stable_variable_id("sovereign-debt-v1", "USYieldSpiking") != stable_variable_id(
        "credit-cycle-v1", "USYieldSpiking"
    )
    assert sd_variables()["USYieldSpiking"].variable_id == stable_variable_id(
        "sovereign-debt-v1", "USYieldSpiking"
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


def test_api_sovereign_debt_backfill_steps_weekly(monkeypatch, tmp_path):
    """Backfill for 'sd' produces only Sunday targets, step by ISO week."""
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    seen_dates: list[date] = []

    variables = sd_variables()

    async def fake_fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        assert domain_key == "sd"
        assert target_date.weekday() == 6  # Sunday
        seen_dates.append(target_date)
        return EvidenceRecord(
            timestamp=datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                tzinfo=timezone.utc,
            ),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=v.variable_id,
                    observed_value=True,
                    missingness=MissingnessType.SOFT_OBSERVED,
                    probabilities={True: 0.6, False: 0.4},
                )
                for v in variables.values()
            ],
            source_type=SourceType.API,
            source_ref=f"weekly-test@{target_date}",
        )

    monkeypatch.setattr(api_app, "_fetch_evidence_record", fake_fetch)

    with TestClient(api_app.app) as client:
        response = client.post("/v1/ingest/backfill?domain=sd&days=15")

    assert response.status_code == 200
    assert len(seen_dates) <= 3
    assert len(seen_dates) >= 2
    assert seen_dates == sorted(set(seen_dates))


def test_evidence_geometry_endpoint_exposes_weekly_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as client:
        body = client.get("/v1/debug/evidence-geometry?domain=sd").json()

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
