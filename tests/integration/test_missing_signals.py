"""
REFACTOR_SPEC D10 / B9: a variable whose inputs are unavailable is recorded as
MISSING, not as a 50/50 observation; with no inputs at all there is no record.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.domains.sf_urban_v1.ingestion.fred_client import FREDObservation
from src.domains.sf_urban_v1.ingestion.pipeline import SFUrbanPipeline, compute_snapshot
from src.engine.model.errors import EvidenceUnavailable
from src.engine.schemas import MissingnessType

TARGET = date(2026, 3, 1)
SFGOV_EMPTY = {"permits": [], "incidents": [], "business_openings": [], "business_closures": []}


def _monthly(series_id: str) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=TARGET - timedelta(days=30 * i), value=100.0 + (i % 5) - 0.3 * i, series_id=series_id)
        for i in range(30)
    ]


def test_unavailable_inputs_become_missing_assignments():
    fred = {sid: _monthly(sid) for sid in ("SANF806INFO", "SANF806LEIH", "SANF806NA")}
    record = SFUrbanPipeline.build_evidence_record(compute_snapshot(SFGOV_EMPTY, fred, TARGET))
    by_kind: dict[str, int] = {}
    for a in record.observed_assignments:
        by_kind[a.missingness.value] = by_kind.get(a.missingness.value, 0) + 1
        if a.missingness == MissingnessType.MISSING:
            assert a.probabilities is None and a.observed_value is None
    # The five SF Open Data variables had no input; the three FRED ones did.
    assert by_kind == {"OBSERVED": 3, "MISSING": 5}


def test_no_input_at_all_is_not_recorded():
    snapshot = compute_snapshot(SFGOV_EMPTY, {}, TARGET)
    with pytest.raises(EvidenceUnavailable):
        SFUrbanPipeline.build_evidence_record(snapshot)


def test_engine_learns_and_restores_records_with_missing_variables(tmp_path):
    import math

    from src.domains.sf_urban_v1.domain import SFUrbanV1
    from src.engine.engine import ProbabilisticOntologyEngine

    fred = {sid: _monthly(sid) for sid in ("SANF806INFO", "SANF806LEIH", "SANF806NA")}
    db = str(tmp_path / "sf.db")

    def engine():
        e = ProbabilisticOntologyEngine(db_path=db)
        e.register_domain(SFUrbanV1())
        e.activate_domain("sf-urban-v1")
        return e

    first = engine()
    for weeks in range(4):
        day = TARGET + timedelta(days=7 * weeks)
        record = SFUrbanPipeline.build_evidence_record(compute_snapshot(SFGOV_EMPTY, fred, day))
        first.ingest(record)
        first.learn([record])
    dom = first.get_population().dominant()
    assert dom.evidence_count == 4 and math.isfinite(dom.log_score)

    stored = engine().evidence_store.load_all("sf-urban-v1")
    assert sum(a.missingness == MissingnessType.MISSING for r in stored for a in r.observed_assignments) == 20
