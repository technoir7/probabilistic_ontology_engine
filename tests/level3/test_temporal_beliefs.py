"""Beliefs about change (REFACTOR_SPEC D19): a domain may give each variable
a companion holding last period's value, which can only be a parent. It is
taken from the previous record when learning, scored never (it was scored
last period), and the macro domain adds a rival programme that holds things
persist."""
from datetime import datetime, timedelta

from src.domains.macro_regime_v1.domain import MacroRegimeV1, get_variables, get_variables_with_lags
from src.domains.sources.structure import boolean_variables, with_lags
from src.engine.engine import ProbabilisticOntologyEngine, _derive_admissible_edges
from src.engine.model.temporal import lag_name, lagged
from src.engine.schemas import EvidenceRecord, MissingnessType, ObservedAssignment


def test_each_variable_gets_a_companion_for_last_period():
    variables = with_lags("m", boolean_variables("m", ["A", "B"]))
    assert set(variables) == {"A", "B", "A_prev", "B_prev"}
    assert variables["A_prev"].lag_of == "A" and variables["A"].lag_of is None
    assert with_lags("m", boolean_variables("m", ["A"]))["A_prev"].variable_id == variables["A_prev"].variable_id


def record(variables, values, day):
    return EvidenceRecord(timestamp=datetime(2024, 1, 1) + timedelta(days=day), observed_assignments=[
        ObservedAssignment(variable_id=variables[n].variable_id, observed_value=v) for n, v in values.items()])


def test_last_periods_values_come_from_the_previous_record():
    v = with_lags("m", boolean_variables("m", ["A", "B"]))
    first, second = record(v, {"A": True, "B": False}, 0), record(v, {"A": False, "B": False}, 7)
    out = lagged([second], first, list(v.values()))
    got = {a.variable_id: a.observed_value for a in out[0].observed_assignments}
    assert got[v["A_prev"].variable_id] is True and got[v["B_prev"].variable_id] is False
    assert got[v["A"].variable_id] is False


def test_within_a_batch_each_record_lags_the_one_before():
    v = with_lags("m", boolean_variables("m", ["A"]))
    recs = [record(v, {"A": x}, i) for i, x in enumerate([True, False, True])]
    out = lagged(recs, None, list(v.values()))
    lag = v["A_prev"].variable_id
    assert [next(a for a in r.observed_assignments if a.variable_id == lag).missingness for r in out][0] == MissingnessType.MISSING
    assert [next(a.observed_value for a in r.observed_assignments if a.variable_id == lag) for r in out[1:]] == [True, False]


def test_a_domain_without_lags_is_untouched():
    v = boolean_variables("m", ["A"])
    r = record(v, {"A": True}, 0)
    assert lagged([r], None, list(v.values())) == [r]


def test_nothing_points_into_last_period():
    engine = ProbabilisticOntologyEngine(db_path=":memory:")
    admissible = _derive_admissible_edges(MacroRegimeV1().initial_candidates())
    assert all(not child.endswith("_prev") for _, child in admissible)
    assert ("InflationShock_prev", "InflationShock") in admissible
    assert ("InflationShock_prev", "DollarStrength") in admissible


def test_the_macro_domain_has_a_persistence_programme():
    seeds = MacroRegimeV1().initial_candidates()
    [persistence] = [c for c in seeds if c.description.startswith("T_persistence")]
    names = {v.variable_id: v.name for v in persistence.variables}
    assert {(names[e.parent_variable_id], names[e.child_variable_id]) for e in persistence.edges} == {
        (f"{n}_prev", n) for n in get_variables()}


def test_last_periods_values_are_never_scored():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(MacroRegimeV1())
    leader = engine.population_manager.dominant("macro-regime-v1")
    v = get_variables_with_lags()
    current = {n: "past" for n in v if not n.endswith("_prev")}
    without = record(v, current, 0)
    with_prev = record(v, {**current, **{f"{n}_prev": "below" for n in current}}, 0)
    ls = engine.learning_service
    assert ls.compute_log_likelihood([without], leader) == ls.compute_log_likelihood([with_prev], leader)


def test_the_engine_learns_with_last_periods_values():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(MacroRegimeV1())
    engine.activate_domain("macro-regime-v1")
    v = get_variables_with_lags()
    names = [n for n in v if not n.endswith("_prev")]
    levels = v[names[0]].support
    for week in range(6):
        engine.learn([record(v, {n: levels[(week + i) % len(levels)] for i, n in enumerate(names)}, 7 * week)])
    pop = engine.population_manager.get_population("macro-regime-v1")
    [persistence] = [c for c in pop.candidates if c.lineage == "T_persistence" and c.generation == 0]
    cpt = engine.parameter_store.get(persistence.candidate_id, "InflationShock")
    assert cpt.parents == ["InflationShock_prev"] and cpt.total_count() >= 5
    assert engine.epistemic_health("macro-regime-v1")["last_cycle"]["forecast_ll"] <= 0
