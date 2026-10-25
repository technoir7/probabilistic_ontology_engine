"""Rival research programmes stay alive until refuted (REFACTOR_SPEC D15):
every candidate carries the programme it belongs to, founded by a connection
the evidence prompted from nothing (D24), and pruning
spares a programme's best candidate unless the evidence for the leader over
it is decisive (a Bayes factor above 100, Jeffreys' scale), so the
population can shift to another worldview rather than only refine one."""
from uuid import uuid4

from src.domains.macro_regime_v1.domain import MacroRegimeV1
from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import CandidateStatus


def engine_for(domain, seed=0):
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    return engine


def test_a_programme_is_founded_from_nothing_and_kept_by_its_descendants():
    engine = engine_for(TestDomainV1())
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    for _ in range(10):
        engine.learn(gen.sample(30))
    pop = engine.population_manager.get_population("test-domain-v1")
    by_id = {c.candidate_id: c for c in pop.candidates}
    founded = 0
    for c in pop.candidates:
        parent = by_id.get(c.parent_candidate_id)
        if parent is None:
            continue
        if parent.lineage == "unconnected" and c.description.startswith("prompted_add_"):
            # From nothing, or from a leader's structure without its core (D27).
            p, ch = c.description.removeprefix("prompted_add_").split("->")
            assert c.lineage == "–".join(sorted((p, ch)))
            founded += not parent.edges
        elif c.description.startswith("rival_"):  # a rival to the leader (D26)
            p, ch = c.description.removeprefix("rival_").split("->")
            assert c.lineage == "–".join(sorted((p, ch)))
        elif c.description.startswith("trial_"):  # the leader's core on trial (D27)
            assert c.lineage == "unconnected"
        else:
            assert c.lineage == parent.lineage
    assert founded >= 1


def scored(candidate, lineage, per_record, n=150.0):
    candidate.lineage = lineage
    candidate.window_log_score, candidate.window_evidence = per_record * n, n
    candidate.evidence_count = int(n)
    return candidate


def manager_with(candidates):
    from src.engine.services.population_manager import PopulationManager
    from src.engine.stores.parameter_store import ParameterStore
    from src.engine.stores.population_store import PopulationStore
    pm = PopulationManager(parameter_store=ParameterStore(), population_store=PopulationStore(":memory:"))
    pm.initialize("test-domain-v1", candidates, max_population_size=10)
    return pm


def seeds():
    from src.domains.test_domain_v1 import domain as d
    return [d.make_tstar_candidate("test-domain-v1"), d.make_talt_candidate("test-domain-v1"),
            d.make_null_candidate("test-domain-v1"), d.make_spurious_1_candidate("test-domain-v1")]


def test_a_rival_short_of_refuted_is_spared():
    a, b, c, d = seeds()
    pm = manager_with([scored(a, "A", -3.00), scored(b, "A", -3.01), scored(c, "B", -3.02), scored(d, "A", -3.03)])
    pruned = pm.prune_low_scorers("test-domain-v1")
    # B trails by 0.02 nats over 150 records: a Bayes factor of e^3, not decisive.
    assert c not in pruned


def test_a_decisively_refuted_rival_can_go():
    a, b, c, d = seeds()
    pm = manager_with([scored(a, "A", -3.00), scored(b, "A", -3.01), scored(c, "B", -3.50), scored(d, "A", -3.02)])
    assert c in pm.prune_low_scorers("test-domain-v1")


def test_the_weakest_of_a_programme_is_still_pruned():
    a, b, c, d = seeds()
    pm = manager_with([scored(a, "A", -3.00), scored(b, "B", -3.01), scored(c, "A", -3.02), scored(d, "A", -3.03)])
    assert d in pm.prune_low_scorers("test-domain-v1")


