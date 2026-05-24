"""
Level 2 tests — edge existence update.
Tests: TEST-L2-01 through TEST-L2-05.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.test_domain_v1.domain import (
    T_ALT_EDGES,
    T_STAR_EDGES,
    make_spurious_1_candidate,
    make_tstar_candidate,
    _make_edge,
    _VARIABLE_DEFS,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.schemas import EdgeExistenceThresholdConfig, OntologyCandidate
from src.engine.services.edge_existence import EdgeExistenceService
from src.engine.services.learning import LearningService
from src.engine.stores.parameter_store import ParameterStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def _run_learning_cycles(candidate, evidence, batch_size=30):
    """Run full learning + edge existence update for given evidence."""
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)
    ees = EdgeExistenceService(ps, EdgeExistenceThresholdConfig(
        prune_below=0.05, accept_above=0.90, explore_band=(0.3, 0.7)
    ))
    for batch in chunk(evidence, batch_size):
        ls.accumulate(batch, candidate)
        ees.update(candidate)
    return ps, ees


def _get_edge_existence(candidate, parent_name, child_name):
    """Return existence_probability for a specific edge."""
    for e in candidate.edges:
        pv = candidate.get_variable_by_id(e.parent_variable_id)
        cv = candidate.get_variable_by_id(e.child_variable_id)
        if pv and cv and pv.name == parent_name and cv.name == child_name:
            return e.existence_probability
    return None


# ---------------------------------------------------------------------------
# TEST-L2-01: True edge existence rises
# ---------------------------------------------------------------------------

def test_L2_01_true_edge_existence_rises():
    """
    Given: edge A→C initialized with existence_prior=0.5
    When:  300 evidence records from T*
    Then:  existence_probability(A→C) > 0.85
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=300)

    candidate = make_tstar_candidate()
    # Reset existence probabilities to prior=0.5
    for e in candidate.edges:
        e.existence_prior = 0.5
        e.existence_probability = 0.5

    _run_learning_cycles(candidate, evidence, batch_size=30)

    p = _get_edge_existence(candidate, "A", "C")
    assert p is not None, "Edge A→C not found"
    assert p > 0.85, f"Expected existence_probability(A→C) > 0.85, got {p:.4f}"


# ---------------------------------------------------------------------------
# TEST-L2-02: Spurious edge existence falls
# ---------------------------------------------------------------------------

def test_L2_02_spurious_edge_existence_falls():
    """
    Given: spurious edge A→D in candidate (T* + A→D), existence_prior=0.5
    When:  300 evidence records from T*
    Then:  existence_probability(A→D) < 0.15
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=300)

    # Candidate: T* + spurious A→D
    candidate = make_spurious_1_candidate()
    for e in candidate.edges:
        e.existence_prior = 0.5
        e.existence_probability = 0.5

    _run_learning_cycles(candidate, evidence, batch_size=30)

    p = _get_edge_existence(candidate, "A", "D")
    assert p is not None, "Edge A→D not found"
    assert p < 0.15, f"Expected existence_probability(A→D) < 0.15, got {p:.4f}"


# ---------------------------------------------------------------------------
# TEST-L2-03: Existence update is monotone in expectation
# ---------------------------------------------------------------------------

def test_L2_03_existence_update_direction():
    """
    Given: a true edge (A→C) and a spurious edge (A→D), both at prior=0.5
    When:  evidence batches arrive sequentially from T*
    Then:  true edge trends upward; spurious edge trends downward
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=300)

    candidate = make_spurious_1_candidate()
    for e in candidate.edges:
        e.existence_prior = 0.5
        e.existence_probability = 0.5

    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)
    ees = EdgeExistenceService(ps, EdgeExistenceThresholdConfig(
        prune_below=0.01, accept_above=0.99, explore_band=(0.3, 0.7)
    ))

    true_edge_history = []
    spurious_edge_history = []

    for batch in chunk(evidence, 30):
        ls.accumulate(batch, candidate)
        ees.update(candidate)
        p_true = _get_edge_existence(candidate, "A", "C")
        p_spurious = _get_edge_existence(candidate, "A", "D")
        if p_true is not None:
            true_edge_history.append(p_true)
        if p_spurious is not None:
            spurious_edge_history.append(p_spurious)

    # True edge: last value should be > first value
    assert true_edge_history[-1] > true_edge_history[0], (
        f"True edge should trend up: first={true_edge_history[0]:.3f}, last={true_edge_history[-1]:.3f}"
    )
    # Spurious edge: last value should be < first value
    assert spurious_edge_history[-1] < spurious_edge_history[0], (
        f"Spurious edge should trend down: first={spurious_edge_history[0]:.3f}, last={spurious_edge_history[-1]:.3f}"
    )


