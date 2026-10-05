"""REFACTOR_SPEC 3.1: one connection, a real transaction boundary, migrations."""
from __future__ import annotations

import sqlite3

import pytest

from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.stores.database import Database


def test_all_stores_share_one_connection(tmp_path):
    engine = ProbabilisticOntologyEngine(db_path=str(tmp_path / "x.db"))
    conns = {id(engine.evidence_store._conn), id(engine.parameter_store._conn), id(engine.population_store._conn)}
    assert conns == {id(engine.db.conn)}


def test_transaction_commits_on_success_and_rolls_back_on_error(tmp_path):
    db = Database(tmp_path / "x.db")
    with db.transaction():
        db.conn.execute("INSERT INTO candidate_scores (score_id, candidate_id, ts, log_likelihood) VALUES ('a', 'c', 't', 0)")
        db.commit()  # deferred inside a transaction
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.conn.execute("INSERT INTO candidate_scores (score_id, candidate_id, ts, log_likelihood) VALUES ('b', 'c', 't', 0)")
            db.commit()
            raise RuntimeError("boom")

    other = sqlite3.connect(tmp_path / "x.db")
    ids = [r[0] for r in other.execute("SELECT score_id FROM candidate_scores")]
    assert ids == ["a"]


def test_migrations_apply_once_and_adopt_pre_migration_databases(tmp_path):
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE evidence_records (evidence_id TEXT PRIMARY KEY, domain_module TEXT NOT NULL, "
                   "timestamp TEXT NOT NULL, source_type TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '', "
                   "confidence REAL NOT NULL DEFAULT 1.0, assignments TEXT NOT NULL DEFAULT '[]')")
    legacy.execute("INSERT INTO evidence_records VALUES ('e1', 'd', 't', 'API', '', 1.0, '[]')")
    legacy.commit()
    legacy.close()

    first = Database(path)
    version = first.schema_version()
    assert version >= 1
    assert first.conn.execute("SELECT COUNT(*) FROM evidence_records").fetchone()[0] == 1
    first.conn.close()
    assert Database(path).schema_version() == version
