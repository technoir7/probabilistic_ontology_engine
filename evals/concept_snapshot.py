"""The art domain's concepts snapshot (REFACTOR_SPEC D29) from the records
abductive_engine's evals/export_concepts.py writes.

    uv run python -m evals.concept_snapshot RECORDS.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.domains.art_prestige_regime_v1 import cases


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text())
    snap = cases.dump("concepts", "Concepts", "writers taking the concept up next year", tuple(data["pool"]),
                      data["records"], data["labels"])
    path = cases.DATA / "concepts.json"
    path.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    print(f"{len(data['records'])} concept-years ({len(snap['closed'])} distinct closed) -> {path}")


if __name__ == "__main__":
    main()
