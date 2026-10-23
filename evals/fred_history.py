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


def observations_at(history: dict[str, list[FREDObservation]], series_id: str, target: date,
                    lookback_as: str | None = None) -> list[FREDObservation]:
    """What the live client would have got for `target`: newest first,
    published by then, within the series' lookback, at most LIVE_LIMIT."""
    lag = PUBLICATION_LAG_DAYS.get(series_id, 0)
    start = target - timedelta(days=FETCH_LOOKBACK_DAYS.get(lookback_as or series_id, 400))
    seen = [o for o in history.get(series_id, []) if start <= o.obs_date and o.obs_date + timedelta(days=lag) <= target]
    return sorted(seen, key=lambda o: o.obs_date, reverse=True)[:LIVE_LIMIT]


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
    download()
    print({sid: len(v) for sid, v in load().items()})
