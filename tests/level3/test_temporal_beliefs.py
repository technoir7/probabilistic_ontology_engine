"""Beliefs about change (REFACTOR_SPEC D19): a domain may give each variable
a companion holding last period's value, which can only be a parent. It is
taken from the previous record when learning, and scored never (it was
scored last period). That things persist is not assumed: the engine must
find it in the evidence (D24)."""
from datetime import datetime, timedelta

from src.domains.macro_regime_v1.domain import MacroRegimeV1, get_variables, get_variables_with_lags
from src.domains.sources.structure import boolean_variables, with_lags
from src.engine.engine import ProbabilisticOntologyEngine, _admissible_edges
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
    admissible = _admissible_edges(MacroRegimeV1().variables())
    assert all(not child.endswith("_prev") for _, child in admissible)
    assert ("InflationShock_prev", "InflationShock") in admissible
    assert ("InflationShock_prev", "DollarStrength") in admissible


def test_every_domain_but_the_synthetic_one_has_last_periods_values():
    from src.engine.runtime.registry import REGISTRY
    for r in REGISTRY:
        variables = r.build_domain().variables()
        signals = {v.name for v in variables if not v.lag_of}
        assert {v.lag_of for v in variables if v.lag_of} == signals, r.module_id


def persisting_weeks(n, seed=0):
    """Each signal keeps last week's level nine times in ten, independently."""
    import random
    from src.domains.sources.grades import LEVELS
    rng = random.Random(seed)
    v = get_variables_with_lags()
    names = [name for name in v if not name.endswith("_prev")]
    state = {name: rng.choice(LEVELS) for name in names}
    out = []
    for week in range(n):
        state = {name: x if rng.random() < 0.9 else rng.choice([lv for lv in LEVELS if lv != x])
                 for name, x in state.items()}
        out.append(record(v, state, 7 * week))
    return out


def test_persistence_is_found_in_the_evidence_not_given():
    # D23 gave every programme persistence as an assumption; with no
    # hypotheses given (D24), the engine must find it, and it is what the
    # evidence most prompts when signals persist and are otherwise unrelated.
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=0)
    engine.register_domain(MacroRegimeV1())
    engine.activate_domain("macro-regime-v1")
    weeks = persisting_weeks(60)
    engine.learn(weeks[:30])
    pop = engine.population_manager.get_population("macro-regime-v1")
    [prompted] = [c for c in pop.candidates if c.description.startswith("prompted_add_")]
    (parent, child), = prompted.edge_structure_signature()
    assert parent == f"{child}_prev"
    cpt = engine.parameter_store.get(prompted.candidate_id, child)
    assert cpt.parents == [parent]
    engine.learn(weeks[30:])
    assert cpt.total_count() >= 30
    assert engine.epistemic_health("macro-regime-v1")["last_cycle"]["forecast_ll"] <= 0
