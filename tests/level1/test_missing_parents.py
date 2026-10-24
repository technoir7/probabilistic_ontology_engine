"""A variable whose parent was not observed is still scored, under its
probability given the parents that were (REFACTOR_SPEC D23). Skipping it
scored it as certain: zero log-loss, a free week for every candidate with
that parent, which in replay 10 decided which programmes survived."""
import math
from datetime import datetime, timezone

from src.domains.macro_regime_v1.domain import MacroRegimeV1, get_variables_with_lags
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.cpt import CPTData
from src.engine.schemas import EvidenceRecord, ObservedAssignment


def table():
    return CPTData(variable_name="X", parents=["A", "B"], support=[True, False], counts={
        (("A", True), ("B", True)): {True: 8, False: 2},
        (("A", True), ("B", False)): {True: 1, False: 1},
        (("A", False), ("B", True)): {True: 0, False: 4},
    })


def test_an_unknown_parent_is_averaged_over_as_the_data_has_seen_it():
    # P(X | A=True), B unknown: the A=True rows pooled, 9 of 12, smoothed.
    assert table().get_probability_given(True, {"A": True}) == (9 + 1) / (12 + 2)


def test_with_every_parent_known_nothing_changes():
    t = table()
    known = {"A": True, "B": False}
    assert t.get_probability_given(True, known) == t.get_probability(True, known)


def test_with_no_parent_known_it_is_the_variables_marginal():
    assert table().get_probability_given(False, {}) == (7 + 1) / (16 + 2)


def record(values):
    v = get_variables_with_lags()
    return EvidenceRecord(timestamp=datetime(2024, 1, 7, tzinfo=timezone.utc), observed_assignments=[
        ObservedAssignment(variable_id=v[name].variable_id, observed_value=value) for name, value in values.items()])


def persistence_candidate(engine):
    """Each signal following its own last week, with even tables."""
    from uuid import uuid4
    from src.engine.schemas import DependencyEdge, DependencyKind, OntologyCandidate
    v = get_variables_with_lags()
    edges = [DependencyEdge(edge_id=uuid4(), parent_variable_id=v[f"{n}_prev"].variable_id,
                            child_variable_id=v[n].variable_id, dependency_kind=DependencyKind.DIRECTED_CONDITIONAL)
             for n in v if not n.endswith("_prev")]
    c = OntologyCandidate(candidate_id=uuid4(), domain_module_id="macro-regime-v1",
                          variables=list(v.values()), edges=edges)
    engine.learning_service.initialize_candidate(c)
    return c


def test_the_first_week_is_scored_without_last_weeks_values():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(MacroRegimeV1())
    current = {n: True for n in get_variables_with_lags() if not n.endswith("_prev")}
    ll = engine.learning_service.compute_log_likelihood([record(current)], persistence_candidate(engine))
    assert math.isclose(ll, 8 * math.log(0.5))  # even tables: one bit a signal, not zero


def test_last_weeks_values_alone_are_not_scored():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(MacroRegimeV1())
    lags = {n: True for n in get_variables_with_lags() if n.endswith("_prev")}
    assert engine.learning_service.compute_log_likelihood([record(lags)], persistence_candidate(engine)) == 0.0
