"""
Integration test — ParameterStore SQLite persistence across engine restarts.

Scenario (matches the manual verification in the task):
  1. Start engine with a real SQLite file.
  2. Ingest + learn 5 evidence records → parameters flushed to DB via
     save_candidate(candidate_id, domain_module_id, edge_signature).
  3. Capture CPT count totals and parameter hashes keyed by edge_signature.
  4. Destroy the engine object (simulates a restart).
  5. Create a brand-new engine pointing at the same DB file.
  6. register_domain() initialises fresh candidates (new ephemeral UUIDs)
     then calls load_from_db(domain_id, sig→uuid_map), which matches
     by (domain_module_id, edge_signature) and restores the saved counts.
  7. Verify that the restored CPT counts match those from the first 5 records.
  8. Ingest + learn 1 more record → counts grow, not reset.

Why candidate_id can't be used as the stable cross-session key:
  All domain modules call uuid4() when building initial_candidates(), so the
  candidate UUIDs are session-local and differ on every restart.  The stable
  key is (domain_module_id, edge_signature) where edge_signature is a sorted
  JSON array of (parent_name, child_name) active-edge pairs.
"""
from __future__ import annotations

import sys
import os
import json
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine, _candidate_edge_sig
from src.engine.stores.parameter_store import ParameterStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(db_path: str) -> ProbabilisticOntologyEngine:
    eng = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    domain = TestDomainV1()
    eng.register_domain(domain)
    eng.activate_domain(domain.module_id())
    return eng


def _total_counts_for_sig(
    ps: ParameterStore,
    candidates,
    target_sig: str,
) -> float:
    """Sum all count values across all CPTs for the candidate with the given edge_signature."""
    for cand in candidates:
        if _candidate_edge_sig(cand) == target_sig:
            total = 0.0
            for cpt in ps.get_all_for_candidate(cand.candidate_id).values():
                for row in cpt.counts.values():
                    total += sum(row.values())
            return total
    return 0.0


# ---------------------------------------------------------------------------
# TEST: parameters survive a full engine restart
# ---------------------------------------------------------------------------

def test_parameters_persist_across_restart(tmp_path):
    """
    Engine instance 1: ingest 5 records, learn → flush to DB.
    Engine instance 2 (same DB): parameters from those 5 records are present.
    After 1 more record + learn: count total is higher, not reset.
    """
    db_file = str(tmp_path / "test_domain.db")
    gen = SyntheticDataGenerator(graph="T*", random_seed=99)
    domain_id = TestDomainV1().module_id()

    # ── Session 1: 5 records ──────────────────────────────────────────────
    eng1 = _make_engine(db_file)
    batch_5 = gen.sample(n=5)
    for rec in batch_5:
        eng1.ingest(rec)

    eng1.learn(batch_5)

    pop1 = eng1.get_population(domain_id)
    active1 = pop1.active_candidates()

    # Capture the edge signature of each initial candidate and its count total
    # Use ALL active candidates (the initial 3 ± any variants introduced)
    sig_counts_s1: dict[str, float] = {}
    sig_hashes_s1: dict[str, str] = {}
    for cand in active1:
        sig = _candidate_edge_sig(cand)
        total = 0.0
        for cpt in eng1.parameter_store.get_all_for_candidate(cand.candidate_id).values():
            for row in cpt.counts.values():
                total += sum(row.values())
        sig_counts_s1[sig] = total
        sig_hashes_s1[sig] = eng1.parameter_store.parameter_hash(cand.candidate_id)

    assert any(v > 0 for v in sig_counts_s1.values()), (
        "No counts accumulated after 5 records"
    )

    # Explicitly drop the engine
    del eng1

    # ── Session 2: new engine, same DB file ───────────────────────────────
    eng2 = _make_engine(db_file)
    pop2 = eng2.get_population(domain_id)
    active2 = pop2.active_candidates()

    # Each initial candidate has a NEW candidate_id in session 2, but
    # its edge_signature is the same → load_from_db should have restored it.
    for cand2 in active2:
        sig = _candidate_edge_sig(cand2)
        if sig not in sig_counts_s1:
            # Variant introduced in session 1 that isn't present in session 2
            continue

        counts_s1 = sig_counts_s1[sig]
        if counts_s1 == 0:
            continue  # this candidate had no data; nothing to check

        total_s2 = 0.0
        for cpt in eng2.parameter_store.get_all_for_candidate(cand2.candidate_id).values():
            for row in cpt.counts.values():
                total_s2 += sum(row.values())

        assert total_s2 == pytest.approx(counts_s1, rel=1e-9), (
            f"Counts for candidate with sig={sig[:60]}... differ after restart: "
            f"session1={counts_s1:.2f}, session2={total_s2:.2f}"
        )

        hash_s2 = eng2.parameter_store.parameter_hash(cand2.candidate_id)
        assert hash_s2 == sig_hashes_s1[sig], (
            f"Parameter hash for sig={sig[:60]}... changed after restart"
        )

    # ── Session 2 continued: 1 more record ───────────────────────────────
    extra_batch = gen.sample(n=1)
    for rec in extra_batch:
        eng2.ingest(rec)

    eng2.learn(extra_batch)

    pop2b = eng2.get_population(domain_id)
    for cand2 in pop2b.active_candidates():
        sig = _candidate_edge_sig(cand2)
        if sig not in sig_counts_s1 or sig_counts_s1[sig] == 0:
            continue

        total_after_6 = 0.0
        for cpt in eng2.parameter_store.get_all_for_candidate(cand2.candidate_id).values():
            for row in cpt.counts.values():
                total_after_6 += sum(row.values())

        assert total_after_6 > sig_counts_s1[sig], (
            f"Counts did not grow for sig={sig[:60]}... after 6th record: "
            f"before={sig_counts_s1[sig]:.2f}, after={total_after_6:.2f}"
        )


