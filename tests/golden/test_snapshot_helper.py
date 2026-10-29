"""The golden comparison: a number shown rounded may land one step either
side of a rounding edge on another platform, and only that is forgiven."""
from tests.golden.snapshot import _diff


def test_a_rounded_number_may_differ_by_one_step_in_its_last_shown_digit():
    assert _diff({"g": 188.2}, {"g": 188.1}) == []
    assert _diff({"p": 0.523}, {"p": 0.524}) == []


def test_anything_more_is_a_difference():
    assert _diff({"g": 188.2}, {"g": 188.0}) != []
    assert _diff({"p": 0.523}, {"p": 0.53}) != []
    assert _diff({"x": 0.123456789}, {"x": 0.123456791}) != []
