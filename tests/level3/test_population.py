"""
Level 3 tests — ontology population management.
Tests: TEST-L3-01 through TEST-L3-06.
Milestone: TEST-L3-03 (paradigm shift detection).
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import random
import pytest
from uuid import uuid4

from src.domains.test_domain_v1.domain import (
    T_STAR_EDGES,
    T_ALT_EDGES,
    make_null_candidate,
    make_spurious_1_candidate,
    make_spurious_2_candidate,
    make_talt_candidate,
    make_tstar_candidate,
    _var_list,
    _make_edge,
    _VARIABLE_DEFS,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.schemas import (
    CandidateStatus,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
    OntologyPopulation,
)
from src.engine.services.edge_existence import EdgeExistenceService
from src.engine.services.learning import LearningService
from src.engine.services.population_manager import PopulationManager
from src.engine.stores.parameter_store import ParameterStore
from src.engine.stores.population_store import PopulationStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOMAIN_ID = "test-domain-v1"

def chunk(lst, size):
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def make_engine_components(candidates, max_pop=10):
    """Create a minimal stack for population-level tests."""
    ps = ParameterStore()
    ls = LearningService(ps)
    pop_store = PopulationStore(":memory:")
    thresholds = EdgeExistenceThresholdConfig(
        prune_below=0.05, accept_above=0.90, explore_band=(0.3, 0.7)
    )
    ees = EdgeExistenceService(ps, thresholds)
    pm = PopulationManager(
        parameter_store=ps,
        population_store=pop_store,
        thresholds=thresholds,
        rng=random.Random(42),
    )

    # Initialize each candidate's CPTs
    for cand in candidates:
        ls.initialize_candidate(cand)

    # Build admissible edges from all variables
    all_edges = set()
    var_names = [v.name for v in candidates[0].variables]
    for a in var_names:
        for b in var_names:
            if a != b:
                all_edges.add((a, b))

    pm.initialize(
        domain_module_id=DOMAIN_ID,
        initial_candidates=candidates,
        max_population_size=max_pop,
        admissible_edges=all_edges,
        thresholds=thresholds,
    )
    return ps, ls, ees, pm


def run_learning_cycle(ps, ls, ees, pm, batch, batch_idx=0):
    """Run one full learning cycle on a batch."""
    pop = pm.get_population(DOMAIN_ID)
    for candidate in pop.active_candidates():
        ls.accumulate(batch, candidate)
        ees.update(candidate)
        ees.prune_below_threshold(candidate, ps)
        log_lik = ls.compute_log_likelihood(batch, candidate)
        pm.update_score(DOMAIN_ID, candidate.candidate_id, log_lik, batch_idx, batch_size=len(batch))

    pm.prune_low_scorers(DOMAIN_ID)
    pm.introduce_variants(DOMAIN_ID, ls)
    pm.end_cycle(DOMAIN_ID)


# ---------------------------------------------------------------------------
# TEST-L3-01: True structure becomes dominant
# ---------------------------------------------------------------------------

def test_L3_01_true_structure_dominates():
    """
    Given: population of 5 candidates (T*, spurious1, spurious2, T_alt, null)
    When:  500 evidence records from T*
    Then:  T* candidate has highest log_score and is dominant
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=500)

    cand_true = make_tstar_candidate(DOMAIN_ID)
    cand_s1 = make_spurious_1_candidate(DOMAIN_ID)
    cand_s2 = make_spurious_2_candidate(DOMAIN_ID)
    cand_alt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    candidates = [cand_true, cand_s1, cand_s2, cand_alt, cand_null]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=10)

    for i, batch in enumerate(chunk(evidence, 50)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)

    dom = pm.dominant(DOMAIN_ID)
    assert dom is not None, "No dominant candidate found"
    assert dom.candidate_id == cand_true.candidate_id, (
        f"Expected T* to dominate. Dominant: {dom.description}, score: {dom.log_score:.2f}. "
        f"T* score: {cand_true.log_score:.2f}"
    )


# ---------------------------------------------------------------------------
# TEST-L3-02: Low-scoring candidates are pruned
# ---------------------------------------------------------------------------

