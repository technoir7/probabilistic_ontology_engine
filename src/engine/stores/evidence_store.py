"""
EvidenceStore — SQLite-backed append-only store for EvidenceRecords.
Schema is PostgreSQL-compatible (uses JSONB as TEXT fallback in SQLite).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ..schemas import EvidenceRecord
from .database import Database


class EvidenceStore:
    """Append-only evidence records per domain module."""

    def __init__(self, db: Database | str | Path = ":memory:"):
        self._db = db if isinstance(db, Database) else Database(db)
        self._conn = self._db.conn
        self.db_path = self._db.path

    # ------------------------------------------------------------------
    def append(self, record: EvidenceRecord, domain_module_id: str) -> None:
        assignments_json = _assignments_json(record)
        self._conn.execute(
            """
            INSERT INTO evidence_records
              (evidence_id, domain_module, timestamp, source_type, source_ref, confidence, assignments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evidence_id) DO NOTHING
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
        self._db.commit()

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
                _assignments_json(r),
            ))
        self._conn.executemany(
            """
            INSERT INTO evidence_records
              (evidence_id, domain_module, timestamp, source_type, source_ref, confidence, assignments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (evidence_id) DO NOTHING
            """,
            rows,
        )
        self._db.commit()

    # ------------------------------------------------------------------
    def load_all(self, domain_module_id: str) -> list[EvidenceRecord]:
        """Every record for the domain, oldest first. Unbounded; prefer load_latest on request paths."""
        cur = self._conn.execute(
            """SELECT evidence_id, timestamp, source_type, source_ref, confidence, assignments
               FROM evidence_records WHERE domain_module=? ORDER BY timestamp""",
            (domain_module_id,),
        )
        return [_row_to_record(row) for row in cur.fetchall()]

    def load_latest(self, domain_module_id: str, limit: int | None) -> list[EvidenceRecord]:
        """The most recent *limit* records (all if None), oldest first."""
        if limit is None:
            return self.load_all(domain_module_id)
        cur = self._conn.execute(
            """SELECT evidence_id, timestamp, source_type, source_ref, confidence, assignments
               FROM evidence_records WHERE domain_module=? ORDER BY timestamp DESC LIMIT ?""",
            (domain_module_id, limit),
        )
        return [_row_to_record(row) for row in reversed(cur.fetchall())]

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
            self._db.commit()
        return {
            "migrated_records": migrated_records,
            "migrated_assignments": migrated_assignments,
            "mismatched_records": mismatched_records,
        }

    # ------------------------------------------------------------------
    def has_record_at(self, domain_module_id: str, timestamp: datetime) -> bool:
        """True if a record with exactly this timestamp is stored. One query; unindexed until Phase 3."""
        cur = self._conn.execute(
            "SELECT 1 FROM evidence_records WHERE domain_module=? AND timestamp=? LIMIT 1",
            (domain_module_id, timestamp.isoformat()),
        )
        return cur.fetchone() is not None

    # ------------------------------------------------------------------
    def restamp(self, domain_module_id: str, new_timestamp) -> tuple[int, int]:
        """
        Re-date records: *new_timestamp(ts)* returns the new datetime, or None
        to leave the record alone. A record whose new timestamp is already
        taken is deleted instead (that period is already represented).
        Returns (moved, deleted). One read of all timestamps, then one write
        per changed record; the caller decides the transaction.
        """
        rows = self._conn.execute(
            "SELECT evidence_id, timestamp FROM evidence_records WHERE domain_module=?",
            (domain_module_id,),
        ).fetchall()
        taken = {row[1] for row in rows}
        moved = deleted = 0
        for evidence_id, ts in rows:
            new = new_timestamp(datetime.fromisoformat(ts))
            if new is None:
                continue
            new_ts = new.isoformat()
            if new_ts in taken:
                self._conn.execute("DELETE FROM evidence_records WHERE evidence_id=?", (evidence_id,))
                deleted += 1
            else:
                self._conn.execute(
                    "UPDATE evidence_records SET timestamp=? WHERE evidence_id=?", (new_ts, evidence_id)
                )
                taken.discard(ts)
                taken.add(new_ts)
                moved += 1
        self._db.commit()
        return moved, deleted

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
        self._db.commit()


def _assignments_json(record: EvidenceRecord) -> str:
    """
    JSON for a record's assignments, keeping soft-evidence keys' types.

    JSON object keys are always strings, so {True: 0.64} would come back as
    {"true": 0.64} and miss every CPT row keyed by True. Probabilities are
    stored as [[value, p], ...] pairs instead.
    """
    out = []
    for a in record.observed_assignments:
        data = a.model_dump(mode="json")
        if a.probabilities is not None:
            data["probabilities"] = [[value, p] for value, p in a.probabilities.items()]
        out.append(data)
    return json.dumps(out)


# Rows written before _assignments_json stored probabilities as a JSON object.
_LEGACY_BOOL_KEYS = {"true": True, "false": False}


def _probabilities_from_json(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return {value: p for value, p in raw}
    return {_LEGACY_BOOL_KEYS.get(k, k): p for k, p in raw.items()}


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
            probabilities=_probabilities_from_json(a.get("probabilities")),
        ))
    return EvidenceRecord(
        evidence_id=UUID(row[0]),
        timestamp=datetime.fromisoformat(row[1]),
        observed_assignments=assignments,
        source_type=SourceType(row[2]),
        source_ref=row[3] or "",
        confidence=row[4],
    )
