"""
Replay 16: art talk on a slower clock, by quarter or by year, from the same
saved inputs as replay 15 (evals/README.md).

    uv run python -m evals.replay_art_slow --clock quarter --seed 0

A period's talk is its months pooled (articles and tag counts summed), read
against the periods before it, as the monthly pipeline reads a month: eight
quarters (two years) or five years, with at least half of them. The Guardian
is read from 2010. Figures are seen in the period holding their April;
museums in the period holding their December, read as the pipeline reads
them.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
from datetime import date
from pathlib import Path
from typing import Iterator

from src.domains.art_prestige_regime_v1.domain import DOMAIN_MODULE_ID, TALK, ArtPrestigeRegimeV1, get_variables
from src.domains.art_prestige_regime_v1.ingestion.figures import figure_signals, load_figures
from src.domains.art_prestige_regime_v1.ingestion.pipeline import PAPER_START, ArtPipeline
from src.domains.sources.grades import build_graded_record
from src.domains.sources.soft_evidence import zscore
from src.domains.sources.structure import with_lags
from src.engine.model.errors import EvidenceUnavailable
from src.engine.schemas import EvidenceRecord

from . import art_history
from .replay import replay, write_rows

DATA = Path(__file__).parent / "data" / "replay16"
WINDOW = {"quarter": 8, "year": 5}
_VARIABLES = with_lags(DOMAIN_MODULE_ID, get_variables())
NAMES = {str(v.variable_id): n for n, v in _VARIABLES.items()}


def period_ends(clock: str, start: date, end: date) -> list[date]:
    step = 3 if clock == "quarter" else 12
    out, y, m = [], start.year, start.month
    m = ((m - 1) // step + 1) * step   # the period's last month
    while date(y, m, 1) <= end:
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
        y, m = (y, m + step) if m + step <= 12 else (y + 1, m + step - 12)
    return out


def _months_of(clock: str, period_end: date) -> list[tuple[int, int]]:
    n = 3 if clock == "quarter" else 12
    y, m, out = period_end.year, period_end.month, []
    for _ in range(n):
        out.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def _pooled(history: art_history.ArtHistory, paper: str, months: list[tuple[int, int]]):
    """(articles, tag counts) over the months, or None if any month is unread or before the paper's start."""
    articles, tags = 0, {}
    for y, m in months:
        if (y, m) < PAPER_START[paper]:
            return None
        counts = asyncio.run(history.papers[paper].month(y, m))
        if counts is None:
            return None
        articles += counts.articles
        for t, c in counts.tags.items():
            tags[t] = tags.get(t, 0) + c
    return (articles, tags) if articles else None


def _talk(history, clock: str, ends: list[date], i: int) -> dict[str, float]:
    out = {}
    for paper in ("guardian", "nyt"):
        current = _pooled(history, paper, _months_of(clock, ends[i]))
        if current is None:
            continue
        past = [p for e in ends[max(0, i - WINDOW[clock]):i] if (p := _pooled(history, paper, _months_of(clock, e)))]
        if len(past) < (WINDOW[clock] + 1) // 2:
            continue
        for name, (p, tag) in TALK.items():
            if p == paper:
                out[name] = zscore(current[1].get(tag, 0) / current[0], [t.get(tag, 0) / a for a, t in past])
    return out


def records(history: art_history.ArtHistory, clock: str, start: date, end: date,
            figures=None) -> Iterator[tuple[date, EvidenceRecord]]:
    figures = load_figures() if figures is None else figures
    pipeline = ArtPipeline({}, history.aic, history.cma, figures={})
    # Periods before START are read too, as the comparison for the first ones.
    lead = WINDOW[clock] * (3 if clock == "quarter" else 12)
    first = date(start.year - lead // 12 - 1, 1, 1)
    ends = period_ends(clock, first, end)
    for i, e in enumerate(ends):
        if e < start:
            continue
        signals = _talk(history, clock, ends, i)
        april = date(e.year, 4, 30)
        previous = {}
        if (april.year, 4) in _months_of(clock, e):
            now, previous = figure_signals(figures, april)
            signals |= now
        if (e.year, 12) in _months_of(clock, e):
            now, prev = asyncio.run(pipeline.museums(e.year))
            if now is not None:
                signals["MuseumAcquisitionMomentum"] = now
                if prev is not None:
                    previous["MuseumAcquisitionMomentum"] = prev
        try:
            yield e, build_graded_record(module_id=DOMAIN_MODULE_ID, variables=_VARIABLES, signals=signals,
                                         previous=previous, confidence={}, target_date=e,
                                         source_ref=f"replay16-{clock}@{e}")
        except EvidenceUnavailable:
            continue


def run(history: art_history.ArtHistory, clock: str, seed: int, start: date, end: date) -> list[dict]:
    return replay(ArtPrestigeRegimeV1(), records(history, clock, start, end), seed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--clock", choices=sorted(WINDOW), required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    start = date(2001, 1, 1) if args.clock == "quarter" else date(2005, 1, 1)
    end = date(2026, 9, 30) if args.clock == "quarter" else date(2025, 12, 31)
    rows = run(art_history.load(), args.clock, args.seed, start, end)
    out = DATA / f"{args.clock}_seed{args.seed}.jsonl.gz"
    write_rows(out, rows)
    print(f"{len(rows)} {args.clock}s, {rows[0]['week']} to {rows[-1]['week']} -> {out}")
