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
            """SELECT evidence_id, timestamp, source_type, source_ref, confidence, assignments
               FROM evidence_records WHERE domain_module=? ORDER BY timestamp""",
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
    def load_recent(self, domain_module_id: str, limit: int = 20) -> list[dict]:
        """Return the most recent *limit* records as plain dicts for API serialisation."""
        cur = self._conn.execute(
            """SELECT evidence_id, timestamp, source_type, source_ref, confidence, assignments
               FROM evidence_records WHERE domain_module=?
               ORDER BY timestamp DESC LIMIT ?""",
            (domain_module_id, limit),
        )
        records = []
        for row in cur.fetchall():
            records.append({
                "evidence_id": row[0],
                "timestamp": row[1],
                "source_type": row[2],
                "source_ref": row[3] or "",
                "confidence": row[4],
                "assignments": json.loads(row[5]) if row[5] else [],
            })
        return records

    # ------------------------------------------------------------------
    def migrate_variable_ids_by_position(
        self,
        domain_module_id: str,
        variables: list,
    ) -> dict[str, int]:
        """
        Rewrite legacy evidence assignment UUIDs to stable IDs when safe.

        Older domain modules generated variable UUIDs at import time.  If a
        stored record has zero current-ID matches but the same assignment count
        as the current domain variables, the domain pipeline's assignment order
        gives us a safe compatibility path.
        """
        current_ids = {str(variable.variable_id) for variable in variables}
        cur = self._conn.execute(
            "SELECT evidence_id, assignments FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        )
        migrated_records = 0
        migrated_assignments = 0
        mismatched_records = 0
        for evidence_id, assignments_json in cur.fetchall():
            assignments = json.loads(assignments_json) if assignments_json else []
            if len(assignments) != len(variables):
                mismatched_records += 1
                continue
            matched = sum(
                1 for assignment in assignments
                if str(assignment.get("variable_id")) in current_ids
            )
            if matched == len(assignments):
                continue
            if matched > 0:
                mismatched_records += 1
                continue
            for variable, assignment in zip(variables, assignments):
                assignment["variable_id"] = str(variable.variable_id)
            self._conn.execute(
                "UPDATE evidence_records SET assignments=? WHERE evidence_id=?",
                (json.dumps(assignments), evidence_id),
            )
            migrated_records += 1
            migrated_assignments += len(assignments)
        if migrated_records:
            self._conn.commit()
        return {
            "migrated_records": migrated_records,
            "migrated_assignments": migrated_assignments,
            "mismatched_records": mismatched_records,
        }

    # ------------------------------------------------------------------
    def latest_timestamp(self, domain_module_id: str) -> str | None:
        """Return the ISO timestamp of the most recent record, or None."""
        cur = self._conn.execute(
            "SELECT MAX(timestamp) FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    # ------------------------------------------------------------------
    def clear(self, domain_module_id: str) -> None:
        self._conn.execute(
            "DELETE FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        )
        self._conn.commit()


def _row_to_record(row: tuple) -> EvidenceRecord:
    from ..schemas import ObservedAssignment, MissingnessType, SourceType
    assignments_data = json.loads(row[5])
    assignments = []
    for a in assignments_data:
        assignments.append(ObservedAssignment(
            variable_id=UUID(a["variable_id"]),
            observed_value=a["observed_value"],
            missingness=MissingnessType(a.get("missingness", "OBSERVED")),
            confidence=a.get("confidence", 1.0),
            probabilities=a.get("probabilities"),
        ))
    return EvidenceRecord(
        evidence_id=UUID(row[0]),
        timestamp=datetime.fromisoformat(row[1]),
        observed_assignments=assignments,
        source_type=SourceType(row[2]),
        source_ref=row[3] or "",
        confidence=row[4],
    )
