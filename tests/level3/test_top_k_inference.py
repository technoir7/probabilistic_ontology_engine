"""
REFACTOR_SPEC B4: TOP_K weighted candidates by exp(raw log_score). At real
scores (hundreds or thousands below zero) every weight underflows to 0.0 and
the merged posteriors are all zero.
"""
from __future__ import annotations

import math

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import InferenceQuery, PopulationAggregation


def test_top_k_posteriors_are_distributions_after_real_learning():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    for _ in range(10):
        engine.learn(gen.sample(30))
    assert max(c.log_score for c in engine.get_population().active_candidates()) < -700

    result = engine.query(InferenceQuery(
        domain_module_id="test-domain-v1",
        target_variables=["A", "C", "E"],
        population_aggregation=PopulationAggregation.TOP_K,
    ))
    for name, dist in result["posteriors"].items():
        assert math.isclose(sum(dist.values()), 1.0, rel_tol=1e-9), (name, dist)
