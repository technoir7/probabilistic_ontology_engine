"""
G1 — engine replay golden (REFACTOR_SPEC §7 Phase 0.3; SPEC TEST-INT-03).

Drives the engine facade through a regime switch and pins, batch by batch,
everything the population believes. Two scenarios cover both learning paths:

* ``hard``: fully observed records (fast exact path), T* then T_alt.
* ``soft``: SOFT_OBSERVED records with 20% MISSING (mean-field path), which is
  what every live domain sends.
"""
from __future__ import annotations

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import PopulationAggregation

from .probe import cpt_table, marginals, population_state, to_soft
from .snapshot import assert_matches_snapshot

DOMAIN_ID = "test-domain-v1"
BATCH = 30

SCENARIOS = {
    # name: (records per phase, missing_rate, soft)
    "hard": (300, 0.0, False),
    "soft": (180, 0.2, True),
}


def run_scenario(name: str) -> dict:
    per_phase, missing_rate, soft = SCENARIOS[name]
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    gen = SyntheticDataGenerator(graph="T*", random_seed=42, missing_rate=missing_rate)

    batches = []
    phase_end = {}
    for phase, graph in (("T*", "T*"), ("T_alt", "T_alt")):
        gen.switch_regime(graph)
        for _ in range(per_phase // BATCH):
            records = gen.sample(BATCH)
            if soft:
                records = [to_soft(r) for r in records]
            engine.ingest_batch(records)
            engine.learn(records)
            batches.append(population_state(engine, DOMAIN_ID))
        pop = engine.get_population(DOMAIN_ID)
        phase_end[phase] = {
            "population": population_state(engine, DOMAIN_ID, detail=True),
            "dominant_cpts": cpt_table(engine, pop.dominant()),
            "marginals": {
                agg.value: marginals(engine, DOMAIN_ID, agg) for agg in PopulationAggregation
            },
        }
    return {"batches": batches, "phase_end": phase_end}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_g1_engine_replay_matches_golden(scenario):
    assert_matches_snapshot(f"g1_engine_replay_{scenario}", run_scenario(scenario))


def test_g1_engine_replay_is_reproducible():
    """SPEC TEST-INT-03: same seed, same inputs → identical population history."""
    from .snapshot import normalize

    assert normalize(run_scenario("soft")) == normalize(run_scenario("soft"))
