"""Five ordered levels (REFACTOR_SPEC D20): a signal's degree, in steps from
well below its threshold to far past it. The three levels past the threshold
together are exactly the old probability of "true", so the levels are a
finer cut of the same evidence."""
import math

import pytest

from src.engine.model.levels import LEVELS, PAST, levels_from_p, p_past


@pytest.mark.parametrize("p", [0.01, 0.2, 0.5, 0.73, 0.99])
def test_levels_are_a_distribution_whose_past_share_is_the_old_probability(p):
    dist = levels_from_p(p)
    assert set(dist) == set(LEVELS)
    assert abs(sum(dist.values()) - 1) < 1e-12
    assert abs(p_past(dist) - p) < 1e-12


def test_a_signal_at_its_threshold_sits_either_side_of_it():
    dist = levels_from_p(0.5)
    assert abs(dist["below"] - dist["past"]) < 1e-12
    assert max(dist, key=dist.get) in ("below", "past")


def test_a_strong_signal_is_far_past():
    dist = levels_from_p(0.99)
    assert max(dist, key=dist.get) == "extreme"


def test_a_weak_signal_is_well_below():
    assert max(levels_from_p(0.01), key=levels_from_p(0.01).get) == "well_below"


def test_the_levels_past_the_threshold():
    assert PAST == ("past", "well_past", "extreme")
    assert LEVELS[:2] == ("well_below", "below")


def test_the_parameter_count_is_unchanged_for_booleans_and_counts_levels():
    from src.domains.sources.structure import boolean_variables, level_variables, seed_edge
    from src.engine.model.scoring import free_parameter_count
    from src.engine.schemas import OntologyCandidate
    b = boolean_variables("m", ["A", "B", "C"])
    cand = OntologyCandidate(domain_module_id="m", variables=list(b.values()),
                             edges=[seed_edge(b, "A", "C", 0.5), seed_edge(b, "B", "C", 0.5)])
    assert free_parameter_count(cand) == 1 + 1 + 4          # as before: 2**parents per boolean
    v = level_variables("m", ["A", "B"])
    cand = OntologyCandidate(domain_module_id="m", variables=list(v.values()), edges=[seed_edge(v, "A", "B", 0.5)])
    assert free_parameter_count(cand) == 4 + 4 * 5          # (5 − 1) free per row; A has 1 row, B has 5


def test_a_level_record_carries_the_finer_cut_of_the_same_evidence():
    from datetime import date
    from src.domains.sources.soft_evidence import build_soft_record
    from src.domains.sources.structure import level_variables
    v = level_variables("m", ["A"])
    r = build_soft_record(module_id="m", variables=v, states=[("A", True, 0.88)], confidence={},
                          target_date=date(2024, 1, 7), source_ref="x", levels=True)
    [a] = r.observed_assignments
    assert set(a.probabilities) == set(LEVELS) and abs(p_past(a.probabilities) - 0.88) < 1e-12
    assert a.observed_value == max(a.probabilities, key=a.probabilities.get)


def test_the_macro_domain_records_levels():
    from src.domains.macro_regime_v1.domain import get_variables
    assert all(tuple(v.support) == LEVELS for v in get_variables().values())


def test_the_dashboard_probability_is_past_the_threshold():
    from src.engine.api.presenters import p_true
    assert abs(p_true({"well_below": 0.1, "below": 0.2, "past": 0.3, "well_past": 0.3, "extreme": 0.1}) - 0.7) < 1e-12
    assert p_true({"True": 0.8, "False": 0.2}) == 0.8
