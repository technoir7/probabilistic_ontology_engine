"""
REFACTOR_SPEC 5.6 / A6: a public way to rebuild a domain from scratch, so the
art package stops popping engine internals and running raw DELETEs (which
miss the tables added in migration 0002).
"""
from __future__ import annotations

import sqlite3

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine

DOMAIN_ID = "test-domain-v1"
TABLES = ("evidence_records", "ontology_populations", "ontology_candidates", "candidate_scores",
          "paradigm_shifts", "parameters", "candidate_edges", "candidate_parameters")


def _counts(path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    conn.close()
    return out


def test_reset_domain_forgets_everything_and_reseeds(tmp_path):
    db = str(tmp_path / "x.db")
    engine = ProbabilisticOntologyEngine(db_path=db)
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    for _ in range(5):
        batch = gen.sample(30)
        engine.ingest_batch(batch)
        engine.learn(batch)
    assert engine.get_population().generation > 0

    engine.reset_domain(DOMAIN_ID)

    pop = engine.get_population()
    assert pop.generation == 0
    assert sorted(c.description for c in pop.candidates) == ["T*", "T_alt", "null"]
    assert all(c.evidence_count == 0 for c in pop.candidates)
    assert engine.learning_stats(DOMAIN_ID)["learn_calls"] == 0
    counts = _counts(db)
    for table in ("evidence_records", "candidate_scores", "paradigm_shifts", "parameters"):
        assert counts[table] == 0, table
    # Only the fresh seeds remain.
    assert counts["ontology_candidates"] == 3
    assert counts["candidate_edges"] == sum(len(c.edges) for c in pop.candidates)

    # A restart resumes the fresh population, not the old one.
    restarted = ProbabilisticOntologyEngine(db_path=db)
    restarted.register_domain(TestDomainV1())
    assert restarted.get_population(DOMAIN_ID).generation == 0
