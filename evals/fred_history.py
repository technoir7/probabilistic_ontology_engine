"""
FRED's full history of the macro domain's series, as public CSV files, and
what the domain's pipeline would have seen in any one week.

Fetched once (`download`) and kept in `evals/data/fred/`, so a replay is
repeatable and needs no API key. A week sees only what had been published by
then: monthly CPI and unemployment come out weeks after the month they
measure (`PUBLICATION_LAG_DAYS`), and each series is cut to the lookback the
live client asks FRED for.
"""
from __future__ import annotations

import csv
import io
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from src.domains.macro_regime_v1.ingestion.fred_client import FETCH_LOOKBACK_DAYS, FRED_SERIES
from src.domains.sources.fred import FREDObservation

DATA = Path(__file__).parent / "data" / "fred"

# FRED serves the ICE BofA high-yield spread only for the last three years;
# Moody's Baa corporate yield minus the 10-year Treasury goes back to 1986.
CREDIT = "BAMLH0A0HYM2"
CREDIT_STAND_IN = "BAA10Y"
SERIES = [*FRED_SERIES.values(), CREDIT_STAND_IN]

# Days after an observation's date before it is published. CPI for a month
# comes out in the middle of the next; unemployment on the first Friday.
# Daily and weekly series are out within a day, before the Monday run.
PUBLICATION_LAG_DAYS = {"CPIAUCSL": 45, "UNRATE": 36}
LIVE_LIMIT = 500  # the live client's `limit`


def csv_url(series_id: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def parse_csv(text: str, series_id: str) -> list[FREDObservation]:
    """Oldest first; FRED writes a missing value as '.'."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[1] in (".", "", series_id):
            continue
        try:
            out.append(FREDObservation(obs_date=date.fromisoformat(row[0]), value=float(row[1]), series_id=series_id))
        except ValueError:
            continue  # the header row
    return sorted(out, key=lambda o: o.obs_date)


def download(folder: Path = DATA) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for sid in SERIES:
        with urllib.request.urlopen(csv_url(sid), timeout=60) as resp:
            (folder / f"{sid}.csv").write_bytes(resp.read())


def load(folder: Path = DATA) -> dict[str, list[FREDObservation]]:
    return {sid: parse_csv((folder / f"{sid}.csv").read_text(), sid) for sid in SERIES}


class Vintages(dict):
    """A revised series as first published: vintage date (ISO) → the series
    as it stood that day, oldest first."""


def as_first_published(history: dict, vintages: dict[str, dict[str, list]]) -> dict:
    """`history` with each series in `vintages` replaced by what was known
    on each vintage date."""
    out = dict(history)
    for sid, by_date in vintages.items():
        out[sid] = Vintages({d: [FREDObservation(obs_date=date.fromisoformat(o), value=float(v), series_id=sid)
                                 for o, v in rows] for d, rows in sorted(by_date.items())})
    return out


def observations_at(history: dict, series_id: str, target: date,
                    lookback_as: str | None = None) -> list[FREDObservation]:
    """What the live client would have got for `target`: newest first,
    published by then, within the series' lookback, at most LIVE_LIMIT. A
    series as first published is read from the latest vintage taken by then."""
    series = history.get(series_id, [])
    start = target - timedelta(days=FETCH_LOOKBACK_DAYS.get(lookback_as or series_id, 400))
    if isinstance(series, Vintages):
        taken = [d for d in series if date.fromisoformat(d) <= target]
        seen = [o for o in series[taken[-1]] if start <= o.obs_date] if taken else []
    else:
        lag = PUBLICATION_LAG_DAYS.get(series_id, 0)
        seen = [o for o in series if start <= o.obs_date and o.obs_date + timedelta(days=lag) <= target]
    return sorted(seen, key=lambda o: o.obs_date, reverse=True)[:LIVE_LIMIT]


# Revised series, and the day of each month a vintage is taken: after CPI's
# mid-month release, after unemployment's first-Friday release.
REVISED = {"CPIAUCSL": 16, "UNRATE": 8}
VINTAGES = DATA.parent / "alfred.json"
KEEP_MONTHS = 24  # enough for any lookback


def alfred_url(series_id: str, vintage: date) -> str:
    return f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series_id}&vintage_date={vintage.isoformat()}"


def download_vintages(start: date, end: date, path: Path = VINTAGES, pause_s: float = 1.0) -> None:
    """One vintage a month per revised series, resumable, politely paced."""
    import json
    import time
    done = json.loads(path.read_text()) if path.exists() else {}
    for sid, day in REVISED.items():
        by_date = done.setdefault(sid, {})
        month = date(start.year, start.month, day)
        while month <= end:
            key = month.isoformat()
            if key not in by_date:
                with urllib.request.urlopen(alfred_url(sid, month), timeout=60) as resp:
                    rows = parse_csv(resp.read().decode(), sid)
                cutoff = date(month.year - KEEP_MONTHS // 12, month.month, 1)
                by_date[key] = [[o.obs_date.isoformat(), o.value] for o in rows if o.obs_date >= cutoff]
                path.write_text(json.dumps(done))
                time.sleep(pause_s)
            month = date(month.year + (month.month == 12), month.month % 12 + 1, day)


def load_vintages(path: Path = VINTAGES) -> dict:
    import json
    return json.loads(path.read_text())


def week_inputs(history: dict[str, list[FREDObservation]], target: date,
                credit: str = CREDIT_STAND_IN) -> dict[str, list[FREDObservation]]:
    """The domain's inputs for one week, keyed as the pipeline expects, with
    the credit spread taken from `credit`."""
    out = {}
    for sid in FRED_SERIES.values():
        source = credit if sid == CREDIT else sid
        out[sid] = observations_at(history, source, target, lookback_as=sid)
    return out


if __name__ == "__main__":
    import sys
    if "--vintages" in sys.argv:
        download_vintages(date(2002, 1, 1), date.today())
        print({sid: len(v) for sid, v in load_vintages().items()})
    else:
        download()
        print({sid: len(v) for sid, v in load().items()})
