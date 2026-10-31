"""The graph of life stories (abductive_engine ART-PLAN 15.16) over every
artist-year with a claim read as about a life, named blocks only. Writes
life_graph.json: [A, B, P(B | A), times the usual, score] per edge.

    uv run python -m evals.life_graph_run OUT_DIR"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .artist_records import artists
from .life_graph import edges
from .success_records import TEXTS, life_keys, life_theme_claims


def main() -> None:
    out_dir = Path(sys.argv[1])
    named = json.loads((TEXTS / "trends" / "names.json").read_text())
    life = {k: {b: n for b, n in blocks.items() if b in named}
            for k, blocks in life_theme_claims(set(artists()), life_keys()).items()}
    graph = edges(life)
    rows = sorted(([a, b, round(p, 4), round(t, 3), round(s, 4)] for (a, b), (p, t, s) in graph.items()),
                  key=lambda r: -r[4])
    (out_dir / "life_graph.json").write_text(json.dumps(rows))
    print(f"{len(rows)} edges over {len(life)} artist-years -> {out_dir / 'life_graph.json'}")


if __name__ == "__main__":
    main()
