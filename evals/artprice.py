"""Artprice's yearly Top 500 artists by auction turnover (abductive_engine
ART-PLAN §12.7), from the free report PDFs Artprice publishes on
imgpublic.artprice.com, saved in ~/Documents/art-market-reports/artprice/
(outside git: the tables are Artprice's).

Years the PDFs lack (2016, 2017) come from Artprice's own report pages as
web.archive.org kept them, under archived/ (ART-PLAN §12.10).

A row is kept only when it reads cleanly (rank, name, dates, a comma-grouped
turnover) and its turnover is no higher than the rank above it, so a
misread row is dropped, never guessed; 2011's figures cannot be read apart,
so its rows are kept only in rank order. Each table reports how many of its
500 ranks survived.

    uv run --with pypdf python -m evals.artprice     # writes top500.csv beside the PDFs"""
from __future__ import annotations

import csv
import re
import unicodedata
from bisect import bisect_left, bisect_right
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple, Optional

REPORTS = Path.home() / "Documents" / "art-market-reports" / "artprice"
HEADING = re.compile(r"top 500 (?:contemporary )?artists", re.I)
_ROW = re.compile(r"^\s*(\d{1,3})\s+(?:(?:\d{1,5}|-|new)\s+)?([^()\d$]+?)\s*\(([^()]*)\)\s+(?:[A-Za-z][A-Za-z .,'-]*?\s+)?\$?"
                  r"(\d{1,3}(?:,\d{3})+)(?=\s|$)")
_YEAR = re.compile(r"\d{4}")
# A row's rank, name and dates, with any figure after them: for 2011, whose
# space-grouped figures cannot be split into turnover and the rest.
_RANKED = re.compile(r"^\s*(\d{1,3})\s+(?:(?:\d{1,5}|-|new)\s+)?([^()\d$]+?)\s*\(([^()]*)\)\s+\d")

# Report file -> (series, year its table covers). Contemporary reports run
# July to June and cover artists born after 1945; the year is the June's.
SOURCES = {
    "trends2009_en.pdf": ("all", 2009), "trends2010_en.pdf": ("all", 2010), "trends2011_en.pdf": ("all", 2011),
    "the_art_market2012_online_en.pdf": ("all", 2012), "trends2013_en_fr_de_es_online.pdf": ("all", 2013),
    "rama2014_en.pdf": ("all", 2014), "rama2016_en.pdf": ("all", 2015),
    **{f"the-art-market-in-{y}.pdf": ("all", y) for y in range(2018, 2026)},
    **{f"the-contemporary-art-market-report-{y}.pdf": ("contemporary", y) for y in (2015, *range(2019, 2027))},
}
SPACE_GROUPED = {"trends2011_en.pdf"}       # read by rank order alone (in_rank_order)
# Artprice's own report pages as web.archive.org kept them, ten pages of 50
# each (ART-PLAN §12.10): the live pages sit behind a bot check.
ARCHIVED = {"archived/2016": ("all", 2016), "archived/2017": ("all", 2017)}


class Row(NamedTuple):
    rank: int
    name: str
    born: Optional[int]
    turnover: Optional[int]     # US dollars; None where it cannot be read apart from the other figures


def parse_row(line: str) -> Optional[Row]:
    m = _ROW.match(re.sub(r"\s+,", ",", line))      # "$287 ,223,639": a stray space, not a misread
    if not m:
        return None
    name = _name(m.group(2))
    if name is None:
        return None
    return Row(int(m.group(1)), name, _born(m.group(3)), int(m.group(4).replace(",", "")))


def _name(text: str) -> Optional[str]:
    # A typeset ligature (ﬀ, ﬁ, ﬂ ...) comes out of the PDF with a space after it.
    name = " ".join(re.sub(r"([\ufb00-\ufb06])\s+", r"\1", text).split())
    if not re.search(r"[A-Za-z]{2}", name) or "'" in name or "’" in name:
        return None                  # auction houses ("Sotheby's") and stray text
    return name