def test_pruning_still_removes_the_weak():
    engine = engine_for(TestDomainV1())
    pop = engine.population_manager.get_population("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=3)
    for _ in range(40):
        engine.learn(gen.sample(30))
    assert any(c.status == CandidateStatus.PRUNED for c in pop.candidates)


def test_the_programme_survives_a_restart(tmp_path):
    db = str(tmp_path / "x.db")
    engine = ProbabilisticOntologyEngine(db_path=db, random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=4)
    for _ in range(5):
        engine.learn(gen.sample(30))
    before = {c.candidate_id: c.lineage for c in engine.population_manager.get_population("test-domain-v1").active_candidates()}
    again = ProbabilisticOntologyEngine(db_path=db, random_seed=0)
    again.register_domain(TestDomainV1())
    after = {c.candidate_id: c.lineage for c in again.population_manager.get_population("test-domain-v1").active_candidates()}
    assert after == before


def test_programmes_take_turns_to_breed_first():
    """Each breeding round starts with another programme's best, so a rival
    can revise itself rather than be judged unrevised (D16)."""
    from src.engine.services.population_manager import _breeding_order
    a, b, c, d = seeds()
    ranked = [scored(a, "A", -3.0), scored(c, "A", -3.1), scored(b, "B", -3.2), scored(d, "C", -3.3)]
    firsts = [_breeding_order(ranked, turn)[0].lineage for turn in range(6)]
    assert firsts == ["A", "B", "C", "A", "B", "C"]
    assert [x.lineage for x in _breeding_order(ranked, 0)] == ["A", "B", "C", "A"]


def test_with_one_programme_breeding_is_best_first():
    from src.engine.services.population_manager import _breeding_order
    a, b, c, d = seeds()
    ranked = [scored(a, "A", -3.0), scored(b, "A", -3.1), scored(c, "A", -3.2)]
    assert all(_breeding_order(ranked, t) == ranked for t in range(3))


def test_every_surviving_programme_gets_offspring():
    engine = engine_for(TestDomainV1())
    pop = engine.population_manager.get_population("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=5)
    for _ in range(30):
        engine.learn(gen.sample(30))
    alive = {c.lineage for c in pop.active_candidates()}
    bred = {c.lineage for c in pop.candidates if c.generation > 0}
    assert alive <= bred


def by_complexity():
    from src.engine.model.scoring import free_parameter_count
    ordered = sorted(seeds(), key=free_parameter_count)
    assert free_parameter_count(ordered[-1]) - free_parameter_count(ordered[0]) >= 2
    return ordered


def test_complexity_alone_does_not_refute():
    # The replays: rivals that predicted as well as the leader died within
    # weeks, refuted by the BIC penalty rather than by the evidence. Occam's
    # razor ranks conjectures; only evidence refutes them (D22).
    simple, *middle, complex_ = by_complexity()
    pm = manager_with([scored(simple, "A", -3.00), scored(middle[0], "A", -3.01),
                       scored(middle[1], "A", -3.02), scored(complex_, "B", -3.00)])
    assert complex_ not in pm.prune_low_scorers("test-domain-v1")


def test_evidence_is_compared_over_the_records_both_were_judged_on():
    # A rival scored on twice as many records has twice the total
    # log-likelihood to lose; that is not evidence against it.
    a, b, c, d = seeds()
    pm = manager_with([scored(a, "A", -3.00, n=300.0), scored(b, "A", -3.01, n=300.0), scored(c, "A", -3.00),
                       scored(d, "B", -3.025, n=300.0)])
    # The leader (c) has seen 150 records. Over those, d trails by 3.75 nats,
    # short of 4.6; window totals would have put it 482 nats behind.
    assert d not in pm.prune_low_scorers("test-domain-v1")


def test_a_shift_records_whether_the_lead_changed_programme():
    """Every change of leader is logged (SPEC: a paradigm shift), but a variant
    overtaking one of its own programme is that programme revising itself,
    and only a rival programme taking the lead is a change of worldview.
    Each event says which it was, so the two can be told apart."""
    from datetime import datetime
    from src.domains.test_domain_v1 import domain as d
    first = scored(d.make_tstar_candidate("test-domain-v1"), "T_star", -2.0)
    sibling = scored(d.make_talt_candidate("test-domain-v1"), "T_star", -3.0)
    rival = scored(d.make_null_candidate("test-domain-v1"), "T_null", -4.0)
    pm = manager_with([first, sibling, rival])

    sibling.window_log_score = -1.0 * sibling.window_evidence
    pm.end_cycle("test-domain-v1", evidence_ts=datetime(2008, 9, 14))
    rival.window_log_score = -0.5 * rival.window_evidence
    pm.end_cycle("test-domain-v1", evidence_ts=datetime(2020, 3, 15))

    revision, shift = pm.pop_store.load_shift_events("test-domain-v1")
    assert (revision["prev_programme"], revision["new_programme"]) == ("T_star", "T_star")
    assert (shift["prev_programme"], shift["new_programme"]) == ("T_star", "T_null")


def test_generations_led_counts_from_the_last_paradigm_shift():
    """How long the leading programme has led: since the last shift, or since
    the start if none. Not the leading candidate's age, which a variant born
    long after its programme took the lead would understate."""
    from datetime import datetime
    engine = engine_for(TestDomainV1())
    domain = "test-domain-v1"
    pop = engine.get_population(domain)
    pop.generation = 12
    assert engine.generations_led(domain) == 12

    engine.population_store.append_shift_event(
        domain_module_id=domain, generation=7, prev_dominant_id=uuid4(), prev_dominant_name="a",
        new_dominant_id=uuid4(), new_dominant_name="b", evidence_count_at_shift=40,
        evidence_ts=datetime(2020, 3, 15), prev_programme="a", new_programme="b")
    pop.paradigm_shift_count = 1
    assert engine.generations_led(domain) == 5


def test_generations_led_is_unknown_when_the_log_predates_the_population():
    """Before populations were persisted (B1) each restart counted generations
    from 0 again, so an old log can end with a shift numbered past today's
    generation. With no shift in this population's life the leader has led
    throughout; with one that cannot be placed, how long is unknown."""
    from datetime import datetime
    engine = engine_for(TestDomainV1())
    domain = "test-domain-v1"
    pop = engine.get_population(domain)
    pop.generation = 6
    engine.population_store.append_shift_event(
        domain_module_id=domain, generation=408, prev_dominant_id=uuid4(), prev_dominant_name="a",
        new_dominant_id=uuid4(), new_dominant_name="b", evidence_count_at_shift=40,
        evidence_ts=datetime(2026, 5, 27), prev_programme="a", new_programme="b")

    pop.paradigm_shift_count = 0
    assert engine.generations_led(domain) == 6
    pop.paradigm_shift_count = 1
    assert engine.generations_led(domain) is None
