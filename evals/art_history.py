"""
Saved inputs for replaying the art domain (replay 15), in evals/data/art/:

- press.json: per paper and month, the art articles and the counts of the
  eight talk tags. Counted on 2026-10-26 by the clients' own rules (the
  NYT's articles with subject "Art", subjects compared in lower case; the
  Guardian's `artanddesign` section with its keyword tags), counts only.
- museums.json: distinct artists the Art Institute of Chicago acquired by
  fiscal year and the Cleveland Museum of Art by accession year, as the
  catalogues stood on 2026-10-26.

`load` gives stand-ins for the pipeline's clients that answer from these.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.domains.art_prestige_regime_v1.ingestion.aic_client import Acquisitions
from src.domains.art_prestige_regime_v1.ingestion.tag_counts import TagCounts

DATA = Path(__file__).parent / "data" / "art"


class SavedPaper:
    def __init__(self, months: dict[str, dict]) -> None:
        self._months = months

    async def month(self, year: int, month: int) -> TagCounts | None:
        saved = self._months.get(f"{year}-{month:02d}")
        return None if saved is None else TagCounts(articles=saved["articles"], tags=saved["tags"])


class SavedAIC:
    def __init__(self, artists: dict[int, int]) -> None:
        self._artists = artists

    async def acquisitions(self, fiscal_year: int, artwork_types=None) -> Acquisitions | None:
        n = self._artists.get(fiscal_year)
        return None if n is None else Acquisitions(objects=n, artists=n)   # objects are not saved or used


class SavedCMA:
    def __init__(self, artists: dict[int, int]) -> None:
        self._artists = artists

    async def artists_by_year(self) -> dict[int, int]:
        return self._artists


@dataclass(frozen=True)
class ArtHistory:
    papers: dict[str, SavedPaper]
    aic: SavedAIC
    cma: SavedCMA


def load(root: Path = DATA) -> ArtHistory:
    press = json.loads((root / "press.json").read_text())
    museums = json.loads((root / "museums.json").read_text())
    return ArtHistory(
        papers={paper: SavedPaper(months) for paper, months in press.items()},
        aic=SavedAIC({int(k): v for k, v in museums["aic"].items()}),
        cma=SavedCMA({int(k): v for k, v in museums["cma"].items()}),
    )
