"""
Macro's raw observations for other engines, as of when each became public.

    uv run python -m evals.observations --out observations.csv

The abductive engine (a separate repo) reasons from numbers, not from POE's
signals, and must never see a number before it was published (its DESIGN
§2). Each row is one published version of one value: series, the date it
measures, the value, and the date it became public. A revised series has a
row per version, from ALFRED's vintages; the newest version public by a
date is the one that counts then.

Daily and weekly series are not revised and FRED posts them the next
business day, so each is public the day after it measures. The vintages are
taken just after each release (fred_history.REVISED), so their dates are an
upper bound on when a value became known.

One-way: POE writes this file and learns nothing from the reader.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path
from typing import IO, Iterable, NamedTuple

from . import fred_history as fh

START = date(2000, 1, 1)


class Row(NamedTuple):
    series: str
    measured: date
    value: float
    public: date


def rows(history: dict, vintages: dict[str, dict[str, list]], start: date = date.min) -> list[Row]:
    """Every published version, oldest first within each series."""
    out = []
    for sid, series in history.items():
        if sid in vintages:
            continue
        out += [Row(sid, o.obs_date, o.value, o.obs_date + timedelta(days=1))
                for o in sorted(series, key=lambda o: o.obs_date) if o.obs_date >= start]
    for sid, by_date in vintages.items():
        known: dict[date, float] = {}
        for taken, values in sorted(by_date.items()):
            for measured, value in values:
                measured, value = date.fromisoformat(measured), float(value)
                if measured >= start and known.get(measured) != value:
                    known[measured] = value
                    out.append(Row(sid, measured, value, date.fromisoformat(taken)))
    return out


def write_csv(out_rows: Iterable[Row], out: IO[str]) -> None:
    w = csv.writer(out, lineterminator="\n")
    w.writerow(Row._fields)
    for r in out_rows:
        w.writerow([r.series, r.measured.isoformat(), repr(r.value), r.public.isoformat()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    found = rows(fh.load(), fh.load_vintages(), start=START)
    with args.out.open("w") as f:
        write_csv(found, f)
    print(len(found), "rows")