def _born(dates: str) -> Optional[int]:
    year = _YEAR.search(dates)
    return int(year.group()) if year else None


def _starts(lines: list[str]) -> list[int]:
    heads = [i for i, line in enumerate(lines) if HEADING.search(line)]
    return sorted({heads[-1] if heads else 0} | {i for i, line in enumerate(lines)
                                                 if (m := _RANKED.match(line)) and m.group(1) == "1"})


def in_rank_order(text: str) -> list[Row]:
    """As table, for a table whose figures cannot be read apart (2011): rank,
    name and birth year only, keeping the longest run of rows whose ranks
    rise in the order they are printed."""
    lines = text.splitlines()
    return max((_rising(lines[i:]) for i in _starts(lines)), key=len, default=[])


def _rising(lines: list[str]) -> list[Row]:
    rows, seen = [], set()
    for line in lines:
        m = _RANKED.match(line)
        if m and 1 <= int(m.group(1)) <= 500 and int(m.group(1)) not in seen and (name := _name(m.group(2))):
            seen.add(int(m.group(1)))
            rows.append(Row(int(m.group(1)), name, _born(m.group(3)), None))
    # Longest strictly increasing subsequence of rank, in print order.
    tails, back, best = [], [], {}
    for i, r in enumerate(rows):
        j = bisect_left(tails, r.rank)
        if j == len(tails):
            tails.append(r.rank)
        else:
            tails[j] = r.rank
        best[j] = i
        back.append(best.get(j - 1))
    out, i = [], best.get(len(tails) - 1)
    while i is not None:
        out.append(rows[i])
        i = back[i]
    return out[::-1]


class _Cells(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def html_table(html: str) -> list[Row]:
    """The rows of one archived report page: rank, "Name (dates)", and the
    column headed turnover."""
    p = _Cells()
    p.feed(html)
    head = next((r for r in p.rows if r and r[0].lower() == "rank"), None)
    if head is None:
        return []
    col = next(i for i, h in enumerate(head) if "turnover" in h.lower())
    out = []
    for r in p.rows:
        m = re.match(r"^(.*?)\s*\(([^()]*)\)$", r[1]) if len(r) > col and r[0].isdigit() else None
        figure = r[col].replace(",", "") if m else ""
        if m and figure.isdigit() and (name := _name(m.group(1))):
            out.append(Row(int(r[0]), name, _born(m.group(2)), int(figure)))
    return out


def table(text: str) -> list[Row]:
    """The Top 500 table, one row per rank, keeping the longest run in which
    turnover never rises as rank goes down. The heading repeats on each page
    but sometimes not the first, and shorter rankings (top works, top 10s)
    come before it, so every rank-1 row and the last heading are tried as
    the table's start, and the start giving the longest table wins."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if HEADING.search(line)]
    starts = {heads[-1] if heads else 0} | {i for i, line in enumerate(lines) if (r := parse_row(line)) and r.rank == 1}
    return max((falling(r for line in lines[i:] if (r := parse_row(line))) for i in sorted(starts)), key=len, default=[])


def falling(parsed) -> list[Row]:
    """One row per rank (the first), keeping the longest run in which turnover
    never rises as rank goes down."""
    rows: dict[int, Row] = {}
    for r in parsed:
        if 1 <= r.rank <= 500 and r.rank not in rows:
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
        for name, (series, year) in sorted({**SOURCES, **ARCHIVED}.items(), key=lambda kv: kv[1]):
            path = REPORTS / name
            if not path.exists():
                print(f"{name}: missing")
                continue
            if name in ARCHIVED:
                rows = falling(r for page in sorted(path.glob("*.html")) for r in html_table(page.read_text()))
            else:
                text = "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
                rows = in_rank_order(text) if name in SPACE_GROUPED else table(text)
            for r in rows:
                w.writerow([series, year, r.rank, r.name, r.born or "", r.turnover or "", name])
            print(f"{series:12} {year}: {len(rows):3} of 500 ranks  ({name})", flush=True)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
