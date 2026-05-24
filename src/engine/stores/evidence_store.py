"""
EvidenceStore — SQLite-backed append-only store for EvidenceRecords.
Schema is PostgreSQL-compatible (uses JSONB as TEXT fallback in SQLite).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ..schemas import EvidenceRecord


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id   TEXT PRIMARY KEY,
    domain_module TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 1.0,
    assignments   TEXT NOT NULL DEFAULT '[]'  -- JSON array
)
"""


class EvidenceStore:
    """Thread-safe SQLite evidence store per domain module."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    def append(self, record: EvidenceRecord, domain_module_id: str) -> None:
        assignments_json = json.dumps(
            [a.model_dump(mode="json") for a in record.observed_assignments]
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO evidence_records
              (evidence_id, domain_module, timestamp, source_type, source_ref, confidence, assignments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.evidence_id),
                domain_module_id,
                record.timestamp.isoformat(),
                record.source_type.value,
                record.source_ref,
                record.confidence,
                assignments_json,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def append_batch(self, records: list[EvidenceRecord], domain_module_id: str) -> None:
        rows = []
        for r in records:
            rows.append((
                str(r.evidence_id),
                domain_module_id,
                r.timestamp.isoformat(),
                r.source_type.value,
                r.source_ref,
                r.confidence,
                json.dumps([a.model_dump(mode="json") for a in r.observed_assignments]),
            ))
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO evidence_records
              (evidence_id, domain_module, timestamp, source_type, source_ref, confidence, assignments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def load_all(self, domain_module_id: str) -> list[EvidenceRecord]:
        cur = self._conn.execute(
            "SELECT assignments FROM evidence_records WHERE domain_module=? ORDER BY timestamp",
            (domain_module_id,),
        )
        return [_row_to_record(row) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    def count(self, domain_module_id: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        )
        return cur.fetchone()[0]

    # ------------------------------------------------------------------
    def clear(self, domain_module_id: str) -> None:
        self._conn.execute(
            "DELETE FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        )
        self._conn.commit()


def _row_to_record(row: tuple) -> EvidenceRecord:
    from ..schemas import ObservedAssignment, MissingnessType, SourceType
    assignments_data = json.loads(row[0])
    assignments = []
    for a in assignments_data:
        assignments.append(ObservedAssignment(
            variable_id=UUID(a["variable_id"]),
            observed_value=a["observed_value"],
            missingness=MissingnessType(a.get("missingness", "OBSERVED")),
            confidence=a.get("confidence", 1.0),
        ))
    return EvidenceRecord(observed_assignments=assignments)
