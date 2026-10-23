"""
Scores the replay's five seeds against the questions in `evals/README.md`,
and draws the leading family week by week.

    uv run python -m evals.report [--dir evals/data/replay2] [--svg docs/replay2.svg]

Writes `results.json` beside the replay's rows, and the chart.
"""
from __future__ import annotations

import json
import statistics
from datetime import date
from pathlib import Path

from . import fred_history as fh
from . import scoring
from .replay import DATA, fridays
from src.domains.macro_regime_v1.ingestion.pipeline import compute_snapshot

SEEDS = range(5)
DOCS = Path(__file__).parents[1] / "docs"
COLOURS = {"T_monetary": "#3b6fb6", "T_credit": "#c8553d", "T_ai_boom": "#6a994e",
           "T_recession": "#8e5ea2", "T_null": "#9a9a9a", "unknown": "#000000"}
PERIODS = [("2003–07", date(2003, 1, 1), date(2007, 11, 30)), ("2007–09", date(2007, 12, 1), date(2009, 12, 31)),
           ("2010–19", date(2010, 1, 1), date(2019, 12, 31)), ("2020–21", date(2020, 1, 1), date(2021, 12, 31)),
           ("2022–23", date(2022, 1, 1), date(2023, 12, 31)), ("2024–26", date(2024, 1, 1), date(2026, 12, 31))]


def load(seed: int, folder: Path = DATA) -> list[dict]:
    return [json.loads(line) for line in (folder / f"seed{seed}.jsonl").read_text().splitlines()]


def one_seed(rows: list[dict]) -> dict:
    changes = scoring.family_changes(rows)
    caught = scoring.events_caught(changes)
    chance = scoring.chance([r["week"] for r in rows], len(changes))
    n_caught = sum(caught.values())
    return {
        "family_changes": len(changes),
        "changes": changes,
        "events_caught": caught,
        "n_events_caught": n_caught,
        "chance_mean_caught": round(chance["mean_share_caught"] * len(scoring.EVENTS), 2),
        "p_chance_catches_as_many": round(scoring.p_at_least(chance["distribution"], n_caught), 4),
        "changes_away_from_events": len(scoring.changes_away_from_events(changes)),
        "fit_gap": scoring.fit_gap(rows),
        "fit_gap_by_period": {name: scoring.fit_gap([r for r in rows if a <= date.fromisoformat(r["week"]) <= b])
                              for name, a, b in PERIODS},
        "weeks_led": {name: scoring.weeks_led(rows, a, b) for name, a, b in PERIODS},
        "expected": {name: {"expected": sorted(fams), "weeks": scoring.weeks_led(rows, a, b)}
                     for name, a, b, fams in scoring.EXPECTED},
        "leader_structures": len({tuple(r["edges"]) for r in rows}),
        "programmes_alive_by_year": {yr: max(len(r["active_families"]) for r in rows if r["week"].startswith(yr))
                                     for yr in sorted({r["week"][:4] for r in rows})},
        "weeks_led_overall": scoring.weeks_led(rows, date(2000, 1, 1), date(2100, 1, 1)),
        "entropy_first_last": [round(rows[0]["entropy"], 3), round(rows[-1]["entropy"], 3)],
    }


def credit_agreement(history: dict) -> dict:
    """CreditSpreadStress from the stand-in against the ICE series, every
    week both have a year of history."""
    weeks = fridays(date(2024, 10, 25), max(o.obs_date for o in history[fh.CREDIT]))
    same = total = 0
    for w in weeks:
        a = compute_snapshot(fh.week_inputs(history, w, fh.CREDIT_STAND_IN), w)
        b = compute_snapshot(fh.week_inputs(history, w, fh.CREDIT), w)
        if "CreditSpreadStress" in a.missing or "CreditSpreadStress" in b.missing:
            continue
        total += 1
        same += a.credit_spread_stress == b.credit_spread_stress
    return {"weeks": total, "same_state": same}


