"""
REFACTOR_SPEC B21: population weights are a BIC posterior over structures.

score_weights was a softmax of per-record average scores. Averages of
competing structures differ by hundredths of a nat, so every candidate got
about the same weight: structure_entropy read ≈ ln(population size) on every
domain ("not converged" forever) and weighted inference was a plain mean.
The BIC approximation of log P(data | structure) is the total, n · score.
"""
from __future__ import annotations

import math

from src.domains.test_domain_v1.domain import (
    TestDomainV1,
    make_null_candidate,
    make_tstar_candidate,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.scoring import candidate_score, score_weights, structure_entropy


def _scored(make, avg_ll: float, n: int):
    cand = make()
    cand.evidence_count = cand.window_evidence = n
    cand.log_score = cand.window_log_score = avg_ll * n
    return cand


def test_weights_follow_total_evidence_not_per_record_averages():
    a = _scored(make_tstar_candidate, -2.80, 300)
    b = _scored(make_tstar_candidate, -2.81, 300)  # same k, 0.01 nats/record worse
    wa, wb = score_weights([a, b])
    assert math.isclose(wa / wb, math.exp(0.01 * 300), rel_tol=1e-9)


def test_weights_charge_the_bic_penalty_in_total():
    sparse = _scored(make_null_candidate, -2.80, 300)
    dense = _scored(make_tstar_candidate, -2.80, 300)
    gap = (candidate_score(sparse) - candidate_score(dense)) * 300
    ws, wd = score_weights([sparse, dense])
    assert math.isclose(ws / wd, math.exp(gap), rel_tol=1e-9)


def test_unscored_candidates_get_no_weight_and_all_unscored_share_it():
    scored = _scored(make_tstar_candidate, -2.8, 30)
    fresh = make_null_candidate()
    assert score_weights([scored, fresh]) == [1.0, 0.0]
    assert score_weights([make_null_candidate(), make_null_candidate()]) == [0.5, 0.5]


def test_structure_entropy_falls_once_one_structure_explains_the_data():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=0)
    for _ in range(10):
        engine.learn(gen.sample(30))
    active = engine.get_population().active_candidates()
    assert structure_entropy(active) < 0.5 * math.log(len(active))
