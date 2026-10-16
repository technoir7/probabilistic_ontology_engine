"""
REFACTOR_SPEC 3.2 / B6: one learning cycle is one transaction. If any part
fails, none of that cycle's scores, CPTs or population rows are written, and
the failure propagates (a failed shift-event write used to be logged and
skipped, silently losing the event).
"""
from __future__ import annotations

import sqlite3

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine


def _snapshot(path) -> dict:
    conn = sqlite3.connect(path)
    out = {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("candidate_scores", "ontology_candidates", "ontology_populations", "parameters", "paradigm_shifts")
    }
    conn.close()
    return out


def test_a_failed_cycle_writes_nothing(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    engine = ProbabilisticOntologyEngine(db_path=path)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    engine.learn(gen.sample(30))
    before = _snapshot(path)

    def fail(*_args, **_kwargs):
        raise RuntimeError("disk full")

    # Fails after every candidate has been scored and written.
    monkeypatch.setattr(engine.population_manager, "end_cycle", fail)
    with pytest.raises(RuntimeError, match="disk full"):
        engine.learn(gen.sample(30))

    assert _snapshot(path) == before


def test_a_failed_shift_event_write_fails_the_cycle(tmp_path, monkeypatch):
    engine = ProbabilisticOntologyEngine(db_path=str(tmp_path / "x.db"))
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    for _ in range(10):
        engine.learn(gen.sample(30))

    def fail(**_kwargs):
        raise RuntimeError("cannot write shift")

    monkeypatch.setattr(engine.population_store, "append_shift_event", fail)
    gen.switch_regime("T_alt")
    with pytest.raises(RuntimeError, match="cannot write shift"):
        for _ in range(10):  # G2: the shift happens within the first batches
            engine.learn(gen.sample(30))