def svg(all_rows: dict[int, list[dict]]) -> str:
    """Three panels: rival explanations dying out (seed 0, 2003–06); every
    seed's leader changes against the events; the yearly fit gap."""
    W, L, R = 1000, 70, 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="660" viewBox="0 0 {W} 660" '
           'font-family="sans-serif" font-size="11"><rect width="100%" height="100%" fill="#fff"/>']
    families = [f for f in COLOURS if f != "unknown"]

    # Panel 1: active candidates by family, seed 0, first three years.
    rows = [r for r in all_rows[0] if r["week"] < "2006-06-30"]
    top, h = 40, 150
    out.append(f'<text x="{L}" y="{top - 12}" font-size="13">1. The rival explanations die out: active candidates by '
               f'the seed they descend from (seed 0, 2003–06)</text>')
    xs = lambda i, n: L + (W - L - R) * i / max(n - 1, 1)
    for i, r in enumerate(rows):
        y = top + h
        for fam in families:
            n = r["active_families"].get(fam, 0)
            if n:
                bar = h * n / 10
                out.append(f'<rect x="{xs(i, len(rows)):.1f}" y="{y - bar:.1f}" width="{(W - L - R) / len(rows) + 0.5:.1f}" '
                           f'height="{bar:.1f}" fill="{COLOURS[fam]}"/>')
                y -= bar
    for year in (2004, 2005, 2006):
        i = next(k for k, r in enumerate(rows) if r["week"].startswith(str(year)))
        out.append(f'<text x="{xs(i, len(rows)):.1f}" y="{top + h + 14}" text-anchor="middle">{year}</text>')
    for k, fam in enumerate(families):
        out.append(f'<rect x="{L + k * 170}" y="{top + h + 24}" width="11" height="11" fill="{COLOURS[fam]}"/>'
                   f'<text x="{L + k * 170 + 16}" y="{top + h + 34}">{fam}</text>')

    # Panel 2: leader changes per seed, with the events.
    top2, band = 280, 22
    weeks = [r["week"] for r in all_rows[0]]
    x = lambda i: L + (W - L - R) * i / (len(weeks) - 1)
    out.append(f'<text x="{L}" y="{top2 - 12}" font-size="13">2. When the leading explanation changed (ticks), '
               f'against the events fixed in advance (dashed), 2003–26</text>')
    for row_i, (seed, rs) in enumerate(sorted(all_rows.items())):
        y = top2 + row_i * band
        out.append(f'<text x="10" y="{y + 14}">seed {seed}</text><line x1="{L}" y1="{y + 10}" x2="{W - R}" '
                   f'y2="{y + 10}" stroke="#ddd"/>')
        for i in range(1, len(rs)):
            if rs[i]["leader"] != rs[i - 1]["leader"]:
                out.append(f'<line x1="{x(i):.1f}" y1="{y + 2}" x2="{x(i):.1f}" y2="{y + 18}" stroke="#333" stroke-width="1.5"/>')
    bottom2 = top2 + band * len(all_rows)
    for name, day in scoring.EVENTS:
        i = next((k for k, w in enumerate(weeks) if date.fromisoformat(w) >= day), None)
        if i is not None:
            out.append(f'<line x1="{x(i):.1f}" y1="{top2 - 2}" x2="{x(i):.1f}" y2="{bottom2}" stroke="#c8553d" '
                       f'stroke-dasharray="3,3"><title>{name}</title></line>')
    for year in range(2004, 2027, 2):
        i = next(k for k, w in enumerate(weeks) if w.startswith(str(year)))
        out.append(f'<text x="{x(i):.1f}" y="{bottom2 + 14}" text-anchor="middle">{year}</text>')

    # Panel 3: yearly fit gap, median over seeds.
    top3, h3 = 470, 140
    years = sorted({w[:4] for w in weeks})
    gaps = {}
    for yr in years:
        per_seed = [scoring.fit_gap([r for r in rs if r["week"].startswith(yr)])["mean_gap_nats"] for rs in all_rows.values()]
        per_seed = [g for g in per_seed if g is not None]
        gaps[yr] = statistics.median(per_seed) if per_seed else 0.0
    scale = h3 / 2 / max(abs(g) for g in gaps.values())
    zero = top3 + h3 / 2
    out.append(f'<text x="{L}" y="{top3 - 12}" font-size="13">3. How much better the leading structure explains each '
               f'week than "nothing connects" (nats per week, median of seeds)</text>')
    out.append(f'<line x1="{L}" y1="{zero}" x2="{W - R}" y2="{zero}" stroke="#999"/>')
    bw = (W - L - R) / len(years)
    for k, yr in enumerate(years):
        g = gaps[yr]
        hgt = abs(g) * scale
        y = zero - hgt if g >= 0 else zero
        out.append(f'<rect x="{L + k * bw + 2:.1f}" y="{y:.1f}" width="{bw - 4:.1f}" height="{hgt:.1f}" '
                   f'fill="{"#3b6fb6" if g >= 0 else "#c8553d"}"/>')
        if int(yr) % 2 == 0:
            out.append(f'<text x="{L + k * bw + bw / 2:.1f}" y="{top3 + h3 + 14}" text-anchor="middle">{yr}</text>')
    out.append(f'<text x="10" y="{zero - h3 / 2 + 10}">better</text><text x="10" y="{zero + h3 / 2}">worse</text>')
    out.append("</svg>")
    return "\n".join(out)


def main(folder: Path = DATA, chart: Path = DOCS / "replay.svg") -> None:
    all_rows = {s: load(s, folder) for s in SEEDS}
    per_seed = {s: one_seed(rows) for s, rows in all_rows.items()}
    summary = {
        "median_family_changes": statistics.median(p["family_changes"] for p in per_seed.values()),
        "median_events_caught": statistics.median(p["n_events_caught"] for p in per_seed.values()),
        "median_chance_caught": statistics.median(p["chance_mean_caught"] for p in per_seed.values()),
        "median_changes_away": statistics.median(p["changes_away_from_events"] for p in per_seed.values()),
        "median_fit_gap_nats": statistics.median(p["fit_gap"]["mean_gap_nats"] for p in per_seed.values()),
        "credit_stand_in_agreement": credit_agreement(fh.load()),
    }
    results = {"summary": summary, "per_seed": per_seed}
    (folder / "results.json").write_text(json.dumps(results, indent=1, default=str))
    chart.parent.mkdir(exist_ok=True)
    chart.write_text(svg(all_rows))
    print(json.dumps(summary, indent=1))
    for s, p in per_seed.items():
        print(f"seed {s}: {p['family_changes']} family changes, events caught {p['n_events_caught']}/"
              f"{len(scoring.EVENTS)} (chance {p['chance_mean_caught']}, p={p['p_chance_catches_as_many']}), "
              f"away from events {p['changes_away_from_events']}, fit gap {p['fit_gap']['mean_gap_nats']}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DATA)
    parser.add_argument("--svg", type=Path, default=DOCS / "replay.svg")
    args = parser.parse_args()
    main(args.dir, args.svg)
