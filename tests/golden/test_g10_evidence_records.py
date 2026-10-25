"""
G10 — evidence record construction per domain (REFACTOR_SPEC 4.5b).

Builds each weekly pipeline's EvidenceRecord from one fixed, fully populated
snapshot and pins the result (assignments, levels, confidences,
timestamp, source_ref), so sharing the record-building code can be checked
against today's per-domain copies.
"""
from __future__ import annotations

import importlib
from datetime import date

import pytest

from .snapshot import assert_matches_snapshot

PIPELINES = {
    "macro_regime_v1": "MacroRegime",
    "ai_regime_v1": "AIRegime",
    "sovereign_debt_v1": "SovereignDebt",
    "credit_cycle_v1": "CreditCycle",
    "energy_regime_v1": "EnergyRegime",
    "labor_market_v1": "LaborMarket",
    "crypto_regime_v1": "CryptoRegime",
    "geopolitics_v1": "Geopolitics",
    "sf_urban_v1": "SFUrban",
}
TARGET = date(2026, 3, 1)


def _snapshot(module, prefix: str, variable_names: list[str]):
    """Every variable with a signal, spread from -1.5 to +1.5 so each level
    (D25) appears, and a confidence."""
    snap = getattr(module, f"{prefix}Snapshot")(target_date=TARGET)
    snap.signals = {name: round(-1.5 + 3.0 * ((i * 37) % 100) / 100, 4) for i, name in enumerate(variable_names)}
    snap.confidence = {name: round(0.5 + 0.05 * (i % 10), 2) for i, name in enumerate(variable_names)}
    return snap


@pytest.mark.parametrize("domain", sorted(PIPELINES))
def test_g10_evidence_record_matches_golden(domain):
    pipeline = importlib.import_module(f"src.domains.{domain}.ingestion.pipeline")
    variables = importlib.import_module(f"src.domains.{domain}.domain").get_variables()
    id_to_name = {v.variable_id: name for name, v in variables.items()}
    prefix = PIPELINES[domain]
    record = getattr(pipeline, f"{prefix}Pipeline").build_evidence_record(
        _snapshot(pipeline, prefix, list(variables))
    )
    assert_matches_snapshot(f"g10_record_{domain}", {
        # The snapshot helper blanks ISO timestamps; keep the parts that matter.
        "date": str(record.timestamp.date()),
        "time_and_tz": [str(record.timestamp.time()), str(record.timestamp.tzinfo)],
        "source_type": record.source_type.value,
        "source_ref": record.source_ref,
        "confidence": record.confidence,
        "assignments": [
            [id_to_name[a.variable_id], a.observed_value, a.missingness.value, a.confidence,
             sorted([str(k), p] for k, p in (a.probabilities or {}).items())]
            for a in record.observed_assignments
        ],
    })
