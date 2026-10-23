"""Epistemic health (SPEC §13.1, REFACTOR_SPEC D18): how well the population
as a whole, weighted by belief, predicted each batch (humility), and whether
its stated confidence about each variable, given the others, comes true as
often as it says (calibration)."""
import math

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.calibration import Calibration, mixture_log_likelihood


def test_a_mixture_of_one_is_that_one():
    assert mixture_log_likelihood([-3.0], [1.0]) == -3.0


def test_a_mixture_lies_between_its_parts():
    ll = mixture_log_likelihood([-2.0, -6.0], [0.5, 0.5])
    assert -6.0 < ll < -2.0 and abs(ll - math.log(0.5 * math.exp(-2) + 0.5 * math.exp(-6))) < 1e-12


def test_perfect_confidence_rightly_held_is_perfectly_calibrated():
    c = Calibration()
    for _ in range(10):
        c.observe(1.0, True)
        c.observe(0.0, False)
    assert c.summary()["brier"] == 0.0 and c.summary()["calibration_error"] == 0.0


def test_seventy_percent_that_comes_true_seventy_percent_is_calibrated():
    c = Calibration()
    for i in range(100):
        c.observe(0.7, i % 10 < 7)
    s = c.summary()
    assert abs(s["calibration_error"]) < 1e-9 and abs(s["brier"] - 0.21) < 1e-9


def test_overconfidence_shows():
    c = Calibration()
    for i in range(100):
        c.observe(0.95, i % 2 == 0)
    assert c.summary()["calibration_error"] > 0.4


def test_round_trips():
    c = Calibration()
    c.observe(0.3, False)
    assert Calibration.from_state(c.state()).summary() == c.summary()


def test_the_engine_tracks_both_every_cycle():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    for _ in range(6):
        engine.learn(gen.sample(20))
    health = engine.epistemic_health("test-domain-v1")
    assert health["last_cycle"]["population_ll"] <= 0 and health["last_cycle"]["leader_ll"] <= 0
    assert health["leader_calibration"]["n"] == 5 * 5   # 5 variables, every cycle after the first
    assert health["population_calibration"]["n"] == 5 * 5


def test_an_outcome_may_itself_be_uncertain():
    # Soft evidence says how likely a signal is, not whether it was: saying
    # 70% of a signal the evidence puts at 70% is calibrated against it.
    c = Calibration()
    for _ in range(20):
        c.observe(0.7, 0.7)
    s = c.summary()
    assert abs(s["calibration_error"]) < 1e-9 and abs(s["brier"]) < 1e-9


def test_with_hard_evidence_both_measures_agree():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    for _ in range(6):
        engine.learn(gen.sample(20))
    health = engine.epistemic_health("test-domain-v1")
    assert health["leader_calibration_vs_evidence"] == health["leader_calibration"]


def test_soft_evidence_is_judged_against_its_own_probability():
    from datetime import date, timedelta
    from tests.fakes import soft_record

    domain = TestDomainV1()
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(domain)
    engine.activate_domain("test-domain-v1")
    variables = domain.initial_candidates()[0].variables
    for week in range(6):
        engine.learn([soft_record(variables, date(2024, 1, 7) + timedelta(weeks=week), seed=3)])
    health = engine.epistemic_health("test-domain-v1")
    vs_evidence, rounded = health["leader_calibration_vs_evidence"], health["leader_calibration"]
    assert vs_evidence["n"] == rounded["n"] == 5 * 5
    assert vs_evidence["brier"] != rounded["brier"]
