"""The population begins with no hypotheses and forms them from the evidence
(REFACTOR_SPEC D24). Blind variation still revises what it forms."""
import random

from src.domains.test_domain_v1.domain import _var_list, TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.services.learning import LearningService
from src.engine.services.population_manager import PopulationManager
from src.engine.services.programmes import UNCONNECTED, unconnected
from src.engine.services.synthesis import connections
from src.engine.stores.parameter_store import ParameterStore
from src.engine.stores.population_store import PopulationStore

DOMAIN = "test-domain-v1"
ALL_PAIRS = {(a, b) for a in "ABCDE" for b in "ABCDE" if a != b}


def manager(start, max_pop=10):
    ps = ParameterStore()
    LearningService(ps).initialize_candidate(start)
    pm = PopulationManager(parameter_store=ps, population_store=PopulationStore(":memory:"), rng=random.Random(0))
    pm.initialize(DOMAIN, [start], max_population_size=max_pop, admissible_edges=ALL_PAIRS)
    return pm


def evidence(n=200):
    return SyntheticDataGenerator(graph="T*", random_seed=0).sample(n)


def test_the_start_holds_no_hypothesis():
    start = unconnected(DOMAIN, _var_list())
    assert start.edges == [] and start.lineage == UNCONNECTED


def test_a_prompted_connection_comes_before_blind_variation():
    start = unconnected(DOMAIN, _var_list())
    pm = manager(start)
    recent = evidence()
    new = pm.introduce_variants(DOMAIN, recent)
    best = connections(start, recent, ALL_PAIRS)[0]
    assert new[0].edge_structure_signature() == {(best.parent, best.child)}
    assert new[0].description == f"prompted_add_{best.parent}->{best.child}"


def test_a_connection_formed_from_nothing_founds_a_programme():
    pm = manager(unconnected(DOMAIN, _var_list()))
    prompted, = pm.introduce_variants(DOMAIN, evidence())
    (p, c), = prompted.edge_structure_signature()
    assert prompted.lineage == "–".join(sorted((p, c)))


def test_blind_variation_revises_hypotheses_but_never_makes_one_from_nothing():
    # A random connection of the unconnected would be a hypothesis from nowhere.
    pm = manager(unconnected(DOMAIN, _var_list()))
    assert pm.introduce_variants(DOMAIN) == []


def test_a_connection_formed_within_a_programme_revises_it():
    pm = manager(unconnected(DOMAIN, _var_list()), max_pop=2)
    first, = pm.introduce_variants(DOMAIN, evidence())
    pm.get_population(DOMAIN).candidates.remove(pm.get_population(DOMAIN).candidates[0])
    LearningService(pm.ps).initialize_candidate(first)
    second, = pm.introduce_variants(DOMAIN, evidence())
    assert second.description.startswith("prompted_add_")
    assert second.lineage == first.lineage


def test_without_evidence_there_is_only_blind_variation():
    from src.domains.test_domain_v1.domain import make_null_candidate
    held = make_null_candidate(DOMAIN)
    held.lineage = "C–E"
    pm = manager(held)
    new = pm.introduce_variants(DOMAIN)
    assert new and all(v.description.startswith("variant_") for v in new)


def test_the_engine_starts_every_domain_with_no_hypotheses():
    from src.engine.runtime.registry import REGISTRY
    for domain in (r.build_domain() for r in REGISTRY):
        engine = ProbabilisticOntologyEngine(db_path=":memory:")
        engine.register_domain(domain)
        candidates = engine.get_population(domain.module_id()).candidates
        assert [(c.edges, c.lineage) for c in candidates] == [([], UNCONNECTED)], domain.module_id()


def test_the_engine_forms_hypotheses_from_what_it_learns():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN)
    gen = SyntheticDataGenerator(graph="T*", random_seed=0)
    engine.learn(gen.sample(30))
    assert any(c.description.startswith("prompted_add_") for c in engine.get_population().candidates)


def test_a_new_connection_is_learned_from_the_evidence_remembered():
    # Synthesis of reproduction: the engine re-reads what it remembers under
    # the new connection, rather than starting that table from nothing.
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN)
    engine.learn(SyntheticDataGenerator(graph="T*", random_seed=0).sample(30))
    pop = engine.get_population()
    [prompted] = [c for c in pop.candidates if c.description.startswith("prompted_add_")]
    (parent, child), = prompted.edge_structure_signature()
    cpt = engine.parameter_store.get(prompted.candidate_id, child)
    assert cpt.parents == [parent] and cpt.total_count() == 30
    # Variables the connection did not touch keep what the parent learned.
    untouched = next(v.name for v in prompted.variables if v.name not in (parent, child))
    assert engine.parameter_store.get(prompted.candidate_id, untouched).total_count() == 30


def test_the_evidence_is_heard_before_blind_variation():
    # Each programme's best first takes the change the evidence most prompts,
    # then the evidence may found a rival to the leader (D26); blind variants
    # fill the places left.
    from src.domains.test_domain_v1.domain import make_null_candidate
    held = make_null_candidate(DOMAIN)
    held.lineage = "C–E"
    pm = manager(held, max_pop=4)
    recent = evidence()
    new = pm.introduce_variants(DOMAIN, recent)
    best = connections(held, recent, ALL_PAIRS)[0]
    assert new[0].description == f"prompted_add_{best.parent}->{best.child}"
    assert len(new) == 3 and new[1].description.startswith("rival_") and new[2].description.startswith("variant_")
