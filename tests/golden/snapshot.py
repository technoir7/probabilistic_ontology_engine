"""
Golden snapshot helper.

A golden test turns observable behaviour into plain JSON, normalises the parts
that legitimately vary between runs (random UUIDs, wall-clock times), and
compares it with a committed file under ``tests/golden/snapshots/``.

The snapshot files are the contract. The code that *extracts* state
(``probe.py``) is an adapter and is expected to change as the refactor moves
APIs; a refactor commit may edit the adapter but must not change a snapshot.
Commits that intentionally change behaviour regenerate snapshots with

    POE_UPDATE_GOLDEN=1 uv run pytest tests/golden

and the snapshot diff in that commit shows exactly what changed.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# Nine decimals: tight enough to catch any real change in learning, loose
# enough to survive harmless float reassociation (e.g. summing in a new order).
_FLOAT_DIGITS = 9

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)?")
_AGO_RE = re.compile(r"\b(just now|\d+[mhd] ago|today|\d+ days? ago)\b")


def normalize(data: Any) -> Any:
    """Make *data* comparable across runs; UUIDs become aliases in first-seen order."""
    aliases: dict[str, str] = {}

    def alias(match: re.Match) -> str:
        return aliases.setdefault(match.group(0), f"<id{len(aliases)}>")

    def walk(x: Any) -> Any:
        if isinstance(x, bool) or x is None or isinstance(x, int):
            return x
        if isinstance(x, float):
            if math.isnan(x):
                return "nan"
            if math.isinf(x):
                return "inf" if x > 0 else "-inf"
            return round(x, _FLOAT_DIGITS) + 0.0  # +0.0 folds -0.0 into 0.0
        if isinstance(x, str):
            x = _UUID_RE.sub(alias, x)
            x = _ISO_TS_RE.sub("<ts>", x)
            return _AGO_RE.sub("<ago>", x)
        if isinstance(x, dict):
            return {walk(k) if isinstance(k, str) else str(k): walk(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v) for v in x]
        raise TypeError(f"cannot snapshot {type(x).__name__}: {x!r}")

    return walk(data)


def _diff(expected: Any, actual: Any, path: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [f"{path}: {expected!r} != {actual!r}"]
    if isinstance(expected, dict):
        out = []
        for k in sorted(set(expected) | set(actual)):
            if k not in actual:
                out.append(f"{path}.{k}: missing in actual")
            elif k not in expected:
                out.append(f"{path}.{k}: unexpected in actual")
            else:
                out.extend(_diff(expected[k], actual[k], f"{path}.{k}"))
        return out
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}: length {len(expected)} != {len(actual)}"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out.extend(_diff(e, a, f"{path}[{i}]"))
        return out
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]


def assert_matches_snapshot(name: str, data: Any) -> None:
    actual = normalize(data)
    path = SNAPSHOT_DIR / f"{name}.json"
    rendered = json.dumps(actual, indent=1, sort_keys=True) + "\n"
    if os.environ.get("POE_UPDATE_GOLDEN") == "1":
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(
            f"No snapshot {path.name}. Create it with POE_UPDATE_GOLDEN=1 and review the file."
        )
    expected = json.loads(path.read_text(encoding="utf-8"))
    # Round-trip through JSON so tuples/lists and key types compare like the file.
    differences = _diff(expected, json.loads(rendered))
    if differences:
        shown = "\n  ".join(differences[:25])
        more = f"\n  ... and {len(differences) - 25} more" if len(differences) > 25 else ""
        raise AssertionError(f"{path.name} differs ({len(differences)} paths):\n  {shown}{more}")
