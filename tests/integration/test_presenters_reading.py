"""presenters.reading: what a posterior says of a variable, as its most
likely value and a degree from 0 to 1 (REFACTOR_SPEC D25)."""
from src.domains.sources.grades import graded_variables
from src.domains.sources.structure import boolean_variables
from src.engine.api import presenters


def test_a_yes_no_reads_as_its_probability_of_true():
    v = boolean_variables("m", ["A"])["A"]
    assert presenters.reading({"True": 0.7, "False": 0.3}, v) == ("True", 0.7)


def test_levels_read_as_their_mean_position_from_low_to_high():
    v = graded_variables("m", ["A"])["A"]
    level, degree = presenters.reading({"low": 0.2, "mid": 0.3, "high": 0.5}, v)
    assert level == "high" and abs(degree - 0.65) < 1e-12


def test_no_posterior_is_no_reading():
    v = graded_variables("m", ["A"])["A"]
    assert presenters.reading({}, v) == (None, None)
