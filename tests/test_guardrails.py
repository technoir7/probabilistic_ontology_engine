"""
Guardrails that keep the refactor from regrowing (REFACTOR_SPEC §6): a size
budget per source file and the performance budgets from SPEC §20.7. They fail
CI instead of relying on someone noticing.
"""
from __future__ import annotations

import time
from pathlib import Path

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import InferenceQuery

SRC = Path(__file__).parents[1] / "src"
MAX_LINES = 600
# Over budget when the budget was introduced: may shrink, must not grow.
CEILINGS = {
    "domains/ai_regime_v1/ingestion/pipeline.py": 778,
    "domains/macro_regime_v1/ingestion/pipeline.py": 663,
}


def test_no_source_file_grows_past_its_budget():
    over = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > CEILINGS.get(rel, MAX_LINES):
            over.append(f"{rel}: {lines} lines (budget {CEILINGS.get(rel, MAX_LINES)})")
    assert not over, "split these files:\n" + "\n".join(over)


def _best_of(n: int, fn) -> float:
    best = float("inf")
    for _ in range(n):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _engine(db_path: str = ":memory:") -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=db_path)
    engine.register_domain(TestDomainV1())
    engine.activate_domain("test-domain-v1")
    return engine


def test_learning_cycle_of_50_records_under_2s(tmp_path):
    engine = _engine(str(tmp_path / "x.db"))
    gen = SyntheticDataGenerator(graph="T*", random_seed=3)
    for _ in range(5):  # a population with variants, not just the seeds
        engine.learn(gen.sample(50))
    assert _best_of(3, lambda: engine.learn(gen.sample(50))) < 2.0


def test_inference_query_under_200ms():
    engine = _engine()
    gen = SyntheticDataGenerator(graph="T*", random_seed=3)
    engine.learn(gen.sample(100))
    query = InferenceQuery(domain_module_id="test-domain-v1", target_variables=["A", "B", "C", "D", "E"])
    assert _best_of(3, lambda: engine.query(query)) < 0.2


def test_ingesting_a_record_under_50ms(tmp_path):
    engine = _engine(str(tmp_path / "x.db"))
    records = SyntheticDataGenerator(graph="T*", random_seed=3).sample(100)
    elapsed = _best_of(1, lambda: [engine.ingest(r) for r in records])
    assert elapsed / len(records) < 0.05


def test_resuming_a_grown_population_under_2s(tmp_path):
    db = str(tmp_path / "x.db")
    engine = _engine(db)
    gen = SyntheticDataGenerator(graph="T*", random_seed=3)
    for _ in range(100):
        engine.learn(gen.sample(10))
    assert _best_of(3, lambda: _engine(db)) < 2.0