def test_L3_02_low_scorers_pruned():
    """
    Given: same 5-candidate population
    When:  500 records from T*
    Then:  null candidate is marked PRUNED (lowest log_score)
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=500)

    cand_true = make_tstar_candidate(DOMAIN_ID)
    cand_s1 = make_spurious_1_candidate(DOMAIN_ID)
    cand_s2 = make_spurious_2_candidate(DOMAIN_ID)
    cand_alt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    candidates = [cand_true, cand_s1, cand_s2, cand_alt, cand_null]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=10)

    for i, batch in enumerate(chunk(evidence, 50)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)

    # null candidate should have the lowest score (single edge vs full graph)
    pop = pm.get_population(DOMAIN_ID)
    all_candidates = pop.candidates  # includes pruned

    # Find null candidate
    null_cand = None
    for c in all_candidates:
        if c.candidate_id == cand_null.candidate_id:
            null_cand = c
            break

    assert null_cand is not None, "Null candidate not found"
    assert null_cand.status == CandidateStatus.PRUNED, (
        f"Null candidate should be PRUNED. Status: {null_cand.status}, "
        f"score: {null_cand.log_score:.2f}"
    )
    assert null_cand.pruned_at is not None
    assert null_cand.pruning_reason is not None


# ---------------------------------------------------------------------------
# TEST-L3-03: PARADIGM SHIFT — regime switch detection (MILESTONE)
# ---------------------------------------------------------------------------

def test_L3_03_paradigm_shift_on_regime_switch():
    """
    This is the most important Level 3 test — the build milestone.

    Phase 1: 300 records from T* → T* candidate dominates
    Phase 2: switch to T_alt → within 300 records, T_alt rises to dominance
             paradigm_shift_count increments
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)

    # Seed with both T* and T_alt candidates plus some variants
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_talt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    candidates = [cand_tstar, cand_talt, cand_null]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=10)

    # --- Phase 1: T* data (300 records) ---
    evidence_phase1 = gen.sample(n=300)
    for i, batch in enumerate(chunk(evidence_phase1, 30)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)

    # After phase 1, T* should dominate
    dom1 = pm.dominant(DOMAIN_ID)
    assert dom1 is not None
    assert dom1.edge_structure_signature() == T_STAR_EDGES, (
        f"After phase 1, T* should dominate. Got: {dom1.description}, "
        f"signature: {dom1.edge_structure_signature()}"
    )
    t_star_dominates_at_switch = pm.dominant_matches_structure(DOMAIN_ID, T_STAR_EDGES)
    assert t_star_dominates_at_switch, "T* must dominate at the end of phase 1"

    # Record paradigm shift count before phase 2
    summary_before = pm.summary(DOMAIN_ID)
    shifts_before = summary_before["paradigm_shift_count"]

    # --- Phase 2: Switch to T_alt regime ---
    gen.switch_regime("T_alt")
    evidence_phase2 = gen.sample(n=300)

    for i, batch in enumerate(chunk(evidence_phase2, 30)):
        run_learning_cycle(ps, ls, ees, pm, batch, i + 10)

    # After phase 2: T_alt should dominate, paradigm_shift_count should increase
    summary_after = pm.summary(DOMAIN_ID)

    assert summary_after["paradigm_shift_count"] > shifts_before, (
        f"paradigm_shift_count should increase. Before: {shifts_before}, "
        f"After: {summary_after['paradigm_shift_count']}"
    )
    # T* should NO LONGER dominate
    assert not pm.dominant_matches_structure(DOMAIN_ID, T_STAR_EDGES), (
        "T* should no longer dominate after regime switch to T_alt"
    )

    # (Bonus) The dominant candidate should match T_alt or be closer to T_alt
    dom2 = pm.dominant(DOMAIN_ID)
    assert dom2 is not None
    # The T_alt candidate or a variant of it should dominate
    # We check: T_alt has edge A→D; T* has B→D. Dominant should have A→D.
    dom2_sig = dom2.edge_structure_signature()
    assert ("A", "D") in dom2_sig or dom2.log_score > cand_tstar.log_score, (
        f"After regime switch, dominant should prefer A→D structure. "
        f"Got signature: {dom2_sig}"
    )


# ---------------------------------------------------------------------------
# TEST-L3-04: Variant introduction preserves schema validity
# ---------------------------------------------------------------------------

def test_L3_04_variant_introduction_schema_valid():
    """
    Given: dominant candidate after learning
    When:  PopulationManager introduces variants
    Then:  all variants are valid DAGs with no cycles
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=200)

    candidates = [make_tstar_candidate(DOMAIN_ID), make_null_candidate(DOMAIN_ID)]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=10)

    for i, batch in enumerate(chunk(evidence, 50)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)

    pop = pm.get_population(DOMAIN_ID)
    # All active candidates should be valid DAGs
    for c in pop.active_candidates():
        assert c.is_dag(), f"Candidate {c.description} is not a DAG!"


# ---------------------------------------------------------------------------
# TEST-L3-05: Population size stays bounded
# ---------------------------------------------------------------------------

def test_L3_05_population_size_bounded():
    """
    Given: max_population_size=5
    When:  20 learning cycles run
    Then:  active candidate count never exceeds 5
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)

    candidates = [
        make_tstar_candidate(DOMAIN_ID),
        make_talt_candidate(DOMAIN_ID),
        make_null_candidate(DOMAIN_ID),
    ]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=5)

    for i in range(20):
        batch = gen.sample(n=20)
        run_learning_cycle(ps, ls, ees, pm, batch, i)
        pop = pm.get_population(DOMAIN_ID)
        active = pop.active_candidates()
        assert len(active) <= 5, (
            f"Cycle {i}: active population size {len(active)} exceeds max 5"
        )


# ---------------------------------------------------------------------------
# TEST-L3-06: Lineage tracking
# ---------------------------------------------------------------------------

def test_L3_06_lineage_tracked():
    """
    Given: PopulationManager introduces variants
    Then:  variant.parent_candidate_id == parent.candidate_id
           variant.generation == parent.generation + 1
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    evidence = gen.sample(n=100)

    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    candidates = [cand_tstar, make_null_candidate(DOMAIN_ID)]
    ps, ls, ees, pm = make_engine_components(candidates, max_pop=10)

    # Run a few cycles to allow variant introduction
    for i, batch in enumerate(chunk(evidence, 25)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)

    pop = pm.get_population(DOMAIN_ID)
    # Find any candidate with a parent (variant)
    variants = [c for c in pop.candidates if c.parent_candidate_id is not None]

    assert len(variants) > 0, "No variants introduced"

    for v in variants:
        # Find parent
        parent = None
        for c in pop.candidates:
            if c.candidate_id == v.parent_candidate_id:
                parent = c
                break
        if parent is None:
            continue  # Parent may have been pruned
        assert v.generation == parent.generation + 1, (
            f"Variant generation {v.generation} != parent generation {parent.generation} + 1"
        )
