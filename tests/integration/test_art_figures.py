"""The yearly Art Basel & UBS figures (art plan §6): each year's first-printed
figure, seen in the April after it, read against the figures printed before."""
from __future__ import annotations

from datetime import date

import pytest

from src.domains.art_prestige_regime_v1.ingestion.figures import FIGURES, figure_signals, load_figures


def test_the_committed_file_has_nine_years_of_four_figures():
    figures = load_figures()
    assert set(figures) == set(FIGURES) == {"ArtSalesGrowth", "DealerShare", "OnlineShare", "HighEndShare"}
    for by_year in figures.values():
        assert sorted(by_year) == list(range(2016, 2025))
    assert figures["OnlineShare"][2020] == 25


def test_figures_are_seen_only_in_april_of_the_following_year():
    figures = {"F": {y: float(y % 3) for y in range(2010, 2020)}}
    assert figure_signals(figures, date(2019, 3, 31)) == ({}, {})
    assert figure_signals(figures, date(2019, 5, 31)) == ({}, {})
    now, _ = figure_signals(figures, date(2019, 4, 30))
    assert set(now) == {"F"}


def test_a_figure_is_read_against_those_printed_before_it_and_so_is_last_years():
    figures = {"F": {2015: 1.0, 2016: 3.0, 2017: 2.0, 2018: 10.0}}
    now, prev = figure_signals(figures, date(2019, 4, 30))   # reads 2018
    assert now["F"] == pytest.approx((10.0 - 2.0) / 1.0)     # mean and sd of 1, 3, 2
    assert prev["F"] == pytest.approx((2.0 - 2.0) / 2 ** 0.5)  # 2017 against 1 and 3


def test_with_fewer_than_two_earlier_figures_a_year_is_not_read():
    figures = {"F": {2016: 1.0, 2017: 3.0, 2018: 2.0}}
    assert figure_signals(figures, date(2018, 4, 30)) == ({}, {})   # 2017 has one before it
    now, prev = figure_signals(figures, date(2019, 4, 30))
    assert set(now) == {"F"} and prev == {}
