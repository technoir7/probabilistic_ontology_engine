"""
REFACTOR_SPEC D14 (3), D8: how candidates are scored so the engine notices a
regime change (TEST-L3-03 / G2) without being fooled by noise.

1. Prequential: each batch is scored under the CPTs from before it. Scoring
   after learning from the batch rewards extra edges by about the BIC
   penalty, so spurious edges (e.g. B->A) beat the true graph.
2. A score window (SPEC §6 `score_window`): evidence is discounted with a
   half-life, so a structure that fits the last few hundred records can
   overtake one that fitted an earlier regime.
3. No edge is pruned before its candidate has seen a minimum of evidence:
   at 30 records BIC can reject a real edge, and pruning is permanent.
"""
from __future__ import annotations

import math

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1, make_tstar_candidate
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.scoring import (
    SCORE_HALF_LIFE_RECORDS,
    add_to_window,
    candidate_score,
)
from src.engine.services.edge_existence import MIN_RECORDS_FOR_EDGE_PRUNING

DOMAIN_ID = "test-domain-v1"


def _engine(seed: int = 0) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def test_each_batch_is_scored_before_it_is_learned():
    engine = _engine()
    gen = SyntheticDataGenerator(graph="T*", random_seed=0)
    engine.learn(gen.sample(30))
    batch = gen.sample(30)
    before = {
        c.candidate_id: (c.log_score, engine.learning_service.compute_log_likelihood(batch, c))
        for c in engine.get_population().active_candidates()
    }
    engine.learn(batch)
    for c in engine.get_population().candidates:
        if c.candidate_id in before:
            old, expected = before[c.candidate_id]
            assert math.isclose(c.log_score - old, expected, rel_tol=1e-12), c.description


def test_window_discounts_old_evidence_by_its_half_life():
    ll, n = add_to_window(0.0, 0.0, -100.0, 50)
    ll, n = add_to_window(ll, n, -60.0, SCORE_HALF_LIFE_RECORDS)
    assert math.isclose(n, 50 * 0.5 + SCORE_HALF_LIFE_RECORDS)
    assert math.isclose(ll, -100.0 * 0.5 - 60.0)


def test_recent_fit_outranks_an_old_one():
    old_fit, new_fit = make_tstar_candidate(DOMAIN_ID), make_tstar_candidate(DOMAIN_ID)
    for cand, history in ((old_fit, [-2.0, -3.0]), (new_fit, [-3.0, -2.0])):
        for avg in history:  # 300 records per regime, per-record log-likelihood avg
            cand.log_score += avg * 300
            cand.evidence_count += 300
            cand.window_log_score, cand.window_evidence = add_to_window(
                cand.window_log_score, cand.window_evidence, avg * 300, 300
            )
    assert old_fit.log_score == new_fit.log_score  # same cumulative total
    assert candidate_score(new_fit) > candidate_score(old_fit)


def test_unscored_candidate_scores_minus_infinity():
    assert candidate_score(make_tstar_candidate(DOMAIN_ID)) == -math.inf


@pytest.mark.parametrize("seed", range(5))
def test_no_edge_is_pruned_before_the_minimum_evidence(seed):
    engine = _engine(seed)
    gen = SyntheticDataGenerator(graph="T*", random_seed=seed)
    for _ in range(MIN_RECORDS_FOR_EDGE_PRUNING // 30 - 1):  # every CPT below the minimum
        engine.learn(gen.sample(30))
        for c in engine.get_population().candidates:
            assert all(e.enabled for e in c.edges), c.description
