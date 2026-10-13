"""
REFACTOR_SPEC C1 / B18: new variants are mutations of the best survivors by
candidate_score, best first. Previously parents were ranked by raw log_score
(which mostly measures how much evidence a candidate has seen) and the loop
started at index 1, so the first variant came from the second-ranked survivor.
"""
from __future__ import annotations

import random

from src.domains.test_domain_v1.domain import (
    make_null_candidate,
    make_talt_candidate,
    make_tstar_candidate,
)
from src.engine.model.scoring import candidate_score
from src.engine.services.learning import LearningService
from src.engine.services.population_manager import PopulationManager
from src.engine.stores.parameter_store import ParameterStore
from src.engine.stores.population_store import PopulationStore

DOMAIN_ID = "test-domain-v1"


def _population(seed: int):
    best = make_tstar_candidate(DOMAIN_ID)       # many records, best average
    best.log_score, best.evidence_count = best.window_log_score, best.window_evidence = -300.0, 300
    middle = make_talt_candidate(DOMAIN_ID)      # few records, worse average
    middle.log_score, middle.evidence_count = middle.window_log_score, middle.window_evidence = -40.0, 10
    worst = make_null_candidate(DOMAIN_ID)
    worst.log_score, worst.evidence_count = worst.window_log_score, worst.window_evidence = -60.0, 10
    # Raw log_score ranks middle > worst > best; the score ranks best first.
    assert candidate_score(best) > candidate_score(middle) > candidate_score(worst)

    ps = ParameterStore()
    learning = LearningService(ps)
    for cand in (best, middle, worst):
        learning.initialize_candidate(cand)
    pm = PopulationManager(
        parameter_store=ps, population_store=PopulationStore(":memory:"), rng=random.Random(seed)
    )
    names = [v.name for v in best.variables]
    pm.initialize(
        domain_module_id=DOMAIN_ID,
        initial_candidates=[best, middle, worst],
        max_population_size=4,  # exactly one slot
        admissible_edges={(a, b) for a in names for b in names if a != b},
    )
    return pm, best


def test_first_variant_attempt_mutates_the_best_scoring_survivor():
    checked = 0
    for seed in range(20):
        pm, best = _population(seed)
        [variant] = pm.introduce_variants(DOMAIN_ID)
        # A first attempt can be rejected (duplicate structure) and the loop
        # moves on; only first-attempt successes say who was tried first.
        if pm.last_mutation_stats(DOMAIN_ID)["total_attempts"] == 1:
            checked += 1
            assert variant.parent_candidate_id == best.candidate_id, f"seed {seed}"
    assert checked >= 5, "too few first-attempt successes to say anything"
