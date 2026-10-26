"""
Artists across the four sources of the artists plan (docs/art-artists-plan.md
§3): who each museum acquired, and whom each paper wrote about, matched by
name. Fetching is in `fetch_museums`; the papers' names come from the saved
texts' tags (abductive_engine press.py).

A name is compared without accents, case, punctuation or "Last, First"
order. Where two sources give birth years that differ, the name belongs to
two people and is dropped, never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping, Optional

_NOT_PEOPLE = re.compile(r"\b(unknown|anonymous|unidentified|workshop|school|period|dynasty|culture|attributed|style)\b")


@dataclass(frozen=True)
class Person:
    name: str
    born: Optional[int]


def normalise(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first} {last}"
    return " ".join(re.sub(r"[^a-z ]", " ", name).split())


def cma_person(description: str) -> Optional[Person]:
    """Cleveland's creator description, "Name (Nationality, 1929-)"; None
    for what is not one named person."""
    name, _, rest = description.partition("(")
    name = name.strip().rstrip(",")
    if not name or _NOT_PEOPLE.search(name.lower()) or len(normalise(name).split()) < 2:
        return None
    born = re.search(r"\b(1\d{3}|20\d{2})\b", rest)
    return Person(normalise(name), int(born.group(1)) if born else None)


def nyt_person(value: str) -> str:
    return normalise(re.sub(r"\(.*?\)", "", value))


@dataclass
class Matched:
    artists: dict[str, set[str]] = field(default_factory=dict)   # name -> sources
    ambiguous: set[str] = field(default_factory=set)


def match(museums: Mapping[str, list[Person]], press: Mapping[str, set[str]],
          candidates: set[str] = frozenset()) -> Matched:
    """Names by the sources that have them. A name from a source in
    *candidates* (Guardian tags, which are topics as well as people) counts
    only if another source has it as a person."""
    births: dict[str, set[int]] = {}
    out = Matched()
    for source, people in museums.items():
        for p in people:
            out.artists.setdefault(p.name, set()).add(source)
            if p.born is not None:
                births.setdefault(p.name, set()).add(p.born)
    for source, names in press.items():
        if source not in candidates:
            for n in names:
                out.artists.setdefault(n, set()).add(source)
    for source, names in press.items():
        if source in candidates:
            for n in names & out.artists.keys():
                out.artists[n].add(source)
    out.ambiguous = {n for n, years in births.items() if max(years) - min(years) > 1}
    for n in out.ambiguous:
        out.artists.pop(n, None)
    return out


# ── Fetching (network; run once, saved to evals/data/artists/) ──────────────

_UA = {"User-Agent": "probabilistic-ontology-engine/0.1 (art_prestige_regime_v1)"}


def _json(url: str, body: dict | None = None) -> dict:
    import json
    import time
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    headers = _UA | ({"Content-Type": "application/json"} if data else {})
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=180) as r:
                return json.load(r)
        except OSError:
            time.sleep(30 * (i + 1))
    raise RuntimeError(f"gave up: {url}")


def fetch_museums(first: int = 1995, last: int = 2025) -> dict:
    """Chicago: works acquired per artist per fiscal year, and each artist's
    name and birth year. Cleveland: works accessioned per creator per year,
    and each creator's description. About 15 minutes, mostly Cleveland."""
    aic_years: dict[str, dict[str, int]] = {}
    for fy in range(first, last + 1):
        body = {"query": {"bool": {"filter": [{"term": {"fiscal_year": fy}}]}},
                "aggs": {"artists": {"terms": {"field": "artist_id", "size": 10000}}}, "limit": 0}
        buckets = _json("https://api.artic.edu/api/v1/artworks/search", body)["aggregations"]["artists"]["buckets"]
        aic_years[str(fy)] = {str(b["key"]): b["doc_count"] for b in buckets}
    ids = sorted({i for year in aic_years.values() for i in year}, key=int)
    agents: dict[str, list] = {}
    for k in range(0, len(ids), 100):
        chunk = ",".join(ids[k:k + 100])
        for a in _json(f"https://api.artic.edu/api/v1/agents?ids={chunk}&fields=id,title,birth_date&limit=100")["data"]:
            agents[str(a["id"])] = [a.get("title") or "", a.get("birth_date")]
    cma_years: dict[str, dict[str, int]] = {}
    creators: dict[str, str] = {}
    skip, total = 0, None
    while total is None or skip < total:
        page = _json(f"https://openaccess-api.clevelandart.org/api/artworks/?limit=1000&skip={skip}"
                     "&fields=accession_number,creators")
        total = page["info"]["total"]
        for work in page["data"]:
            m = re.match(r"(\d{4})\.", work.get("accession_number") or "")
            if not m or not first <= int(m.group(1)) <= last:
                continue
            for c in work.get("creators") or []:
                year = cma_years.setdefault(m.group(1), {})
                year[str(c["id"])] = year.get(str(c["id"]), 0) + 1
                creators[str(c["id"])] = c.get("description") or ""
        skip += 1000
    return {"aic": {"agents": agents, "years": aic_years}, "cma": {"creators": creators, "years": cma_years}}


