"""
G3 — restart round-trip (REFACTOR_SPEC §7 Phase 0.3; fixed in 3.3/3.4).

A restart must be invisible: the engine rebuilt on the same database file
holds exactly the population it had, and keeps learning exactly as an engine
that never restarted. Until Phase 3 this test pinned the broken behaviour
(B1: variants, pruning and generation lost; soft-evidence scores wrong).
"""
from __future__ import annotations

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

from .probe import cpt_table, population_state, to_soft
from .snapshot import normalize

DOMAIN_ID = "test-domain-v1"


def _engine(db_path: str) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def _learn(engine, gen, batches: int) -> None:
    for _ in range(batches):
        records = [to_soft(r) for r in gen.sample(30)]
        engine.ingest_batch(records)
        engine.learn(records)


def _state(engine) -> dict:
    pop = engine.get_population(DOMAIN_ID)
    return normalize({
        "population": population_state(engine, DOMAIN_ID, detail=True),
        "cpts": [cpt_table(engine, c) for c in pop.candidates if c.status.value == "ACTIVE"],
    })


def test_g3_restart_preserves_the_population_exactly(tmp_path):
    db = str(tmp_path / "g3.db")
    engine = _engine(db)
    _learn(engine, SyntheticDataGenerator(graph="T*", random_seed=7), 10)
    assert engine.get_population(DOMAIN_ID).generation > 0, "scenario must evolve variants"

    assert _state(_engine(db)) == _state(engine)


def test_g3_learning_continues_after_restart_as_if_uninterrupted(tmp_path):
    uninterrupted = _engine(str(tmp_path / "a.db"))
    _learn(uninterrupted, SyntheticDataGenerator(graph="T*", random_seed=7), 10)

    db = str(tmp_path / "b.db")
    gen = SyntheticDataGenerator(graph="T*", random_seed=7)
    _learn(_engine(db), gen, 5)
    _learn(_engine(db), gen, 5)  # a restart halfway through

    assert _state(_engine(db)) == _state(uninterrupted)
