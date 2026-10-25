"""The leader's core is put on trial (REFACTOR_SPEC D27).

A rival needs an anomaly: a connection the evidence supports that the leader
lacks (D26). Where the evidence prompts none, the leader would never be
challenged. So while no other worldview is alive, the engine founds a trial
of the leader's core: the leader's structure without the connection that
founded its programme, everything else kept, level with it. Without its
core it holds no worldview (Popper: even the core faces the test; the
leader keeps it only by predicting better from here on)."""
import math

from src.domains.test_domain_v1.domain import _var_list
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.model.scoring import candidate_score, dominant, log_bayes_factor
from src.engine.services.programmes import UNCONNECTED, unconnected
from tests.level3.test_rival_founding import manager, scored, with_edges

DOMAIN = "test-domain-v1"
T_STAR = [("A", "C"), ("B", "C"), ("B", "D"), ("C", "E"), ("D", "E")]


def introduced(population, admissible=frozenset(T_STAR)):
    # Admitting only the leader's own connections, the evidence prompts no
    # rival: there is no connection it lacks.
    pm = manager(population, admissible=set(admissible))
    new = pm.introduce_variants(DOMAIN, SyntheticDataGenerator(graph="T*", random_seed=0).sample(200))
    return pm, [c for c in new if c.description.startswith("trial_")]


def test_with_no_anomaly_the_leaders_core_is_put_on_trial_level_with_it():
    leader = scored(with_edges(unconnected(DOMAIN, _var_list()), T_STAR, "B–D"), -3.0)
    pm, trials = introduced([leader])
    assert len(trials) == 1
    trial = trials[0]
    assert trial.description == "trial_B->D"
    assert trial.parent_candidate_id == leader.candidate_id
    assert trial.edge_structure_signature() == set(T_STAR) - {("B", "D")}
    assert trial.lineage == UNCONNECTED  # without its core, no worldview
    # Level on score: its fit is lowered by what it saves in complexity.
    assert 0 <= candidate_score(leader) - candidate_score(trial) < 1e-12
    assert dominant(pm.get_population(DOMAIN).active_candidates()) is leader


def test_no_trial_while_another_worldview_is_alive():
    start = unconnected(DOMAIN, _var_list())
    leader = scored(with_edges(start, T_STAR, "B–D"), -3.0)
    rival = scored(with_edges(start, [("A", "C")], "A–C"), -3.4)
    _, trials = introduced([leader, rival])
    assert trials == []


def test_no_second_trial_while_one_is_alive():
    start = unconnected(DOMAIN, _var_list())
    leader = scored(with_edges(start, T_STAR, "B–D"), -3.0)
    on_trial = scored(with_edges(start, [e for e in T_STAR if e != ("B", "D")], UNCONNECTED), -3.0)
    _, trials = introduced([leader, on_trial])
    assert trials == []


def test_no_trial_of_a_leader_that_no_longer_holds_its_core():
    leader = scored(with_edges(unconnected(DOMAIN, _var_list()), [e for e in T_STAR if e != ("B", "D")], "B–D"), -3.0)
    _, trials = introduced([leader])
    assert trials == []


def test_a_trial_is_not_refuted_for_the_fit_it_gave_up_by_being_simpler():
    # Without D→E, E's table halves: the trial's fit is lowered by more than
    # a decisive Bayes factor to tie the leader. That is no evidence against it.
    leader = scored(with_edges(unconnected(DOMAIN, _var_list()), T_STAR, "D–E"), -3.0)
    pm, (trial,) = introduced([leader])
    assert log_bayes_factor(leader, trial) > math.log(100)
    trial.window_log_score -= 1e-6  # a hair behind, so it is the one up for pruning
    pm.prune_low_scorers(DOMAIN)
    assert trial in pm.get_population(DOMAIN).active_candidates()
