"""
Macro's raw observations for other engines, as of when each became public.

    uv run python -m evals.observations --out observations.csv

The abductive engine (a separate repo) reasons from numbers, not from POE's
signals, and must never see a number before it was published (its DESIGN
§2). Each row is one published version of one value: series, the date it
measures, the value, and the date it became public. A revised series has a
row per version; the newest version public by a
date is the one that counts then.

Daily and weekly series are not revised and FRED posts them the next
business day, so each is public the day after it measures. CPI and
unemployment are read from FRED's real-time observations, which give every
version with the day it was released (`--fetch-releases` saves them to
RELEASES, with FRED_API_KEY set). POE's own replays read monthly vintages
taken on a fixed day instead (fred_history.REVISED); a release after that
day reaches them a month late.

One-way: POE writes this file and learns nothing from the reader.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import IO, Iterable, NamedTuple

from . import fred_history as fh

START = date(2000, 1, 1)
RELEASES = Path(__file__).parent / "data" / "fred_releases.json"
REVISED = ("CPIAUCSL", "UNRATE")


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


def releases(versions: dict[str, list[dict]]) -> dict[str, dict[str, list]]:
    """FRED's real-time observations as vintages: release date → the values
    that release published. A value FRED reports as missing ('.') is skipped."""
    out: dict[str, dict[str, list]] = {}
    for sid, rows_ in versions.items():
        by_release = out.setdefault(sid, {})
        for v in rows_:
            if v["value"] != ".":
                by_release.setdefault(v["realtime_start"], []).append([v["date"], float(v["value"])])
    return out


def fetch_releases(api_key: str, series: tuple[str, ...] = REVISED, path: Path = RELEASES) -> None:
    """Every version of each series since START, with its release date: one request each."""
    out = {}
    for sid in series:
        q = urllib.parse.urlencode({"series_id": sid, "realtime_start": START.isoformat(), "realtime_end": "9999-12-31",
                                    "observation_start": START.isoformat(), "file_type": "json", "limit": 100000,
                                    "api_key": api_key})
        with urllib.request.urlopen("https://api.stlouisfed.org/fred/series/observations?" + q, timeout=120) as r:
            out[sid] = [{k: o[k] for k in ("realtime_start", "date", "value")} for o in json.load(r)["observations"]]
    path.write_text(json.dumps(out))


def write_csv(out_rows: Iterable[Row], out: IO[str]) -> None:
    w = csv.writer(out, lineterminator="\n")
    w.writerow(Row._fields)
    for r in out_rows:
        w.writerow([r.series, r.measured.isoformat(), repr(r.value), r.public.isoformat()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fetch-releases", action="store_true")
    args = parser.parse_args()
    if args.fetch_releases:
        fetch_releases(os.environ["FRED_API_KEY"])
    if args.out is None:
        raise SystemExit(0)
    found = rows(fh.load(), releases(json.loads(RELEASES.read_text())), start=START)
    with args.out.open("w") as f:
        write_csv(found, f)
    print(len(found), "rows")
