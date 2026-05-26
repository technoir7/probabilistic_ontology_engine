from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.domains.natural_gas_v1.domain import get_variables
from src.engine.api import app as api_app
from src.engine.schemas import (
    DomainType,
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
    Variable,
)
from src.engine.services.evidence_geometry import build_evidence_geometry_diagnostics


@pytest.fixture
def geometry_variables() -> list[Variable]:
    return [
        Variable(name="A", domain_type=DomainType.BOOLEAN, support=[True, False]),
        Variable(name="B", domain_type=DomainType.BOOLEAN, support=[True, False]),
        Variable(name="C", domain_type=DomainType.BOOLEAN, support=[True, False]),
    ]


def _record(
    variables: list[Variable],
    timestamp: datetime,
    values: dict[str, bool],
    missing: set[str] | None = None,
) -> EvidenceRecord:
    missing = missing or set()
    by_name = {v.name: v for v in variables}
    assignments = []
    for name, value in values.items():
        assignments.append(ObservedAssignment(
            variable_id=by_name[name].variable_id,
            observed_value=value,
            missingness=(
                MissingnessType.MISSING
                if name in missing
                else MissingnessType.OBSERVED
            ),
        ))
    return EvidenceRecord(
        timestamp=timestamp,
        observed_assignments=assignments,
        source_type=SourceType.SIMULATION,
    )


def test_evidence_geometry_entropy_and_transitions(geometry_variables):
    records = [
        _record(geometry_variables, datetime(2026, 1, 1, tzinfo=timezone.utc), {"A": True}),
        _record(geometry_variables, datetime(2026, 1, 2, tzinfo=timezone.utc), {"A": True}),
        _record(geometry_variables, datetime(2026, 1, 3, tzinfo=timezone.utc), {"A": False}),
        _record(
            geometry_variables,
            datetime(2026, 1, 4, tzinfo=timezone.utc),
            {"A": False},
            missing={"A"},
        ),
    ]

    diagnostics = build_evidence_geometry_diagnostics(records, geometry_variables)

    assert diagnostics["variables"]["A"]["observed_count"] == 3
    assert diagnostics["variables"]["A"]["missing_count"] == 1
    assert diagnostics["variables"]["A"]["observed_ratio"] == pytest.approx(0.75)
    assert diagnostics["variables"]["A"]["shannon_entropy"] == pytest.approx(0.918295834)
    assert diagnostics["variables"]["A"]["transition_count"] == 1
    assert diagnostics["variables"]["A"]["unique_value_count"] == 2
    assert diagnostics["variables"]["A"]["value_distribution"] == {"False": 1, "True": 2}


def test_evidence_geometry_unique_pattern_counting(geometry_variables):
    records = [
        _record(
            geometry_variables,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            {"A": True, "B": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            {"A": True, "B": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 3, tzinfo=timezone.utc),
            {"A": False},
        ),
    ]

    diagnostics = build_evidence_geometry_diagnostics(records, geometry_variables)

    assert diagnostics["unique_observed_assignment_patterns"] == 2
    assert diagnostics["top_10_most_common_assignment_patterns"] == [
        {"pattern": {"A": True, "B": False, "C": None}, "count": 2},
        {"pattern": {"A": False, "B": None, "C": None}, "count": 1},
    ]


def test_evidence_geometry_mi_matrix_shape(geometry_variables):
    records = [
        _record(
            geometry_variables,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            {"A": True, "B": True, "C": True},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            {"A": True, "B": True, "C": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 3, tzinfo=timezone.utc),
            {"A": False, "B": False, "C": True},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 4, tzinfo=timezone.utc),
            {"A": False, "B": False, "C": False},
        ),
    ]

    diagnostics = build_evidence_geometry_diagnostics(records, geometry_variables)
    matrix = diagnostics["pairwise_mutual_information_matrix"]

    assert set(matrix) == {"A", "B", "C"}
    assert all(set(row) == {"A", "B", "C"} for row in matrix.values())
    assert matrix["A"]["B"] == pytest.approx(1.0)
    assert matrix["B"]["A"] == pytest.approx(1.0)
    assert matrix["A"]["C"] == pytest.approx(0.0)
    assert diagnostics["highest_mi_variable_pair"] == {
        "variable_x": "A",
        "variable_y": "B",
        "joint_observed_count": 4,
        "mutual_information": pytest.approx(1.0),
    }


def test_evidence_geometry_weekly_aggregation_and_compression(geometry_variables):
    records = [
        _record(
            geometry_variables,
            datetime(2026, 1, 5, tzinfo=timezone.utc),
            {"A": True, "B": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 6, tzinfo=timezone.utc),
            {"A": True, "B": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 7, tzinfo=timezone.utc),
            {"A": False, "B": False},
        ),
        _record(
            geometry_variables,
            datetime(2026, 1, 12, tzinfo=timezone.utc),
            {"A": False, "B": False},
        ),
    ]

    diagnostics = build_evidence_geometry_diagnostics(records, geometry_variables)

    assert diagnostics["daily_state_count"] == 4
    assert diagnostics["daily_unique_state_count"] == 2
    assert diagnostics["weekly_bucket_count"] == 2
    assert diagnostics["weekly_compressed_state_count"] == 3
    assert diagnostics["weekly_unique_state_count"] == 2
    assert diagnostics["daily_transition_count"] == 1
    assert diagnostics["weekly_transition_count"] == 1
    assert diagnostics["compression_ratio_daily_to_weekly"] == pytest.approx(4 / 3)
    assert diagnostics["weekly_aggregation"][0]["daily_state_count"] == 3
    assert diagnostics["weekly_aggregation"][0]["compressed_state_count"] == 2


def test_evidence_geometry_route_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as client:
        engine = api_app.app.state.engines["ng"]
        variables = get_variables()
        engine.ingest(EvidenceRecord(
            timestamp=datetime(2026, 1, 5, tzinfo=timezone.utc),
            observed_assignments=[
                ObservedAssignment(
                    variable_id=variables["TempAnom"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["HeatingDem"].variable_id,
                    observed_value=True,
                ),
                ObservedAssignment(
                    variable_id=variables["StorageDraw"].variable_id,
                    observed_value=False,
                    missingness=MissingnessType.MISSING,
                ),
                ObservedAssignment(
                    variable_id=variables["PriceUp"].variable_id,
                    observed_value=True,
                ),
            ],
        ))

        response = client.get("/v1/debug/evidence-geometry?domain=ng")

    assert response.status_code == 200
    body = response.json()
    assert body["domain"] == "Natural Gas"
    assert body["domain_key"] == "ng"
    assert body["domain_module_id"] == "natural-gas-v1"
    assert body["total_evidence_records"] == 1
    assert body["unique_observed_assignment_patterns"] == 1
    assert body["daily_unique_state_count"] == 1
    assert body["weekly_unique_state_count"] == 1
    assert body["compression_ratio_daily_to_weekly"] == 1.0
    assert set(body["variables"]) == {
        "TempAnom",
        "HeatingDem",
        "StorageDraw",
        "PriceUp",
    }
    assert set(body["pairwise_mutual_information_matrix"]) == {
        "TempAnom",
        "HeatingDem",
        "StorageDraw",
        "PriceUp",
    }
    assert body["variables"]["StorageDraw"]["observed_count"] == 0
    assert body["weekly_aggregation"][0]["iso_year"] == 2026
    assert body["weekly_aggregation"][0]["compressed_state_count"] == 1
