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
    SE-08  Credit cycle pipeline: no-data fallback yields p=0.5 for all variables
    SE-09  Natural gas soft assignments carry valid probability distributions
    SE-10  Soft assignment MAP value matches hard boolean
    SE-11  Sovereign debt pipeline: high yield spike gives P(USYieldSpiking) > 0.5
    SE-12  Labor market pipeline: rising unemployment gives P(UnemploymentRising) > 0.9
    SE-13  Credit cycle snapshot: all 8 variables SOFT_OBSERVED with clamped probs
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
    counts_true = cpt_a.counts.get((), {}).get(True, 0.0)
    counts_false = cpt_a.counts.get((), {}).get(False, 0.0)

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
    parent_cfg = (("A", True),)
    row = cpt_b.counts.get(parent_cfg, {})

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


# ---------------------------------------------------------------------------
# SE-08  Credit cycle pipeline: no-data fallback yields p=0.5 for all variables
# ---------------------------------------------------------------------------

def test_credit_cycle_no_data_fallback_is_uniform():
    """
    When compute_snapshot receives empty observations, every variable must fall
    back to p=0.5 (maximum uncertainty), not a false deterministic observation.
    """
    from src.domains.credit_cycle_v1.ingestion.pipeline import compute_snapshot
    from datetime import date as _date

    snapshot = compute_snapshot({}, _date(2024, 5, 3))
    for attr in [
        "p_hy_spread_elevated", "p_leveraged_loan_stress", "p_corporate_default_risk",
        "p_credit_impulse_negative", "p_bank_lending_tightening",
        "p_investment_grade_spread", "p_high_yield_issuance_falling", "p_refinancing_stress",
    ]:
        val = getattr(snapshot, attr)
        assert val == 0.5, (
            f"No-data fallback: {attr}={val:.3f} should be 0.5 (max uncertainty)."
        )


# ---------------------------------------------------------------------------
# SE-09  Natural gas soft assignments carry valid probability distributions
# ---------------------------------------------------------------------------

def test_natural_gas_soft_assignments_valid_distributions():
    """All four NatGas assignments are SOFT_OBSERVED with valid distributions."""
    from src.domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline
    from src.domains.natural_gas_v1.ingestion.eia_client import NatGasSnapshot
    from src.domains.natural_gas_v1.ingestion.noaa_client import (
        DailyClimateObs, MONTHLY_NORMALS_C, HDD_BASE_C,
    )
    from src.domains.natural_gas_v1.domain import get_variables

    target = date(2025, 1, 15)
    temp_c = 0.0
    hdd = max(0.0, HDD_BASE_C - temp_c)
    normal = MONTHLY_NORMALS_C[target.month]

    climate = DailyClimateObs(
        target_date=target,
        mean_temp_c=temp_c,
        hdd=hdd,
        temp_anom=temp_c > normal,
        heating_dem=hdd > 0.0,
        stations_used=5,
        station_means={"KORD": temp_c},
    )
    gas = NatGasSnapshot(
        storage_current_bcf=1900.0,
        storage_prev_bcf=2000.0,
        storage_change_bcf=-100.0,
        storage_draw=True,
        latest_price=5.0,
        median_price=4.0,
        price_up=True,
    )

    record = NaturalGasPipeline.build_evidence_record(climate, gas)
    variables = get_variables()
    amap = {a.variable_id: a for a in record.observed_assignments}

    for var_name in ("TempAnom", "HeatingDem", "StorageDraw", "PriceUp"):
        a = amap[variables[var_name].variable_id]
        assert a.missingness == MissingnessType.SOFT_OBSERVED, (
            f"{var_name}: expected SOFT_OBSERVED, got {a.missingness}"
        )
        assert a.probabilities is not None, f"{var_name} must have probabilities"
        total = sum(a.probabilities.values())
        assert abs(total - 1.0) < 0.02, (
            f"{var_name} probs sum to {total:.4f}, not 1.0"
        )
        for val, p in a.probabilities.items():
            assert 0.01 <= p <= 0.99, (
                f"{var_name} probability {p:.4f} is outside [0.01, 0.99]"
            )


# ---------------------------------------------------------------------------
# SE-10  Soft assignment MAP value matches hard boolean
# ---------------------------------------------------------------------------

def test_soft_assignment_map_value_matches_boolean():
    """
    For SOFT_OBSERVED assignments, observed_value should equal the MAP
    (highest-probability) value from the distribution.
    """
    from src.domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline
    from src.domains.natural_gas_v1.ingestion.eia_client import NatGasSnapshot
    from src.domains.natural_gas_v1.ingestion.noaa_client import (
        DailyClimateObs, MONTHLY_NORMALS_C, HDD_BASE_C,
    )
    from src.domains.natural_gas_v1.domain import get_variables

    target = date(2025, 1, 15)
    temp_c = 10.0  # above January normal (1.5°C) → TempAnom=True expected
    hdd = max(0.0, HDD_BASE_C - temp_c)
    normal = MONTHLY_NORMALS_C[target.month]

    climate = DailyClimateObs(
        target_date=target,
        mean_temp_c=temp_c,
        hdd=hdd,
        temp_anom=temp_c > normal,
        heating_dem=hdd > 0.0,
        stations_used=5,
        station_means={"KORD": temp_c},
    )
    gas = NatGasSnapshot(
        storage_current_bcf=2100.0,
        storage_prev_bcf=2000.0,
        storage_change_bcf=100.0,
        storage_draw=False,
        latest_price=3.0,
        median_price=4.0,
        price_up=False,
    )
    record = NaturalGasPipeline.build_evidence_record(climate, gas)
    variables = get_variables()
    amap = {a.variable_id: a for a in record.observed_assignments}

    for var_name, expected_map in [
        ("TempAnom", True),    # 10°C well above 1.5°C normal
        ("StorageDraw", False),  # 100 Bcf build, not a draw
        ("PriceUp", False),    # 3.0 < 4.0 median
    ]:
        a = amap[variables[var_name].variable_id]
        assert a.observed_value == expected_map, (
            f"{var_name}: MAP boolean should be {expected_map}, got {a.observed_value}"
        )
        probs = a.probabilities
        map_from_probs = max(probs.items(), key=lambda kv: kv[1])[0]
        assert map_from_probs == expected_map, (
            f"{var_name}: MAP from probabilities {probs} is {map_from_probs}, "
            f"expected {expected_map}"
        )


