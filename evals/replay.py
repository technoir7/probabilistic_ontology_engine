"""
Replays history through a fresh engine, period by period, as the app learns it.

    uv run python -m evals.replay --seed 0 [--start 2006-01-06] [--end 2008-12-26]

Each period: take the domain's evidence record (for macro, built from what
FRED had published, `fred_history`; for art, `replay_art`), score it under
the leading candidate and under a baseline that treats the signals as
independent, both before learning it (as the engine scores), then store and
learn it with the app's own `ingest_and_learn`. One row per period, written
to `evals/data/replay/`.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from src.domains.macro_regime_v1.domain import MacroRegimeV1
from src.domains.macro_regime_v1.ingestion.pipeline import MacroRegimePipeline, compute_snapshot
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.doubt import DISCOUNT as DOUBT_DISCOUNT
from src.engine.model.scoring import log_bayes_factor, structure_entropy
from src.engine.model.temporal import lagged
from src.engine.runtime.ingestion import ingest_and_learn
from src.engine.schemas import EvidenceRecord, OntologyCandidate

from . import fred_history as fh

DATA = Path(__file__).parent / "data" / "replay"


def fridays(start: date, end: date) -> list[date]:
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    return [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]


def _independent(module) -> OntologyCandidate:
    return OntologyCandidate(candidate_id=uuid4(), domain_module_id=module.module_id(), generation=0,
                             variables=[v for v in module.variables() if not v.lag_of], edges=[],
                             description="independent signals (baseline)")


def run(history: dict, seed: int, start: date, end: date, credit: str = fh.CREDIT_STAND_IN) -> list[dict]:
    """Macro, every Friday from START to END."""
    records = ((week, MacroRegimePipeline.build_evidence_record(compute_snapshot(fh.week_inputs(history, week, credit), week)))
               for week in fridays(start, end))
    return replay(MacroRegimeV1(), records, seed)


def replay(module, records: Iterable[tuple[date, EvidenceRecord]], seed: int) -> list[dict]:
    """Learn each (date, record) in turn; one row each. "week" is the period's
    date: a Friday for macro, a month-end for art."""
    domain = module.module_id()
    names = {str(v.variable_id): v.name for v in module.variables()}
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(module)
    engine.activate_domain(domain)
    pop = engine.population_manager.get_population(domain)
    baseline = _independent(module)
    engine.learning_service.initialize_candidate(baseline)

    rows = []
    previous = None
    for when, record in records:
        leader = engine.population_manager.dominant(domain)
        # Scored as the engine scores it: with last period's values attached.
        leader_ll = engine.learning_service.compute_log_likelihood(lagged([record], previous, leader.variables), leader)
        previous = record
        independent_ll = engine.learning_service.compute_log_likelihood([record], baseline)

        async def fetch(_: date, record=record):
            return record
        doubts = engine.doubt_events(domain)
        asyncio.run(ingest_and_learn(engine, domain, fetch, when))
        # The baseline forgets as the candidates do (D17), so the comparison
        # is structure against independence, not memory against memory.
        if engine.doubt_events(domain) > doubts:
            for cpt in engine.parameter_store.get_all_for_candidate(baseline.candidate_id).values():
                cpt.discount(DOUBT_DISCOUNT)
        engine.learning_service.accumulate([record], baseline)

        now = engine.population_manager.dominant(domain)
        rows.append({
            "week": when.isoformat(),
            "leader": str(now.candidate_id),
            "family": now.lineage,
            "edges": held_links(now),
            "leader_ll": leader_ll,
            "independent_ll": independent_ll,
            "observed": sum(a.missingness.value != "MISSING" for a in record.observed_assignments),
            "states": {names[str(a.variable_id)]: a.observed_value for a in record.observed_assignments},
            "entropy": structure_entropy(pop.active_candidates()),
            "active_families": dict(sorted(Counter(c.lineage for c in pop.active_candidates()).items())),
            "active": len(pop.active_candidates()),
            "doubt": engine.doubt_events(domain) > doubts,
            "population_ll": engine.epistemic_health(domain)["last_cycle"].get("population_ll"),
            "forecast_ll": engine.epistemic_health(domain)["last_cycle"].get("forecast_ll"),
            "programmes": programmes(pop.active_candidates(), now),
        })
    rows[-1]["health"] = engine.epistemic_health(domain)
    return rows


def held_links(candidate: OntologyCandidate) -> list[str]:
    """The links CANDIDATE reasons with, as "parent_id>child_id". Not those
    edge existence has switched off: replays 11–14 as first run counted
    those as held."""
    return sorted(f"{e.parent_variable_id}>{e.child_variable_id}" for e in candidate.get_active_edges())


def programmes(active: list[OntologyCandidate], leader: OntologyCandidate) -> dict:
    """Each surviving programme's best candidate: the evidence for the leader
    over it (what pruning judges), its links, the evidence it has been scored
    on, and whether it still holds the connection that founded it (D24)."""
    best: dict[str, OntologyCandidate] = {}
    for c in sorted(active, key=lambda c: log_bayes_factor(leader, c)):
        best.setdefault(c.lineage, c)
    out = {}
    for family, c in sorted(best.items()):
        pair = family.split("–") if "–" in family else None
        held = {frozenset(e) for e in c.edge_structure_signature()}
        out[family] = {"log_bf": round(log_bayes_factor(leader, c), 3), "edges": len(c.get_active_edges()),
                       "window": round(c.window_evidence, 1),
                       "core_kept": frozenset(pair) in held if pair else None}
    return out


def write_rows(path: Path, rows: list[dict]) -> None:
    """One JSON row a week, gzipped when the name ends in .gz."""
    text = "".join(json.dumps(r) + "\n" for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode(), mtime=0))
    else:
        path.write_text(text)


def read_rows(path: Path) -> list[dict]:
    text = gzip.decompress(path.read_bytes()).decode() if path.suffix == ".gz" else path.read_text()
    return [json.loads(line) for line in text.splitlines()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2003, 4, 4))
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--credit", default=fh.CREDIT_STAND_IN, choices=[fh.CREDIT_STAND_IN, fh.CREDIT])
    parser.add_argument("--out", default=None)
    parser.add_argument("--as-published", action="store_true",
                        help="CPI and unemployment as first published (ALFRED vintages), not as revised")
    args = parser.parse_args()
    history = fh.load()
    if args.as_published:
        history = fh.as_first_published(history, fh.load_vintages())
    end = args.end or max(o.obs_date for o in fh.load()["WALCL"])
    rows = run(history, args.seed, args.start, end, args.credit)
    DATA.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else DATA / f"seed{args.seed}.jsonl.gz"
    write_rows(out, rows)
    print(f"{len(rows)} weeks, {rows[0]['week']} to {rows[-1]['week']} -> {out}")
