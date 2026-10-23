"""The engine's random_seed decides how variants mutate (SPEC §2.2:
reproducible given the same evidence sequence and random seed)."""
from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine


def variant_structures(seed: int) -> list[frozenset]:
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=7)
    for _ in range(8):
        engine.learn(gen.sample(30))
    pop = engine.population_manager.get_population("test-domain-v1")
    return [c.edge_structure_signature() for c in pop.candidates if c.generation > 0]


def test_the_same_seed_mutates_the_same_way():
    assert variant_structures(3) == variant_structures(3)


def test_another_seed_mutates_differently():
    assert any(variant_structures(s) != variant_structures(3) for s in (4, 5, 6))
