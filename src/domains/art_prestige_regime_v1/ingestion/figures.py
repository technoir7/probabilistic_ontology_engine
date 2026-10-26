"""
The yearly Art Basel & UBS figures (art plan §6), from report_figures.csv:
each year's figure as first printed, in the edition of the year after,
which appears in March or early April. A figure is seen in that April's
record and in no other.

A figure is read as a level against the figures printed before it (the
z-score of this year's against all earlier years'), so "high" means high
for that figure, with no line set by hand. Last year's level is given too,
read the same way from what was printed by then (art plan §7).
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Mapping

from ...sources.soft_evidence import zscore
from ..domain import FIGURES

SEEN_IN_MONTH = 4
MIN_EARLIER = 2
_FILE = Path(__file__).resolve().parents[1] / "report_figures.csv"

Figures = Mapping[str, Mapping[int, float]]


def load_figures(path: Path = _FILE) -> dict[str, dict[int, float]]:
    """Signal → year → percent. Raises on a row the rules above do not cover."""
    out: dict[str, dict[int, float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            year, edition = int(row["year"]), int(row["edition"])
            if row["signal"] not in FIGURES or edition != year + 1:
                raise ValueError(f"{path.name}: unexpected row {row}")
            out.setdefault(row["signal"], {})[year] = float(row["percent"])
    return out


def _read(by_year: Mapping[int, float], year: int) -> float | None:
    earlier = [v for y, v in sorted(by_year.items()) if y < year]
    if year not in by_year or len(earlier) < MIN_EARLIER:
        return None
    return zscore(by_year[year], earlier)


def figure_signals(figures: Figures, target_date: date) -> tuple[dict[str, float], dict[str, float]]:
    """(this year's signals, last year's) for a month's record; both empty outside April."""
    if target_date.month != SEEN_IN_MONTH:
        return {}, {}
    year = target_date.year - 1
    now, prev = {}, {}
    for name, by_year in figures.items():
        if (s := _read(by_year, year)) is not None:
            now[name] = s
            if (p := _read(by_year, year - 1)) is not None:
                prev[name] = p
    return now, prev
