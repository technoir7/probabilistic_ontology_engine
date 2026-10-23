"""
Replays history through a fresh engine, week by week, as the app learns it.

    uv run python -m evals.replay --seed 0 [--start 2006-01-06] [--end 2008-12-26]

Each week: build the macro domain's evidence record from what FRED had
published (`fred_history`), score it under the leading candidate and under a
baseline that treats the eight signals as independent, both before learning
it (as the engine scores), then store and learn it with the app's own
`ingest_and_learn`. One row per week, written to `evals/data/replay/`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from src.domains.macro_regime_v1.domain import MacroRegimeV1, get_variables
from src.domains.macro_regime_v1.ingestion.pipeline import MacroRegimePipeline, compute_snapshot
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.doubt import DISCOUNT as DOUBT_DISCOUNT
from src.engine.model.scoring import structure_entropy
from src.engine.runtime.ingestion import ingest_and_learn
from src.engine.schemas import OntologyCandidate

from . import fred_history as fh

DATA = Path(__file__).parent / "data" / "replay"
DOMAIN = "macro-regime-v1"


def fridays(start: date, end: date) -> list[date]:
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    return [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]


def family_of(candidate_id: str, parents: dict[str, str | None], seeds: dict[str, str]) -> str:
    """The seed explanation a candidate descends from."""
    seen = set()
    current: str | None = candidate_id
    while current is not None and current not in seen:
        if current in seeds:
            return seeds[current]
        seen.add(current)
        current = parents.get(current)
    return "unknown"


def _independent() -> OntologyCandidate:
    return OntologyCandidate(candidate_id=uuid4(), domain_module_id=DOMAIN, generation=0,
                             variables=list(get_variables().values()), edges=[],
                             description="independent signals (baseline)")


def run(history: dict, seed: int, start: date, end: date, credit: str = fh.CREDIT_STAND_IN) -> list[dict]:
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=seed)
    engine.register_domain(MacroRegimeV1())
    engine.activate_domain(DOMAIN)
    pop = engine.population_manager.get_population(DOMAIN)
    seeds = {str(c.candidate_id): c.description.split(":")[0] for c in pop.candidates}
    parents: dict[str, str | None] = {}
    baseline = _independent()
    engine.learning_service.initialize_candidate(baseline)

    rows = []
    for week in fridays(start, end):
        record = MacroRegimePipeline.build_evidence_record(compute_snapshot(fh.week_inputs(history, week, credit), week))
        leader = engine.population_manager.dominant(DOMAIN)
        leader_ll = engine.learning_service.compute_log_likelihood([record], leader)
        independent_ll = engine.learning_service.compute_log_likelihood([record], baseline)

        async def fetch(_: date, record=record):
            return record
        doubts = engine.doubt_events(DOMAIN)
        asyncio.run(ingest_and_learn(engine, DOMAIN, fetch, week))
        # The baseline forgets as the candidates do (D17), so the comparison
        # is structure against independence, not memory against memory.
        if engine.doubt_events(DOMAIN) > doubts:
            for cpt in engine.parameter_store.get_all_for_candidate(baseline.candidate_id).values():
                cpt.discount(DOUBT_DISCOUNT)
        engine.learning_service.accumulate([record], baseline)

        for c in pop.candidates:
            parents.setdefault(str(c.candidate_id), str(c.parent_candidate_id) if c.parent_candidate_id else None)
        now = engine.population_manager.dominant(DOMAIN)
        rows.append({
            "week": week.isoformat(),
            "leader": str(now.candidate_id),
            "family": family_of(str(now.candidate_id), parents, seeds),
            "edges": sorted(f"{e.parent_variable_id}>{e.child_variable_id}" for e in now.edges),
            "leader_ll": leader_ll,
            "independent_ll": independent_ll,
            "observed": sum(a.missingness.value != "MISSING" for a in record.observed_assignments),
            "states": {get_name(a.variable_id): a.observed_value for a in record.observed_assignments},
            "entropy": structure_entropy(pop.active_candidates()),
            "active_families": dict(sorted(Counter(family_of(str(c.candidate_id), parents, seeds)
                                                   for c in pop.active_candidates()).items())),
            "active": len(pop.active_candidates()),
            "doubt": engine.doubt_events(DOMAIN) > doubts,
            "population_ll": engine.epistemic_health(DOMAIN)["last_cycle"].get("population_ll"),
            "forecast_ll": engine.epistemic_health(DOMAIN)["last_cycle"].get("forecast_ll"),
        })
    rows[-1]["health"] = engine.epistemic_health(DOMAIN)
    return rows


_NAMES = {str(v.variable_id): v.name for v in get_variables().values()}


def get_name(variable_id) -> str:
    return _NAMES[str(variable_id)]


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
    out = Path(args.out) if args.out else DATA / f"seed{args.seed}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} weeks, {rows[0]['week']} to {rows[-1]['week']} -> {out}")
