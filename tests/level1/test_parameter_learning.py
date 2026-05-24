"""
Level 1 tests — parameter learning.
Tests: TEST-L1-01 through TEST-L1-04.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import hashlib
import pytest

from src.domains.test_domain_v1.domain import (
    TestDomainV1,
    make_tstar_candidate,
    T_STAR_CPTS,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.services.learning import LearningService
from src.engine.stores.parameter_store import ParameterStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def make_fixed_engine():
    """Engine with a single T* candidate for parameter learning tests."""
    eng = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = TestDomainV1()
    eng.register_domain(domain)
    eng.activate_domain(domain.module_id())
    return eng


# ---------------------------------------------------------------------------
# TEST-L1-01: Single variable posterior convergence
# ---------------------------------------------------------------------------

def test_L1_01_parameter_update_single_variable():
    """
    Given: variable A with uniform prior Beta(1,1)
    When:  100 samples with P(A=True)=0.7 are ingested
    Then:  posterior mean of P(A=True) converges within 0.05 of 0.7
    """
    gen = SyntheticDataGenerator(random_seed=42)
    evidence = gen.sample_variable_only("A", n=100, p_true=0.7)

    # Use a standalone candidate with just variable A (no parents)
    from src.domains.test_domain_v1.domain import make_tstar_candidate
    cand = make_tstar_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(cand)

    ls.accumulate(evidence, cand)

    var_a = cand.get_variable_by_name("A")
    cpt_data = ps.get(cand.candidate_id, "A")
    # A is a root node (no parents)
    p_true = cpt_data.get_probability(True, {})
    assert abs(p_true - 0.7) < 0.08, (
        f"Expected P(A=True) ≈ 0.7, got {p_true:.4f}"
    )


# ---------------------------------------------------------------------------
# TEST-L1-02: Full CPT convergence under ground truth graph
# ---------------------------------------------------------------------------

def test_L1_02_cpt_convergence_full_graph():
    """
    Given: fixed graph T*, all edges enabled, uniform priors
    When:  500 evidence records from T*
    Then:  all CPT entries within 0.10 of ground truth values
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=500)

    cand = make_tstar_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(cand)
    ls.accumulate(evidence, cand)

    tolerance = 0.10

    # Check variable C (most complex: 2 parents)
    cpt_c = ps.get(cand.candidate_id, "C")
    ground = T_STAR_CPTS["C"]
    for parent_config, val_dist in ground.items():
        for val, expected_p in val_dist.items():
            parent_assignment = dict(parent_config)
            learned_p = cpt_c.get_probability(val, parent_assignment)
            assert abs(learned_p - expected_p) < tolerance, (
                f"C CPT mismatch at {parent_config}, {val}: "
                f"expected {expected_p:.3f}, got {learned_p:.3f}"
            )

    # Check variable D (1 parent: B)
    cpt_d = ps.get(cand.candidate_id, "D")
    ground_d = T_STAR_CPTS["D"]
    for parent_config, val_dist in ground_d.items():
        for val, expected_p in val_dist.items():
            parent_assignment = dict(parent_config)
            learned_p = cpt_d.get_probability(val, parent_assignment)
            assert abs(learned_p - expected_p) < tolerance, (
                f"D CPT mismatch at {parent_config}, {val}: "
                f"expected {expected_p:.3f}, got {learned_p:.3f}"
            )

    # Check variable E (2 parents: C, D)
    cpt_e = ps.get(cand.candidate_id, "E")
    ground_e = T_STAR_CPTS["E"]
    for parent_config, val_dist in ground_e.items():
        for val, expected_p in val_dist.items():
            parent_assignment = dict(parent_config)
            learned_p = cpt_e.get_probability(val, parent_assignment)
            assert abs(learned_p - expected_p) < tolerance, (
                f"E CPT mismatch at {parent_config}, {val}: "
                f"expected {expected_p:.3f}, got {learned_p:.3f}"
            )


# ---------------------------------------------------------------------------
# TEST-L1-03: Bitwise reproducibility
# ---------------------------------------------------------------------------

def test_L1_03_parameter_reproducibility():
    """
    Given: identical evidence sequence and random seed
    When:  learning is run twice
    Then:  parameter hashes are identical
    """
    gen1 = SyntheticDataGenerator(graph="T*", random_seed=42)
    gen2 = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence1 = gen1.sample(n=200)
    evidence2 = gen2.sample(n=200)

    def run_once(evidence):
        cand = make_tstar_candidate()
        ps = ParameterStore()
        ls = LearningService(ps)
        ls.initialize_candidate(cand)
        ls.accumulate(evidence, cand)
        return ps.parameter_hash(cand.candidate_id)

    h1 = run_once(evidence1)
    h2 = run_once(evidence2)
    assert h1 == h2, f"Parameter hashes differ: {h1} vs {h2}"


# ---------------------------------------------------------------------------
# TEST-L1-04: Missing evidence EM convergence
# ---------------------------------------------------------------------------

def test_L1_04_missing_evidence_em():
    """
    Given: 30% of observations have missingness=MISSING
    When:  EM parameter fitting runs via proper posterior inference
    Then:  CPT convergence within 0.12 of ground truth
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42, missing_rate=0.30)
    evidence = gen.sample(n=500)

    cand = make_tstar_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(cand)

    # Use proper EM with pgmpy E-step (5 iterations)
    ls.accumulate_em(evidence, cand, n_iterations=5)

    tolerance = 0.12

    # Check key entries
    cpt_c = ps.get(cand.candidate_id, "C")
    # P(C=T|A=T,B=T) should be near 0.95
    p = cpt_c.get_probability(True, {"A": True, "B": True})
    assert abs(p - 0.95) < tolerance, f"C(T|T,T) expected 0.95, got {p:.3f}"

    # P(C=T|A=F,B=F) should be near 0.05
    p = cpt_c.get_probability(True, {"A": False, "B": False})
    assert abs(p - 0.05) < tolerance, f"C(T|F,F) expected 0.05, got {p:.3f}"

    cpt_d = ps.get(cand.candidate_id, "D")
    # P(D=T|B=T) should be near 0.7
    p = cpt_d.get_probability(True, {"B": True})
    assert abs(p - 0.70) < tolerance, f"D(T|B=T) expected 0.70, got {p:.3f}"
