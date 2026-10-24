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
        log_lik = ls.compute_log_likelihood(batch, candidate)  # before learning it, as the engine does
        ls.accumulate(batch, candidate)
        ees.update(candidate)
        ees.prune_below_threshold(candidate, ps)
        pm.update_score(DOMAIN_ID, candidate.candidate_id, log_lik, batch_idx, batch_size=len(batch))

    pm.prune_low_scorers(DOMAIN_ID)
    pm.introduce_variants(DOMAIN_ID)
    pm.end_cycle(DOMAIN_ID, evidence_ts=max(r.timestamp for r in batch))


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

def _l3_03_succeeds(seed: int) -> bool:
    """SPEC §20.6 on one seed: T* dominates after 300 T* records, then within
    200 records of the switch an A->D structure takes over and a shift is logged."""
    gen = SyntheticDataGenerator(graph="T*", random_seed=seed)
    cands = [make_tstar_candidate(DOMAIN_ID), make_talt_candidate(DOMAIN_ID), make_null_candidate(DOMAIN_ID)]
    ps, ls, ees, pm = make_engine_components(cands, max_pop=10)

    for i, batch in enumerate(chunk(gen.sample(n=300), 30)):
        run_learning_cycle(ps, ls, ees, pm, batch, i)
    if not pm.dominant_matches_structure(DOMAIN_ID, T_STAR_EDGES):
        return False
    shifts_before = pm.summary(DOMAIN_ID)["paradigm_shift_count"]

    gen.switch_regime("T_alt")
    for i, batch in enumerate(chunk(gen.sample(n=180), 30)):
        run_learning_cycle(ps, ls, ees, pm, batch, 10 + i)
        dom = pm.dominant(DOMAIN_ID).edge_structure_signature()
        if dom != T_STAR_EDGES and ("A", "D") in dom:
            return pm.summary(DOMAIN_ID)["paradigm_shift_count"] > shifts_before
    return False


def test_L3_03_paradigm_shift_on_regime_switch():
    """
    This is the most important Level 3 test — the build milestone.

    Run on 20 seeds and required on at least 16: one seed passing measured the
    seed, not the engine (REFACTOR_SPEC D14). Seeds 0-19 passed 18 when the
    rate was introduced.
    """
    successes = sum(_l3_03_succeeds(seed) for seed in range(20))
    assert successes >= 16, f"paradigm shift detected on {successes}/20 seeds, need 16"


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
