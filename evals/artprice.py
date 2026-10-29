"""Artprice's yearly Top 500 artists by auction turnover (abductive_engine
ART-PLAN §12.7), from the free report PDFs Artprice publishes on
imgpublic.artprice.com, saved in ~/Documents/art-market-reports/artprice/
(outside git: the tables are Artprice's).

A row is kept only when it reads cleanly (rank, name, dates, a comma-grouped
turnover) and its turnover is no higher than the rank above it, so a
misread row is dropped, never guessed; each table reports how many of its
500 ranks survived.

    uv run --with pypdf python -m evals.artprice     # writes top500.csv beside the PDFs"""
from __future__ import annotations

import csv
import re
import unicodedata
from bisect import bisect_right
from pathlib import Path
from typing import NamedTuple, Optional

REPORTS = Path.home() / "Documents" / "art-market-reports" / "artprice"
HEADING = re.compile(r"top 500 (?:contemporary )?artists", re.I)
_ROW = re.compile(r"^\s*(\d{1,3})\s+(?:(?:\d{1,5}|-|new)\s+)?([^()\d$]+?)\s*\(([^()]*)\)\s+(?:[A-Za-z][A-Za-z .,'-]*?\s+)?\$?"
                  r"(\d{1,3}(?:,\d{3})+)(?=\s|$)")
_YEAR = re.compile(r"\d{4}")

# Report file -> (series, year its table covers). Contemporary reports run
# July to June and cover artists born after 1945; the year is the June's.
SOURCES = {
    "trends2009_en.pdf": ("all", 2009), "trends2010_en.pdf": ("all", 2010), "trends2011_en.pdf": ("all", 2011),
    "rama2014_en.pdf": ("all", 2014), "rama2016_en.pdf": ("all", 2015),
    **{f"the-art-market-in-{y}.pdf": ("all", y) for y in range(2018, 2026)},
    **{f"the-contemporary-art-market-report-{y}.pdf": ("contemporary", y) for y in (2015, *range(2019, 2027))},
}


class Row(NamedTuple):
    rank: int
    name: str
    born: Optional[int]
    turnover: int        # US dollars


def parse_row(line: str) -> Optional[Row]:
    m = _ROW.match(line)
    if not m:
        return None
    name = m.group(2).strip()
    if not re.search(r"[A-Za-z]{2}", name) or "'" in name or "’" in name:
        return None                  # auction houses ("Sotheby's") and stray text
    year = _YEAR.search(m.group(3))
    return Row(int(m.group(1)), name, int(year.group()) if year else None, int(m.group(4).replace(",", "")))


def table(text: str) -> list[Row]:
    """The Top 500 table, one row per rank, keeping the longest run in which
    turnover never rises as rank goes down. The heading repeats on each page
    but sometimes not the first, and shorter rankings (top works, top 10s)
    come before it, so every rank-1 row and the last heading are tried as
    the table's start, and the start giving the longest table wins."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if HEADING.search(line)]
    starts = {heads[-1] if heads else 0} | {i for i, line in enumerate(lines) if (r := parse_row(line)) and r.rank == 1}
    return max((_falling(lines[i:]) for i in sorted(starts)), key=len, default=[])


def _falling(lines: list[str]) -> list[Row]:
    rows: dict[int, Row] = {}
    for line in lines:
        r = parse_row(line)
        if r and 1 <= r.rank <= 500 and r.rank not in rows:
            rows[r.rank] = r
    ordered = [rows[k] for k in sorted(rows)]
    # Longest non-increasing subsequence of turnover, by rank.
    tails, back, best = [], [], {}
    for i, r in enumerate(ordered):
        j = bisect_right(tails, -r.turnover)
        if j == len(tails):
            tails.append(-r.turnover)
        else:
            tails[j] = -r.turnover
        best[j] = i
        back.append(best.get(j - 1))
    out, i = [], best.get(len(tails) - 1)
    while i is not None:
        out.append(ordered[i])
        i = back[i]
    return out[::-1]


def key(name: str, born: Optional[int]) -> tuple[frozenset, Optional[int]]:
    """An artist as name words in any order and case, with birth year."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return frozenset(re.sub(r"[^a-z ]", " ", plain).split()), born


def main() -> None:
    from pypdf import PdfReader
    out = REPORTS / "top500.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["series", "year", "rank", "name", "born", "turnover_usd", "source"])
        for name, (series, year) in sorted(SOURCES.items(), key=lambda kv: kv[1]):
            path = REPORTS / name
            if not path.exists():
                print(f"{name}: missing")
                continue
            text = "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
            rows = table(text)
            for r in rows:
                w.writerow([series, year, r.rank, r.name, r.born or "", r.turnover, name])
            print(f"{series:12} {year}: {len(rows):3} of 500 ranks  ({name})", flush=True)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
