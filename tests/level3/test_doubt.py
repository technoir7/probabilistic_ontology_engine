"""Crisis-sensitive doubt (REFACTOR_SPEC D17): when the leading structure is
far more surprised by a week than it usually is, every candidate's learned
counts and score window count for half, before it learns that week."""
from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.cpt import CPTData
from src.engine.model.doubt import MIN_RECORDS, Surprise


def test_ordinary_weeks_are_not_a_crisis():
    s = Surprise()
    assert not any(s.observe(5.0 + (i % 3) * 0.1, 1) for i in range(200))


def test_a_spike_after_enough_evidence_is_a_crisis():
    s = Surprise()
    for i in range(MIN_RECORDS + 10):
        s.observe(5.0 + (i % 3) * 0.1, 1)
    assert s.observe(9.0, 1)


def test_no_crisis_before_enough_evidence():
    s = Surprise()
    for i in range(MIN_RECORDS - 5):
        assert not s.observe(5.0 if i < MIN_RECORDS - 6 else 50.0, 1)


def test_the_tracker_round_trips():
    s = Surprise()
    for i in range(30):
        s.observe(4.0 + i % 2, 1)
    assert Surprise.from_state(s.state()) == s


def test_discounting_halves_the_counts_and_keeps_the_rows():
    cpt = CPTData("C", ["A"], [True, False], counts={(("A", True),): {True: 8.0, False: 2.0}})
    cpt.discount(0.5)
    assert cpt.counts == {(("A", True),): {True: 4.0, False: 1.0}}


def _engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    return engine


def test_a_crisis_halves_what_every_candidate_has_learned(monkeypatch):
    engine = _engine()
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    for _ in range(4):
        engine.learn(gen.sample(30))
    pop = engine.population_manager.get_population("test-domain-v1")
    before = {c.candidate_id: (engine.parameter_store.get(c.candidate_id, "C").total_count(), c.window_evidence)
              for c in pop.active_candidates()}
    def crisis(self, per_record, n):
        self.events += 1
        return True
    monkeypatch.setattr(Surprise, "observe", crisis)
    batch = gen.sample(30)
    engine.learn(batch)
    for c in pop.active_candidates():
        if c.candidate_id in before:
            counts, window = before[c.candidate_id]
            assert engine.parameter_store.get(c.candidate_id, "C").total_count() == counts / 2 + 30
            assert abs(c.window_evidence - (window / 2 * 0.5 ** (30 / 100) + 30)) < 1e-6
    assert engine.doubt_events("test-domain-v1") == 1


def test_stationary_evidence_rarely_raises_doubt():
    engine = _engine()
    gen = SyntheticDataGenerator(graph="T*", random_seed=2)
    for _ in range(60):
        engine.learn(gen.sample(10))
    assert engine.doubt_events("test-domain-v1") <= 3
