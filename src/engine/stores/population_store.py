"""
PopulationStore — SQLite-backed store for OntologyPopulation and OntologyCandidate metadata.
Scores and status are persisted here; CPT data lives in ParameterStore (in-memory).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ..schemas import CandidateStatus, OntologyCandidate, OntologyPopulation


_POPULATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS ontology_populations (
    population_id         TEXT PRIMARY KEY,
    domain_module_id      TEXT NOT NULL UNIQUE,
    max_population_size   INT  NOT NULL DEFAULT 10,
    active_candidate_id   TEXT,
    generation            INT  NOT NULL DEFAULT 0,
    paradigm_shift_count  INT  NOT NULL DEFAULT 0,
    updated_at            TEXT NOT NULL
)
"""

_CANDIDATES_TABLE = """
CREATE TABLE IF NOT EXISTS ontology_candidates (
    candidate_id         TEXT PRIMARY KEY,
    domain_module_id     TEXT NOT NULL,
    generation           INT  NOT NULL DEFAULT 0,
    parent_candidate_id  TEXT,
    log_score            REAL NOT NULL DEFAULT 0.0,
    evidence_count       INT  NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'ACTIVE',
    introduced_at        TEXT NOT NULL,
    pruned_at            TEXT,
    pruning_reason       TEXT,
    description          TEXT NOT NULL DEFAULT '',
    metadata             TEXT NOT NULL DEFAULT '{}'
)
"""

_SCORES_TABLE = """
CREATE TABLE IF NOT EXISTS candidate_scores (
    score_id          TEXT PRIMARY KEY,
    candidate_id      TEXT NOT NULL,
    ts                TEXT NOT NULL,
    log_likelihood    REAL NOT NULL,
    batch_index       INT  NOT NULL DEFAULT 0,
    context           TEXT NOT NULL DEFAULT '{}'
)
"""


class PopulationStore:

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_POPULATIONS_TABLE)
        self._conn.execute(_CANDIDATES_TABLE)
        self._conn.execute(_SCORES_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Population CRUD
    # ------------------------------------------------------------------

    def save_population(self, pop: OntologyPopulation) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ontology_populations
              (population_id, domain_module_id, max_population_size,
               active_candidate_id, generation, paradigm_shift_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(pop.population_id),
                pop.domain_module_id,
                pop.max_population_size,
                str(pop.active_candidate_id) if pop.active_candidate_id else None,
                pop.generation,
                pop.paradigm_shift_count,
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def load_population_id(self, domain_module_id: str) -> UUID | None:
        cur = self._conn.execute(
            "SELECT population_id FROM ontology_populations WHERE domain_module_id=?",
            (domain_module_id,),
        )
        row = cur.fetchone()
        return UUID(row["population_id"]) if row else None

    # ------------------------------------------------------------------
    # Candidate CRUD
    # ------------------------------------------------------------------

    def save_candidate(self, cand: OntologyCandidate) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ontology_candidates
              (candidate_id, domain_module_id, generation, parent_candidate_id,
               log_score, evidence_count, status, introduced_at, pruned_at,
               pruning_reason, description, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(cand.candidate_id),
                cand.domain_module_id,
                cand.generation,
                str(cand.parent_candidate_id) if cand.parent_candidate_id else None,
                cand.log_score,
                cand.evidence_count,
                cand.status.value,
                cand.introduced_at.isoformat(),
                cand.pruned_at.isoformat() if cand.pruned_at else None,
                cand.pruning_reason,
                cand.description,
                "{}",
            ),
        )
        self._conn.commit()

    def update_score(self, candidate_id: UUID, log_score: float, evidence_count: int) -> None:
        self._conn.execute(
            "UPDATE ontology_candidates SET log_score=?, evidence_count=? WHERE candidate_id=?",
            (log_score, evidence_count, str(candidate_id)),
        )
        self._conn.commit()

    def mark_pruned(self, candidate_id: UUID, reason: str) -> None:
        self._conn.execute(
            """
            UPDATE ontology_candidates
            SET status='PRUNED', pruned_at=?, pruning_reason=?
            WHERE candidate_id=?
            """,
            (datetime.utcnow().isoformat(), reason, str(candidate_id)),
        )
        self._conn.commit()

    def append_score_record(
        self,
        candidate_id: UUID,
        log_likelihood: float,
        batch_index: int = 0,
    ) -> None:
        from uuid import uuid4
        self._conn.execute(
            """
            INSERT INTO candidate_scores (score_id, candidate_id, ts, log_likelihood, batch_index)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                str(candidate_id),
                datetime.utcnow().isoformat(),
                log_likelihood,
                batch_index,
            ),
        )
        self._conn.commit()