# ---------------------------------------------------------------------------
# TEST: parameters table is created with expected schema
# ---------------------------------------------------------------------------

def test_parameters_table_schema(tmp_path):
    """
    Verify the 'parameters' table exists with the required columns after
    a learn() call.
    """
    db_file = str(tmp_path / "schema_check.db")
    gen = SyntheticDataGenerator(graph="T*", random_seed=7)

    eng = _make_engine(db_file)
    batch = gen.sample(n=3)
    for rec in batch:
        eng.ingest(rec)
    eng.learn(batch)
    del eng  # close engine / commit

    conn = sqlite3.connect(db_file)
    cur = conn.execute("SELECT * FROM parameters LIMIT 1")
    cols = [d[0] for d in cur.description]

    # Spec-required columns
    required_cols = {
        "candidate_id", "variable_name", "alpha",
        "counts_json", "parent_ids_json", "updated_at",
    }
    assert required_cols.issubset(set(cols)), (
        f"Missing spec-required columns: {required_cols - set(cols)}"
    )

    # Additional stable-key columns
    assert "domain_module_id" in cols, "domain_module_id column missing"
    assert "edge_signature" in cols, "edge_signature column missing"

    count = conn.execute("SELECT COUNT(*) FROM parameters").fetchone()[0]
    conn.close()
    assert count > 0, "parameters table is empty after learn()"


def test_parameters_table_migrates_legacy_schema(tmp_path):
    """
    Existing databases created before stable-key columns must be upgraded
    before load_from_db selects edge_signature/domain_module_id.
    """
    db_file = str(tmp_path / "legacy_schema.db")

    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE parameters (
            candidate_id     TEXT NOT NULL,
            variable_name    TEXT NOT NULL,
            alpha            REAL NOT NULL DEFAULT 1.0,
            counts_json      TEXT NOT NULL DEFAULT '[]',
            parent_ids_json  TEXT NOT NULL DEFAULT '[]',
            updated_at       TEXT NOT NULL,
            PRIMARY KEY (candidate_id, variable_name)
        )
        """
    )
    conn.commit()
    conn.close()

    store = ParameterStore(db_file)
    assert store._conn is not None
    cols = [row[1] for row in store._conn.execute("PRAGMA table_info(parameters)")]
    store._conn.close()

    assert "edge_signature" in cols
    assert "domain_module_id" in cols


# ---------------------------------------------------------------------------
# TEST: in-memory engine is unaffected (persistence is a no-op)
# ---------------------------------------------------------------------------

def test_in_memory_engine_unchanged():
    """
    Engines created with db_path=':memory:' must work exactly as before —
    save_candidate() and load_from_db() must be harmless no-ops.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=1)
    eng = _make_engine(":memory:")

    batch = gen.sample(n=20)
    for rec in batch:
        eng.ingest(rec)
    eng.learn(batch)

    pop = eng.get_population(TestDomainV1().module_id())
    dom = pop.dominant()
    assert dom is not None
    assert dom.evidence_count == 20
