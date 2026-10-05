"""
G3 — restart round-trip (REFACTOR_SPEC §7 Phase 0.3).

Learns soft evidence against an on-disk database, rebuilds the engine on the
same file, and snapshots the state before and after.

This deliberately pins today's BROKEN behaviour (REFACTOR_SPEC B1): variants,
pruning and generation are lost on restart, and soft-evidence keys come back
as strings so restored scores are wrong. Phase 3 fixes it and replaces the
snapshot assertion with ``before == after``.
"""
from __future__ import annotations

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

from .probe import population_state, to_soft
from .snapshot import assert_matches_snapshot

DOMAIN_ID = "test-domain-v1"


def _engine(db_path: str) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def test_g3_restart_roundtrip_matches_golden(tmp_path):
    db = str(tmp_path / "g3.db")
    engine = _engine(db)
    gen = SyntheticDataGenerator(graph="T*", random_seed=7)
    for _ in range(10):
        records = [to_soft(r) for r in gen.sample(30)]
        engine.ingest_batch(records)
        engine.learn(records)
    before = population_state(engine, DOMAIN_ID, detail=True)

    restarted = _engine(db)
    after = population_state(restarted, DOMAIN_ID, detail=True)

    assert_matches_snapshot("g3_restart_roundtrip", {"before": before, "after": after})
