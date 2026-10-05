"""
G2 — TEST-L3-03 through the engine facade (REFACTOR_SPEC §7 Phase 0.3).

tests/level3 checks the same scenario on a hand-wired service stack, which
would not notice a change inside ProbabilisticOntologyEngine.learn. This goes
through the facade and uses SPEC §20.6's bound: detected within 200 records.
"""
from __future__ import annotations

from src.domains.test_domain_v1.domain import T_STAR_EDGES, TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

DOMAIN_ID = "test-domain-v1"
BATCH = 30
DETECTION_BOUND = 200


def test_g2_paradigm_shift_detected_within_200_records_via_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)

    for _ in range(300 // BATCH):
        engine.learn(gen.sample(BATCH))
    assert engine.get_population().dominant().edge_structure_signature() == T_STAR_EDGES
    shifts_before = engine.population_status()["paradigm_shift_count"]

    gen.switch_regime("T_alt")
    seen = 0
    detected_at = None
    while seen < DETECTION_BOUND:
        engine.learn(gen.sample(BATCH))
        seen += BATCH
        dom = engine.get_population().dominant()
        if dom.edge_structure_signature() != T_STAR_EDGES and ("A", "D") in dom.edge_structure_signature():
            detected_at = seen
            break

    assert detected_at is not None, f"no shift to an A->D structure within {DETECTION_BOUND} records"
    assert engine.population_status()["paradigm_shift_count"] > shifts_before