# ---------------------------------------------------------------------------
# TEST-L2-04: Edge pruning fires at threshold
# ---------------------------------------------------------------------------

def test_L2_04_edge_pruned_at_threshold():
    """
    Given: spurious edge A→D, existence_thresholds.prune_below=0.05
    When:  500 records from T*
    Then:  edge A→D is disabled (enabled=False) and pruning logged
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=500)

    candidate = make_spurious_1_candidate()
    for e in candidate.edges:
        e.existence_prior = 0.5
        e.existence_probability = 0.5

    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)
    ees = EdgeExistenceService(ps, EdgeExistenceThresholdConfig(
        prune_below=0.05, accept_above=0.90, explore_band=(0.3, 0.7)
    ))

    pruned_edges = []
    for batch in chunk(evidence, 50):
        ls.accumulate(batch, candidate)
        ees.update(candidate)
        pruned = ees.prune_below_threshold(candidate, ps)
        pruned_edges.extend(pruned)

    # Check that A→D is pruned
    p = _get_edge_existence(candidate, "A", "D")
    a_d_edge = None
    for e in candidate.edges:
        pv = candidate.get_variable_by_id(e.parent_variable_id)
        cv = candidate.get_variable_by_id(e.child_variable_id)
        if pv and cv and pv.name == "A" and cv.name == "D":
            a_d_edge = e
            break

    assert a_d_edge is not None, "A→D edge not found"
    assert not a_d_edge.enabled, (
        f"Edge A→D should be pruned (disabled). existence_probability={a_d_edge.existence_probability:.4f}"
    )


# ---------------------------------------------------------------------------
# TEST-L2-05: Explore weight decays as existence resolves
# ---------------------------------------------------------------------------

def test_L2_05_explore_weight_decays():
    """
    Given: edge C→E at existence_prior=0.5, explore_weight=1.0
    When:  existence_probability converges above accept_above (0.90)
    Then:  explore_weight has decayed below 0.5
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=400)

    candidate = make_tstar_candidate()
    for e in candidate.edges:
        e.existence_prior = 0.5
        e.existence_probability = 0.5
        e.explore_weight = 1.0

    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)
    ees = EdgeExistenceService(ps, EdgeExistenceThresholdConfig(
        prune_below=0.05, accept_above=0.90, explore_band=(0.3, 0.7)
    ))

    for batch in chunk(evidence, 40):
        ls.accumulate(batch, candidate)
        ees.update(candidate)

    # Find C→E edge
    ce_edge = None
    for e in candidate.edges:
        pv = candidate.get_variable_by_id(e.parent_variable_id)
        cv = candidate.get_variable_by_id(e.child_variable_id)
        if pv and cv and pv.name == "C" and cv.name == "E":
            ce_edge = e
            break

    assert ce_edge is not None, "C→E edge not found"
    # Existence should be high (C→E is a true edge)
    assert ce_edge.existence_probability > 0.85, (
        f"C→E existence should be high, got {ce_edge.existence_probability:.3f}"
    )
    # Explore weight should have decayed
    assert ce_edge.explore_weight < 0.5, (
        f"Explore weight should decay below 0.5, got {ce_edge.explore_weight:.3f}"
    )
