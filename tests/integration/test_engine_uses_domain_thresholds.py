"""
REFACTOR_SPEC B2: the engine must prune and band edges with the domain's own
existence_thresholds(), not the library defaults.
"""
from __future__ import annotations

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EdgeExistenceThresholdConfig
from src.engine.services.edge_existence import MIN_RECORDS_FOR_EDGE_PRUNING


class StrictPruningDomain(TestDomainV1):
    """Prunes any edge whose existence probability drops below 0.5."""

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.5, accept_above=0.95, explore_band=(0.6, 0.9)
        )


def test_engine_prunes_edges_with_the_domain_threshold():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    engine.register_domain(StrictPruningDomain())
    engine.activate_domain("test-domain-v1")
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    # Long enough for hypotheses formed along the way to reach the pruning
    # minimum: none is given at the start (D24).
    for _ in range(20):
        engine.learn(gen.sample(30))

    def prunable(c, e) -> bool:
        # Edges whose child CPT is still below the pruning minimum are kept by design.
        child = c.get_variable_by_id(e.child_variable_id).name
        return engine.parameter_store.get(c.candidate_id, child).total_count() >= MIN_RECORDS_FOR_EDGE_PRUNING

    edges = [(c, e) for c in engine.get_population().candidates for e in c.edges if e.existence_update_count]
    assert edges, "some edges should have been updated"
    for c, e in edges:
        if e.enabled and prunable(c, e):
            assert e.existence_probability >= 0.5, "an edge below the domain's prune_below survived"
    edges = [e for _, e in edges]
    assert any(not e.enabled and e.existence_probability >= 0.05 for e in edges), (
        "expected edges between the default (0.05) and domain (0.5) thresholds to be pruned"
    )
