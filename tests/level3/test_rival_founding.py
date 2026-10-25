"""A rival can always be founded (REFACTOR_SPEC D26).

Persistence, a concept following its own last value, is common ground that
every worldview needs; it founds no programme. At any time, a connection
the recent evidence supports and the leader lacks founds a rival: the
leader's structure without its hard core, with the new connection in its
place. It shares the leader's auxiliaries, denies its core and asserts its
own, and starts level with it, so it is judged only on what comes after (a
fair trial). Founding stops while half the places hold programmes, so
programmes keep room to revise themselves."""
import random
from uuid import uuid4

from src.domains.macro_regime_v1.domain import MacroRegimeV1
from src.domains.test_domain_v1.domain import _var_list
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import _admissible_edges
from src.engine.model.scoring import candidate_score, dominant, log_bayes_factor
from src.engine.schemas import DependencyEdge, DependencyKind
from src.engine.services.learning import LearningService
from src.engine.services.population_manager import PopulationManager
from src.engine.services.programmes import UNCONNECTED, programme_name, unconnected
from src.engine.stores.parameter_store import ParameterStore
from src.engine.stores.population_store import PopulationStore

DOMAIN = "test-domain-v1"
ALL_PAIRS = {(a, b) for a in "ABCDE" for b in "ABCDE" if a != b}


def scored(candidate, per_record, n=150.0):
    candidate.window_log_score, candidate.window_evidence = per_record * n, n
    candidate.log_score, candidate.evidence_count = per_record * n, int(n)
    return candidate


def with_edges(start, pairs, lineage):
    v = {x.name: x for x in start.variables}
    edges = [DependencyEdge(edge_id=uuid4(), parent_variable_id=v[p].variable_id, child_variable_id=v[c].variable_id,
                            dependency_kind=DependencyKind.DIRECTED_CONDITIONAL) for p, c in pairs]
    return start.model_copy(update={"candidate_id": uuid4(), "edges": edges, "lineage": lineage,
                                    "description": lineage})


def manager(candidates, admissible=ALL_PAIRS, domain=DOMAIN, max_pop=10):
    ps = ParameterStore()
    for c in candidates:
        LearningService(ps).initialize_candidate(c)
    pm = PopulationManager(parameter_store=ps, population_store=PopulationStore(":memory:"), rng=random.Random(0))
    pm.initialize(domain, candidates, max_population_size=max_pop, admissible_edges=admissible)
    return pm


def test_persistence_is_common_ground_and_founds_no_programme():
    from tests.level3.test_temporal_beliefs import persisting_weeks
    from src.engine.model.temporal import lagged
    variables = MacroRegimeV1().variables()
    start = unconnected("macro-regime-v1", variables)
    pm = manager([start], admissible=_admissible_edges(variables), domain="macro-regime-v1")
    new = pm.introduce_variants("macro-regime-v1", lagged(persisting_weeks(80), None, variables))
    prompted = [c for c in new if c.description.startswith("prompted_")]
    (parent, child), = prompted[0].edge_structure_signature()
    assert parent == f"{child}_prev"
    assert prompted[0].lineage == UNCONNECTED


def test_a_rival_replaces_the_leaders_core_with_a_connection_it_lacks_level_with_it():
    start = unconnected(DOMAIN, _var_list())
    leader = scored(with_edges(start, [("B", "D"), ("A", "C")], "B–D"), -3.0)
    pm = manager([leader, scored(start, -3.4)])
    new = pm.introduce_variants(DOMAIN, SyntheticDataGenerator(graph="T*", random_seed=0).sample(200))
    rivals = [c for c in new if c.description.startswith("rival_")]
    assert len(rivals) == 1
    rival = rivals[0]
    assert rival.parent_candidate_id == leader.candidate_id
    added = rival.edge_structure_signature() - leader.edge_structure_signature()
    (p, c), = added
    assert rival.edge_structure_signature() == {("A", "C"), (p, c)}  # B–D, the core, is denied
    assert rival.lineage == programme_name(p, c) not in ("B–D", "A–C")
    assert candidate_score(rival) <= candidate_score(leader)
    assert abs(log_bayes_factor(leader, rival)) < 1e-6
    assert dominant(pm.get_population(DOMAIN).active_candidates()) is leader


def test_no_rival_is_founded_while_half_the_places_hold_programmes():
    # Five programmes on connections T* lacks, so T*'s own would found a rival
    # if there were room.
    start = unconnected(DOMAIN, _var_list())
    pairs = [("A", "B"), ("A", "E"), ("B", "E"), ("A", "D"), ("C", "D")]

    def founded(max_pop):
        programmes = [scored(with_edges(start, [pair], programme_name(*pair)), -3.0 - i / 100)
                      for i, pair in enumerate(pairs)]
        pm = manager(programmes, max_pop=max_pop)
        new = pm.introduce_variants(DOMAIN, SyntheticDataGenerator(graph="T*", random_seed=0).sample(200))
        return [c for c in new if c.description.startswith("rival_")]

    assert founded(max_pop=10) == []      # 5 of 10 places hold programmes
    assert len(founded(max_pop=12)) == 1  # 5 of 12: room for one more
