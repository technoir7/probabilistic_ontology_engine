"""
Critical reception by artist (abductive_engine ART-PLAN §4, a first concept
family): the judgements the press makes about each artist, by year, from
the assertions the reader reported. A judgement belongs to an artist when
the artist's full name, as a museum gives it, appears in what it is about
(the text's own words); the longest such name wins. A surname alone is not
enough, so some judgements go unlinked rather than guessed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .art_artists import normalise

STANCES = ("approval", "disapproval")


def linked(about: str, names: set[str]) -> Optional[str]:
    words = normalise(about).split()
    for n in range(min(5, len(words)), 1, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i + n])
            if phrase in names:
                return phrase
    return None


def reception(assertions_root: Path, names: set[str]) -> dict[str, dict[str, dict[int, int]]]:
    """Artist -> {"approval", "disapproval", "judged", "contested"} -> year ->
    judgements; contested is 1 in a year with both approval and disapproval."""
    out: dict[str, dict[str, dict[int, int]]] = {}
    for path in sorted(Path(assertions_root).glob("*/*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            year = int(row["published"][:4])
            for a in row["assertions"]:
                if a["force"] != "judges":
                    continue
                artist = linked(a["about"], names)
                if artist is None:
                    continue
                series = out.setdefault(artist, {"approval": {}, "disapproval": {}, "judged": {}})
                series["judged"][year] = series["judged"].get(year, 0) + 1
                if a["stance"] in STANCES:
                    series[a["stance"]][year] = series[a["stance"]].get(year, 0) + 1
    for series in out.values():
        series["contested"] = {y: 1 for y in series["approval"] if y in series["disapproval"]}
    return out
