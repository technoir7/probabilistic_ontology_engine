"""
The macro domain's weekly history, as first published, for the live app.

    uv run python -m evals.export --out macro-history.json

One record a week, stamped with the Sunday that ends it as the live
scheduler stamps them (REFACTOR_SPEC D12), built by the domain's own
pipeline from FRED's history and ALFRED's vintages. Uploaded with the admin
route `POST /v1/ingest/replace?domain=mr`, it replaces the live history.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.domains.macro_regime_v1.ingestion.pipeline import MacroRegimePipeline, compute_snapshot
from src.engine.schemas import EvidenceRecord

from . import fred_history as fh


def sundays(start: date, end: date) -> list[date]:
    first = start + timedelta(days=(6 - start.weekday()) % 7)
    return [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]


def weekly_records(history: dict, start: date, end: date) -> list[EvidenceRecord]:
    out = []
    for sunday in sundays(start, end):
        record = MacroRegimePipeline.build_evidence_record(compute_snapshot(fh.week_inputs(history, sunday), sunday))
        out.append(record.model_copy(update={"timestamp": datetime(sunday.year, sunday.month, sunday.day, tzinfo=timezone.utc)}))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2003, 4, 6))
    args = parser.parse_args()
    history = fh.as_first_published(fh.load(), fh.load_vintages())
    end = max(o.obs_date for o in fh.load()["WALCL"])
    records = weekly_records(history, args.start, end)
    args.out.write_text(json.dumps([r.model_dump(mode="json") for r in records]))
    print(f"{len(records)} weeks, {records[0].timestamp.date()} to {records[-1].timestamp.date()} -> {args.out}")
