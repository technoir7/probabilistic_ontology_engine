"""
REFACTOR_SPEC B1a: soft-evidence probabilities must come back from the store
with the variable's own values as keys. Pydantic's JSON mode turned
{True: 0.64} into {"true": 0.64}, so every soft record read back (score
restore on restart, art rebuilds, diagnostics) missed its CPT rows.
"""
from __future__ import annotations

import json
from uuid import uuid4

from src.engine.schemas import EvidenceRecord, MissingnessType, ObservedAssignment
from src.engine.stores.evidence_store import EvidenceStore


def _soft(vid, p):
    return ObservedAssignment(
        variable_id=vid, observed_value=p > 0.5, missingness=MissingnessType.SOFT_OBSERVED,
        probabilities={True: p, False: 1 - p},
    )


def test_soft_probabilities_round_trip_with_boolean_keys():
    store = EvidenceStore(":memory:")
    vid = uuid4()
    store.append(EvidenceRecord(observed_assignments=[_soft(vid, 0.64)]), "d")
    [back] = store.load_all("d")
    assert back.observed_assignments[0].probabilities == {True: 0.64, False: 1 - 0.64}


def test_rows_written_by_the_old_format_are_read_with_boolean_keys():
    store = EvidenceStore(":memory:")
    vid = uuid4()
    legacy = [{
        "variable_id": str(vid), "observed_value": True, "missingness": "SOFT_OBSERVED",
        "confidence": 1.0, "probabilities": {"true": 0.7, "false": 0.3},
    }]
    store._conn.execute(
        "INSERT INTO evidence_records (evidence_id, domain_module, timestamp, source_type, source_ref, confidence, assignments)"
        " VALUES (?, 'd', '2026-01-01T00:00:00', 'API', '', 1.0, ?)",
        (str(uuid4()), json.dumps(legacy)),
    )
    [back] = store.load_all("d")
    assert back.observed_assignments[0].probabilities == {True: 0.7, False: 0.3}
