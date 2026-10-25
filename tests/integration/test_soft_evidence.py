"""
Soft-evidence integration tests.

Tests cover:
    SE-01  Hard ObservedAssignment backward compatibility (no probabilities)
    SE-02  Probability validation — bad sum raises ValueError
    SE-03  Probability validation — good sum (exactly 1.0) passes
    SE-04  Probability validation — sum 0.99 within tolerance passes
    SE-05  Fractional count accumulation for a root variable (SOFT_OBSERVED)
    SE-06  Fractional count accumulation for a child with hard-observed parents
    SE-07  Soft evidence shifts log-likelihood vs missing evidence

Measured domains no longer give soft evidence: they read each signal as a
level, observed exactly (REFACTOR_SPEC D25), tested in each domain's own
ingestion tests. Soft evidence remains for testimony (art's reports).
"""
from __future__ import annotations

import sys
import os
import math
from datetime import date
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.engine.schemas import (
    DomainType,
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    OntologyCandidate,
    SourceType,
    Variable,
    DependencyEdge,
    DependencyKind,
)
from src.engine.services.learning import LearningService
from src.engine.stores.parameter_store import ParameterStore


# ---------------------------------------------------------------------------
# Minimal 2-variable candidate: A (root) → B
# ---------------------------------------------------------------------------

def _make_two_var_candidate():
    var_a = Variable(
        variable_id=uuid4(), name="A",
        domain_type=DomainType.BOOLEAN, support=[True, False],
    )
    var_b = Variable(
        variable_id=uuid4(), name="B",
        domain_type=DomainType.BOOLEAN, support=[True, False],
    )
    edge = DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=var_a.variable_id,
        child_variable_id=var_b.variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
    )
    candidate = OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id="test",
        variables=[var_a, var_b],
        edges=[edge],
    )
    return candidate, var_a, var_b


def _make_record(assignments: list[ObservedAssignment]) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=uuid4(),
        observed_assignments=assignments,
        source_type=SourceType.MANUAL,
    )


# ---------------------------------------------------------------------------
# SE-01  Hard assignment backward compatibility
# ---------------------------------------------------------------------------

def test_hard_assignment_no_probabilities():
    """
    An ObservedAssignment without probabilities (hard evidence) must
    serialize / deserialize without error and have probabilities=None.
    """
    vid = uuid4()
    a = ObservedAssignment(
        variable_id=vid,
        observed_value=True,
        missingness=MissingnessType.OBSERVED,
        confidence=1.0,
    )
    assert a.probabilities is None
    assert a.observed_value is True
    assert a.missingness == MissingnessType.OBSERVED

    # Round-trip via model_dump / model_validate
    d = a.model_dump()
    a2 = ObservedAssignment.model_validate(d)
    assert a2.probabilities is None
    assert a2.observed_value is True


# ---------------------------------------------------------------------------
# SE-02  Bad probability sum raises ValidationError
# ---------------------------------------------------------------------------

def test_bad_probability_sum_raises():
    vid = uuid4()
    with pytest.raises(Exception):   # pydantic ValidationError
        ObservedAssignment(
            variable_id=vid,
            observed_value=True,
            missingness=MissingnessType.SOFT_OBSERVED,
            confidence=1.0,
            probabilities={True: 0.7, False: 0.5},   # sum=1.2 → invalid
        )


# ---------------------------------------------------------------------------
# SE-03 / SE-04  Probability validation edge cases
# ---------------------------------------------------------------------------

def test_probability_sum_exactly_one_passes():
    vid = uuid4()
    a = ObservedAssignment(
        variable_id=vid,
        observed_value=True,
        missingness=MissingnessType.SOFT_OBSERVED,
        confidence=1.0,
        probabilities={True: 0.64, False: 0.36},
    )
    total = sum(a.probabilities.values())
    assert abs(total - 1.0) < 1e-9


def test_probability_sum_within_tolerance_passes():
    """Sum 0.99 (rounding artefact) is within the ±0.02 tolerance."""
    vid = uuid4()
    a = ObservedAssignment(
        variable_id=vid,
        observed_value=True,
        missingness=MissingnessType.SOFT_OBSERVED,
        confidence=1.0,
        probabilities={True: 0.99, False: 0.0},  # sum=0.99
    )
    assert a.probabilities is not None


# ---------------------------------------------------------------------------
# SE-05  Fractional count accumulation — root variable
# ---------------------------------------------------------------------------

def test_soft_root_variable_fractional_counts():
    """
    A soft observation P(A=True)=0.7 on a root variable should accumulate
    0.7 fractional count for True and 0.3 for False.
    """
    candidate, var_a, var_b = _make_two_var_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)

    # Soft evidence on A only; B is absent (MISSING from record perspective)
    a_assign = ObservedAssignment(
        variable_id=var_a.variable_id,
        observed_value=True,
        missingness=MissingnessType.SOFT_OBSERVED,
        confidence=1.0,
        probabilities={True: 0.7, False: 0.3},
    )
    record = _make_record([a_assign])

    ls.accumulate([record], candidate)

    cpt_a = ps.get(candidate.candidate_id, "A")
    # Root CPT is stored under () config
    counts_true = cpt_a.row({}).get(True, 0.0)
    counts_false = cpt_a.row({}).get(False, 0.0)

    assert abs(counts_true - 0.7) < 1e-9, (
        f"Expected 0.7 fractional True count, got {counts_true}"
    )
    assert abs(counts_false - 0.3) < 1e-9, (
        f"Expected 0.3 fractional False count, got {counts_false}"
    )


