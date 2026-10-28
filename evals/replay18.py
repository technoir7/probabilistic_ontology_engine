"""
Replay 18 (evals/README.md): the artists' case engine with each artist's
own past graded finely, against five deals of the leader's mechanisms
within each year.

    uv run python -m evals.replay18
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import replace

from src.domains.art_prestige_regime_v1 import cases
from src.engine.model.cases import CaseSet
from src.engine.services.cases import case_report

from .artist_records import POOL, YEARS, artists, records

DEALS = 5


def dealt(s: CaseSet, features: tuple[str, ...], rng: random.Random) -> CaseSet:
    """FEATURES' joint values dealt among the same year's closed case-years,
    keeping how common each is and breaking its tie to the case. Weighted
    rows are dealt as units, so whole groups move together."""
    by_year = defaultdict(list)
    for i, r in enumerate(s.records):
        if r.outcome is not None:
            by_year[r.year].append(i)
    out = list(s.records)
    for idx in by_year.values():
        values = [s.records[i] for i in idx]
        weights = [r.weight for r in values]
        # Expand to single cases so a deal moves cases, not groups.
        flat = [tuple(r.features[f] for f in features) for r, w in zip(values, weights) for _ in range(w)]
        rng.shuffle(flat)
        pos = 0
        for i in idx:
            r = s.records[i]
            out[i] = None
            for v in flat[pos:pos + r.weight]:
                out.append(replace(r, features={**r.features, **dict(zip(features, v))}, weight=1))
            pos += r.weight
    return replace(s, records=tuple(r for r in out if r is not None))


def main() -> None:
    rows = records(artists(), YEARS, POOL)
    s = cases.load(cases.dump("artists", "Artists", "museum acquisitions next year", POOL, rows, {}))
    report = case_report(s)
    print(f"{sum(r.weight for r in s.records if r.outcome is not None)} closed artist-years, "
          f"{sum(r.outcome is None for r in s.records)} open (2025)")
    for y in report.years:
        print(f"{y.year}: engine - own past {y.engine - y.own_past:+.1f}")
    print(f"leader {report.leader or '(own past)'}; gain {report.gain:+.1f} nats; "
          f"shifts {[(x.year, x.frm, x.to) for x in report.shifts]}", flush=True)
    if not report.leader:
        return
    gains = []
    for seed in range(DEALS):
        d = case_report(dealt(s, report.leader, random.Random(seed)))
        gains.append(d.gain)
        print(f"deal {seed}: leader {d.leader or '(own past)'}; gain {d.gain:+.1f}", flush=True)
    print(f"real {report.gain:+.1f} vs deals max {max(gains):+.1f}")


if __name__ == "__main__":
    main()
