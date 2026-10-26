"""Levels of degree (REFACTOR_SPEC D25): a measured signal is read as low,
middle or high, observed exactly, rather than as a doubt about a yes/no."""
from __future__ import annotations

from datetime import date

import pytest

from src.domains.sources.grades import LEVELS, build_graded_record, graded_variables, level_of
from src.domains.sources.structure import with_lags
from src.engine.model.errors import EvidenceUnavailable
from src.engine.schemas import DomainType, MissingnessType


def test_a_signal_more_than_half_a_unit_from_its_line_is_low_or_high():
    assert [level_of(s) for s in (-0.51, -0.5, 0.0, 0.5, 0.51)] == ["low", "mid", "mid", "mid", "high"]


def test_graded_variables_are_ordered_levels_and_so_are_their_lags():
    variables = with_lags("m", graded_variables("m", ["A"]))
    for v in variables.values():
        assert v.domain_type == DomainType.ORDINAL
        assert v.support == list(LEVELS) == ["low", "mid", "high"]


def test_a_graded_record_observes_each_level_exactly_and_records_no_input_as_missing():
    variables = graded_variables("m", ["A", "B", "C"])
    record = build_graded_record(module_id="m", variables=variables, signals={"A": 1.2, "B": -0.2},
                                 confidence={}, target_date=date(2026, 3, 1), source_ref="s")
    by_id = {a.variable_id: a for a in record.observed_assignments}
    a, b, c = (by_id[variables[n].variable_id] for n in "ABC")
    assert (a.missingness, a.observed_value, a.probabilities) == (MissingnessType.OBSERVED, "high", None)
    assert (b.missingness, b.observed_value) == (MissingnessType.OBSERVED, "mid")
    assert (c.missingness, c.observed_value) == (MissingnessType.MISSING, None)


def test_a_graded_record_with_no_input_at_all_is_unavailable():
    variables = graded_variables("m", ["A"])
    with pytest.raises(EvidenceUnavailable):
        build_graded_record(module_id="m", variables=variables, signals={}, confidence={},
                            target_date=date(2026, 3, 1), source_ref="s")


def test_a_source_can_observe_last_periods_level_itself():
    # A yearly figure is MISSING eleven months in twelve, so the source gives
    # last year's value (art plan §7); the engine keeps it (model/temporal.py).
    variables = with_lags("m", graded_variables("m", ["A", "B"]))
    record = build_graded_record(module_id="m", variables=variables, signals={"A": 1.2, "B": 0.0},
                                 previous={"A": -0.9}, confidence={}, target_date=date(2026, 4, 1), source_ref="s")
    by_id = {a.variable_id: a for a in record.observed_assignments}
    lag = by_id[variables["A_prev"].variable_id]
    assert (lag.missingness, lag.observed_value) == (MissingnessType.OBSERVED, "low")
    assert variables["B_prev"].variable_id not in by_id   # left to the engine, as before