if __name__ == "__main__":
    import json
    from pathlib import Path
    out = Path(__file__).parent / "data" / "artists" / "museums.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fetch_museums(), sort_keys=True))
    print("wrote", out)


def press_names(root) -> dict[str, dict[int, dict[str, int]]]:
    """Per paper and year, how many art articles name each person: the NYT's
    "persons" keywords, and the Guardian's `artanddesign/` keyword tags
    (topics as well as people; `match` keeps only names that are people
    elsewhere). From the saved texts (abductive_engine press.py)."""
    import json
    from pathlib import Path
    out: dict[str, dict[int, dict[str, int]]] = {"guardian": {}, "nyt": {}}
    for paper in out:
        for path in sorted(Path(root, paper).glob("*.jsonl")):
            year = int(path.stem[:4])
            counts = out[paper].setdefault(year, {})
            for line in path.read_text().splitlines():
                names = set()
                for kind, value in json.loads(line).get("tags", []):
                    if paper == "nyt" and kind.lower() == "persons":
                        names.add(nyt_person(value))
                    elif paper == "guardian" and kind.startswith("artanddesign/"):
                        names.add(normalise(value))
                for n in names:
                    counts[n] = counts.get(n, 0) + 1
    return out


def panel(museums: Mapping, press: Mapping) -> dict[str, dict[str, dict[int, int]]]:
    """Replay 17's panel: every artist a museum acquired (by name), with works
    acquired by each museum and articles naming them in each paper, by year.
    "museum" is both museums' works together."""
    people: dict[str, list[Person]] = {"aic": [], "cma": []}
    rows: list[tuple[str, str, int, int]] = []      # (source, name, year, works)
    for year, by_id in museums["aic"]["years"].items():
        for i, works in by_id.items():
            if i in museums["aic"]["agents"]:
                title, born = museums["aic"]["agents"][i]
                people["aic"].append(Person(normalise(title), born))
                rows.append(("aic", normalise(title), int(year), works))
    for year, by_id in museums["cma"]["years"].items():
        for i, works in by_id.items():
            p = cma_person(museums["cma"]["creators"].get(i, ""))
            if p:
                people["cma"].append(p)
                rows.append(("cma", p.name, int(year), works))
    kept = match(people, press={}).artists
    out: dict[str, dict[str, dict[int, int]]] = {}
    for source, name, year, works in rows:
        if name in kept:
            series = out.setdefault(name, {"aic": {}, "cma": {}, "museum": {}, "nyt": {}, "guardian": {}})
            series[source][year] = series[source].get(year, 0) + works
            series["museum"][year] = series["museum"].get(year, 0) + works
    for paper, by_year in press.items():
        for year, counts in by_year.items():
            for name, n in counts.items():
                if name in out:
                    out[name][paper][year] = n
    return out
