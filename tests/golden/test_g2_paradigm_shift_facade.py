"""
G2 — TEST-L3-03 through the engine facade, over many seeds (REFACTOR_SPEC D14).

tests/level3 checks the same scenario on a hand-wired service stack, which
would not notice a change inside ProbabilisticOntologyEngine.learn. This goes
through the facade and uses SPEC §20.6's bound: detected within 200 records.

One seed passing says little: on seeds 0-19 the engine succeeded on some and
failed on others, so a single-seed test measured the seed, not the engine. A
run succeeds when T* dominates after 300 T* records and an A->D structure
takes over within 200 records of the switch to T_alt.
"""
from __future__ import annotations

from src.domains.test_domain_v1.domain import T_STAR_EDGES, TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

DOMAIN_ID = "test-domain-v1"
BATCH = 30
DETECTION_BOUND = 200
SEEDS = range(20)
# The 80% bar from REFACTOR_SPEC D14; seeds 0-19 passed 18 when the score window landed.
REQUIRED = 16


def _succeeds(seed: int) -> bool:
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    gen = SyntheticDataGenerator(graph="T*", random_seed=seed)

    for _ in range(300 // BATCH):
        engine.learn(gen.sample(BATCH))
    if engine.get_population().dominant().edge_structure_signature() != T_STAR_EDGES:
        return False
    shifts_before = engine.population_status()["paradigm_shift_count"]

    gen.switch_regime("T_alt")
    for _ in range(DETECTION_BOUND // BATCH):
        engine.learn(gen.sample(BATCH))
        dom = engine.get_population().dominant().edge_structure_signature()
        if dom != T_STAR_EDGES and ("A", "D") in dom:
            return engine.population_status()["paradigm_shift_count"] > shifts_before
    return False


def test_g2_paradigm_shift_detected_on_most_seeds():
    successes = sum(_succeeds(seed) for seed in SEEDS)
    assert successes >= REQUIRED, f"{successes}/{len(SEEDS)} seeds, need {REQUIRED}"
