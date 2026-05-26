from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.domains.natural_gas_v1.domain import get_variables
from src.engine.api import app as api_app
from src.engine.schemas import (
    DomainType,
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    Variable,
)
from src.engine.services.evidence_diagnostics import build_entropy_diagnostics


@pytest.fixture
def debug_variables() -> list[Variable]:
    return [
        Variable(name="A", domain_type=DomainType.BOOLEAN, support=[True, False]),
        Variable(name="B", domain_type=DomainType.BOOLEAN, support=[True, False]),
        Variable(name="C", domain_type=DomainType.BOOLEAN, support=[True, False]),
    ]


def _record(
    variables: list[Variable],
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
    return EvidenceRecord(observed_assignments=assignments)


def test_entropy_uses_observed_values_only(debug_variables):
    records = [
        _record(debug_variables, {"A": True}),
        _record(debug_variables, {"A": True}),
        _record(debug_variables, {"A": False}),
        _record(debug_variables, {"A": False}, missing={"A"}),
    ]

    diagnostics = build_entropy_diagnostics(records, debug_variables)

    assert diagnostics["variables"]["A"]["value_counts"] == {"False": 1, "True": 2}
    assert diagnostics["variables"]["A"]["observed_count"] == 3
    assert diagnostics["variables"]["A"]["missing_count"] == 1
    assert diagnostics["variables"]["A"]["entropy"] == pytest.approx(0.918295834)


def test_unique_patterns_count_missing_slots(debug_variables):
    records = [
        _record(debug_variables, {"A": True, "B": False}),
        _record(debug_variables, {"A": True, "B": False}),
        _record(debug_variables, {"A": False}),
    ]

    diagnostics = build_entropy_diagnostics(records, debug_variables)

    assert diagnostics["unique_observed_patterns"] == [
        {"pattern": {"A": True, "B": False, "C": None}, "count": 2},
        {"pattern": {"A": False, "B": None, "C": None}, "count": 1},
    ]


def test_pairwise_mutual_information_uses_joint_observed_rows(debug_variables):
    records = [
        _record(debug_variables, {"A": True, "B": True, "C": True}),
        _record(debug_variables, {"A": True, "B": True, "C": False}),
        _record(debug_variables, {"A": False, "B": False, "C": True}),
        _record(debug_variables, {"A": False, "B": False, "C": False}),
        _record(debug_variables, {"A": True, "B": False}, missing={"B"}),
    ]

    diagnostics = build_entropy_diagnostics(records, debug_variables)
    mi_by_pair = {
        (item["variable_x"], item["variable_y"]): item
        for item in diagnostics["pairwise_mutual_information"]
    }

    assert mi_by_pair[("A", "B")]["joint_observed_count"] == 4
    assert mi_by_pair[("A", "B")]["mutual_information"] == pytest.approx(1.0)
    assert mi_by_pair[("A", "C")]["mutual_information"] == pytest.approx(0.0)


def test_debug_entropy_route_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))

    with TestClient(api_app.app) as client:
        engine = api_app.app.state.engines["ng"]
        variables = get_variables()
        engine.ingest(EvidenceRecord(
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

        response = client.get("/v1/debug/entropy?domain=ng")

    assert response.status_code == 200
    body = response.json()
    assert body["domain"] == "Natural Gas"
    assert body["domain_key"] == "ng"
    assert body["domain_module_id"] == "natural-gas-v1"
    assert body["total_evidence_rows"] == 1
    assert set(body["variables"]) == {
        "TempAnom",
        "HeatingDem",
        "StorageDraw",
        "PriceUp",
    }
    assert body["variables"]["StorageDraw"]["observed_count"] == 0
    assert body["variables"]["StorageDraw"]["missing_count"] == 1
    assert body["unique_observed_patterns"] == [
        {
            "pattern": {
                "TempAnom": True,
                "HeatingDem": True,
                "StorageDraw": None,
                "PriceUp": True,
            },
            "count": 1,
        }
    ]
    assert len(body["pairwise_mutual_information"]) == 6
