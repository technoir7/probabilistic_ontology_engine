"""
Replays the art domain month by month from saved inputs (replay 15).

    uv run python -m evals.replay_art --seed 0 [--start 2001-01-01] [--end 2026-09-30]

Each month-end's record is built by the art pipeline itself, its clients
answering from `art_history`; a month with no evidence at all is left out,
as the live rebuild leaves it out. Rows as `replay.replay` writes them, to
`evals/data/replay15/`.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
from datetime import date
from pathlib import Path
from typing import Iterator

from src.domains.art_prestige_regime_v1.domain import ArtPrestigeRegimeV1
from src.domains.art_prestige_regime_v1.ingestion.pipeline import ArtPipeline
from src.engine.model.errors import EvidenceUnavailable
from src.engine.schemas import EvidenceRecord

from . import art_history
from .replay import replay, write_rows

DATA = Path(__file__).parent / "data" / "replay15"


def month_ends(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def records(history: art_history.ArtHistory, start: date, end: date) -> Iterator[tuple[date, EvidenceRecord]]:
    pipeline = ArtPipeline(history.papers, history.aic, history.cma)
    for month_end in month_ends(start, end):
        try:
            yield month_end, asyncio.run(pipeline.fetch_evidence(month_end))
        except EvidenceUnavailable:
            continue


def run(history: art_history.ArtHistory, seed: int, start: date, end: date) -> list[dict]:
    return replay(ArtPrestigeRegimeV1(), records(history, start, end), seed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2001, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    args = parser.parse_args()
    rows = run(art_history.load(), args.seed, args.start, args.end)
    out = DATA / f"seed{args.seed}.jsonl.gz"
    write_rows(out, rows)
    print(f"{len(rows)} months, {rows[0]['week']} to {rows[-1]['week']} -> {out}")