# ---------------------------------------------------------------------------
# SE-06  Fractional count accumulation — child with hard parent
# ---------------------------------------------------------------------------

def test_soft_child_with_hard_parent_fractional_counts():
    """
    Hard A=True, soft B with P(B=True)=0.6.
    Under parent config A=True, B should accumulate 0.6 True and 0.4 False.
    """
    candidate, var_a, var_b = _make_two_var_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)

    a_assign = ObservedAssignment(
        variable_id=var_a.variable_id,
        observed_value=True,
        missingness=MissingnessType.OBSERVED,
        confidence=1.0,
    )
    b_assign = ObservedAssignment(
        variable_id=var_b.variable_id,
        observed_value=True,
        missingness=MissingnessType.SOFT_OBSERVED,
        confidence=1.0,
        probabilities={True: 0.6, False: 0.4},
    )
    record = _make_record([a_assign, b_assign])

    ls.accumulate([record], candidate)

    cpt_b = ps.get(candidate.candidate_id, "B")
    row = cpt_b.row({"A": True})

    assert abs(row.get(True, 0.0) - 0.6) < 1e-9, (
        f"Expected 0.6 fractional True count for B|A=True, got {row}"
    )
    assert abs(row.get(False, 0.0) - 0.4) < 1e-9, (
        f"Expected 0.4 fractional False count for B|A=True, got {row}"
    )


# ---------------------------------------------------------------------------
# SE-07  Soft evidence produces non-zero log-likelihood; MISSING produces zero
# ---------------------------------------------------------------------------

def test_soft_evidence_log_likelihood_differs_from_missing():
    """
    A record with all-MISSING assignments contributes exactly 0.0 to the
    log-likelihood (nothing observed, nothing learned from).

    A record with SOFT_OBSERVED assignments contributes a non-zero expected
    log-likelihood even when both variables are soft, because the observation
    distribution weights each outcome.

    Additionally: a soft observation that closely matches the learned model
    (high probability on the likely outcome) should yield a higher expected
    log-likelihood than one that places high probability on the unlikely outcome.
    """
    candidate, var_a, var_b = _make_two_var_candidate()
    ps = ParameterStore()
    ls = LearningService(ps)
    ls.initialize_candidate(candidate)

    # Train on 10 records each: A=True→B=True and A=False→B=False
    # This gives balanced priors and strong conditional structure.
    for val in [True, False]:
        for _ in range(10):
            ls.accumulate([_make_record([
                ObservedAssignment(
                    variable_id=var_a.variable_id,
                    observed_value=val,
                    missingness=MissingnessType.OBSERVED,
                ),
                ObservedAssignment(
                    variable_id=var_b.variable_id,
                    observed_value=val,
                    missingness=MissingnessType.OBSERVED,
                ),
            ])], candidate)

    # After training: P(A=True) ≈ 0.5, P(B=T|A=T) ≈ 1, P(B=F|A=F) ≈ 1

    # --- all-MISSING record → LL must be exactly 0.0 ---
    all_missing = _make_record([
        ObservedAssignment(
            variable_id=var_a.variable_id,
            observed_value=False,
            missingness=MissingnessType.MISSING,
            confidence=0.0,
        ),
        ObservedAssignment(
            variable_id=var_b.variable_id,
            observed_value=False,
            missingness=MissingnessType.MISSING,
            confidence=0.0,
        ),
    ])
    ll_all_missing = ls.compute_log_likelihood([all_missing], candidate)
    assert ll_all_missing == 0.0, (
        f"All-MISSING record should yield LL=0.0, got {ll_all_missing}"
    )

    # --- model-aligned soft record: P(A=True)=0.9, P(B=True)=0.9 ---
    # High-probability outcome matches the A=True training cluster.
    soft_aligned = _make_record([
        ObservedAssignment(
            variable_id=var_a.variable_id,
            observed_value=True,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: 0.9, False: 0.1},
        ),
        ObservedAssignment(
            variable_id=var_b.variable_id,
            observed_value=True,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: 0.9, False: 0.1},
        ),
    ])

    # --- model-opposed soft record: P(A=True)=0.1, P(B=True)=0.9 ---
    # Mismatch: A mostly False but B mostly True → P(B=T|A=F) is small.
    soft_opposed = _make_record([
        ObservedAssignment(
            variable_id=var_a.variable_id,
            observed_value=False,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: 0.1, False: 0.9},
        ),
        ObservedAssignment(
            variable_id=var_b.variable_id,
            observed_value=True,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: 0.9, False: 0.1},
        ),
    ])

    ll_aligned = ls.compute_log_likelihood([soft_aligned], candidate)
    ll_opposed = ls.compute_log_likelihood([soft_opposed], candidate)

    assert ll_aligned != 0.0, "Soft-aligned record must produce non-zero LL"
    assert ll_opposed != 0.0, "Soft-opposed record must produce non-zero LL"
    assert ll_aligned > ll_opposed, (
        f"Model-aligned soft evidence (ll={ll_aligned:.4f}) should score higher "
        f"than model-opposed soft evidence (ll={ll_opposed:.4f})"
    )
