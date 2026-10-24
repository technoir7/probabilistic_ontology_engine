"""
G2 — TEST-L3-03 through the engine facade, over many seeds (REFACTOR_SPEC D14, D24).

tests/level3 checks the same scenario on a hand-wired service stack given the
rival structures, which would not notice a change inside
ProbabilisticOntologyEngine.learn. This goes through the facade, where the
engine starts with no hypotheses and forms its own from the evidence (D24),
and uses SPEC §20.6's bound: a shift detected within 200 records.

One seed passing says little: a single-seed test measured the seed, not the
engine. A run succeeds when, after 300 records of T*, the leader holds the
B–D dependence and not A–D, and within 200 records of the switch to T_alt a
leader holding A–D has taken over, with a shift logged. Dependences are
compared without direction: the evidence alone often cannot orient them
(Verma and Pearl 1990).
"""
from __future__ import annotations

import pytest

from src.domains.test_domain_v1.domain import T_STAR_EDGES, TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

DOMAIN_ID = "test-domain-v1"
BATCH = 30
DETECTION_BOUND = 200
SEEDS = range(20)
# The 80% bar from REFACTOR_SPEC D14. From nothing, seeds 0-19 passed 19 when D24 landed.
REQUIRED = 16
B_D, A_D = frozenset("BD"), frozenset("AD")


def _dependences(engine) -> set[frozenset[str]]:
    return {frozenset(e) for e in engine.get_population().dominant().edge_structure_signature()}


def _learned_from_nothing(seed: int) -> tuple[ProbabilisticOntologyEngine, SyntheticDataGenerator]:
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    gen = SyntheticDataGenerator(graph="T*", random_seed=seed)
    for _ in range(300 // BATCH):
        engine.learn(gen.sample(BATCH))
    return engine, gen


def _succeeds(seed: int) -> bool:
    engine, gen = _learned_from_nothing(seed)
    held = _dependences(engine)
    if B_D not in held or A_D in held:
        return False
    shifts_before = engine.population_status()["paradigm_shift_count"]

    gen.switch_regime("T_alt")
    for _ in range(DETECTION_BOUND // BATCH):
        engine.learn(gen.sample(BATCH))
        if A_D in _dependences(engine):
            return engine.population_status()["paradigm_shift_count"] > shifts_before
    return False


def test_g2_paradigm_shift_detected_on_most_seeds():
    successes = sum(_succeeds(seed) for seed in SEEDS)
    assert successes >= REQUIRED, f"{successes}/{len(SEEDS)} seeds, need {REQUIRED}"


@pytest.mark.xfail(strict=True, reason=(
    "Known limit of starting from nothing (D24): B–C carries about 0.04 nats a "
    "record, too little to tell from chance within the score window's memory "
    "(SCORE_HALF_LIFE_RECORDS), so the full structure is rarely found in 300 records."))
def test_g2_the_whole_true_structure_is_found_from_nothing():
    found = sum({frozenset(e) for e in T_STAR_EDGES} <= _dependences(_learned_from_nothing(seed)[0])
                for seed in SEEDS)
    assert found >= REQUIRED, f"{found}/{len(SEEDS)} seeds, need {REQUIRED}"