# ---------------------------------------------------------------------------
# SE-11  Sovereign debt: DGS10 well above 2-year mean → P(USYieldSpiking) > 0.5
# ---------------------------------------------------------------------------

def test_sovereign_debt_high_yield_produces_high_spiking_probability():
    """
    DGS10 at 5.5 with 2yr mean of 3.5 (z≈+2) → P(USYieldSpiking=True) > 0.5.
    """
    from src.domains.sovereign_debt_v1.ingestion.pipeline import (
        _compute_us_yield_spiking,
        _soft_bool,
    )
    from src.domains.sovereign_debt_v1.ingestion.fred_client import FREDObservation

    # 400 observations: mean ~3.5, latest 5.5
    obs = [
        FREDObservation(
            obs_date=date(2024, 5, 3) - __import__("datetime").timedelta(days=i),
            value=(5.5 if i == 0 else 3.5),
            series_id="DGS10",
        )
        for i in range(400)
    ]
    sig, _ = _compute_us_yield_spiking(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.5, f"High DGS10 should yield P(USYieldSpiking)>0.5, got {p:.3f}"


# ---------------------------------------------------------------------------
# SE-12  Labor market: rising unemployment gives P(UnemploymentRising) > 0.9
# ---------------------------------------------------------------------------

def test_labor_market_rising_unemployment_high_probability():
    """
    UNRATE at 5.0 vs 12-month mean of 4.0 (z≈+1pp) → P(UnemploymentRising) > 0.9.
    """
    from src.domains.labor_market_v1.ingestion.pipeline import (
        _compute_unemployment_rising,
        _soft_bool,
    )
    from src.domains.labor_market_v1.ingestion.fred_client import FREDObservation

    obs = [
        FREDObservation(
            obs_date=date(2024, 5, 3) - __import__("datetime").timedelta(days=i * 30),
            value=(5.0 if i == 0 else 4.0),
            series_id="UNRATE",
        )
        for i in range(15)
    ]
    sig, _ = _compute_unemployment_rising(obs)
    assert sig is not None
    p = _soft_bool(sig)
    assert p > 0.9, f"1pp unemployment rise should yield P>0.9, got {p:.3f}"


# ---------------------------------------------------------------------------
# SE-13  Credit cycle: full snapshot produces 8 SOFT_OBSERVED clamped assignments
# ---------------------------------------------------------------------------

def test_credit_cycle_full_snapshot_all_soft_observed():
    """
    With full observations, CreditCyclePipeline.build_evidence_record must yield
    8 SOFT_OBSERVED assignments all with probabilities clamped to [0.01, 0.99].
    """
    import numpy as np
    from src.domains.credit_cycle_v1.ingestion.pipeline import (
        CreditCyclePipeline,
        compute_snapshot,
    )
    from src.domains.credit_cycle_v1.ingestion.fred_client import FREDObservation

    target = date(2024, 5, 3)
    rng = np.random.default_rng(0)

    hy_values = rng.normal(4.5, 0.3, 260).tolist()
    hy_values[0] = 4.5
    hy_obs = [
        FREDObservation(obs_date=target - __import__("datetime").timedelta(days=i), value=hy_values[i], series_id="BAMLH0A0HYM2")
        for i in range(260)
    ]
    totci_obs = [
        FREDObservation(obs_date=target - __import__("datetime").timedelta(days=i * 30), value=(1_000.0 if i == 0 else 1_020.0), series_id="TOTCI")
        for i in range(6)
    ]
    dgs5_obs = [
        FREDObservation(obs_date=target - __import__("datetime").timedelta(days=i), value=4.2, series_id="DGS5")
        for i in range(260)
    ]
    ig_values = rng.normal(1.2, 0.1, 260).tolist()
    ig_values[0] = 1.2
    ig_obs = [
        FREDObservation(obs_date=target - __import__("datetime").timedelta(days=i), value=ig_values[i], series_id="BAMLC0A0CM")
        for i in range(260)
    ]
    drtscilm_obs = [
        FREDObservation(obs_date=target - __import__("datetime").timedelta(days=i * 90), value=5.0, series_id="DRTSCILM")
        for i in range(20)
    ]

    observations = {
        "BAMLH0A0HYM2": hy_obs,
        "DRTSCILM": drtscilm_obs,
        "TOTCI": totci_obs,
        "BAMLC0A0CM": ig_obs,
        "DGS5": dgs5_obs,
    }
    snapshot = compute_snapshot(observations, target)
    record = CreditCyclePipeline.build_evidence_record(snapshot)

    assert len(record.observed_assignments) == 8
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED, (
            f"{a.variable_id}: expected SOFT_OBSERVED, got {a.missingness}"
        )
        assert a.probabilities is not None
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99, (
            f"{a.variable_id}: P(True)={p_true:.4f} is outside [0.01, 0.99]"
        )
