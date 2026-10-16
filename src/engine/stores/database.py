"""
Database — one SQLite connection per database file, shared by every store.

Gives the stores one transaction boundary: inside ``transaction()`` their
``commit()`` calls are deferred, so a learning cycle's scores, CPTs and
population metadata land together or not at all. Owns schema migrations
(``migrations/NNNN_*.sql``, shared with PostgreSQL).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        # Row supports both row[0] and row["column"]; the stores use both.
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        # Callers serialize access per domain; the lock makes one connection
        # safe if two threads ever do reach it at once.
        self._lock = threading.RLock()
        self._depth = 0
        self._upgrade_pre_migration_parameters_table()
        self._migrate()

    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit everything inside on success, roll it all back on error. Re-entrant."""
        with self._lock:
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.rollback()
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.commit()

    def commit(self) -> None:
        """Commit now, unless inside transaction() — then the outermost block commits."""
        if self._depth == 0:
            self.conn.commit()

    # ------------------------------------------------------------------
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0

    def _migrate(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        current = self.schema_version()
        for path in sorted(_MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(path.name[:4])
            if version <= current:
                continue
            # executescript commits first and runs the file as one script.
            self.conn.executescript(path.read_text(encoding="utf-8"))
            self.conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (version, path.stem, datetime.now(timezone.utc).isoformat()),
            )
            self.conn.commit()

    def _upgrade_pre_migration_parameters_table(self) -> None:
        """
        SQLite-only shim for databases older than the edge_signature columns.

        Those columns were added by ALTER TABLE before migrations existed; a
        database from before that has a parameters table that 0001's
        CREATE IF NOT EXISTS would leave as-is. Delete once no such database
        can exist (all deployments have run 0001).
        """
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='parameters'"
        ).fetchone()
        if not exists:
            return
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(parameters)")}
        for column in ("edge_signature", "domain_module_id"):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE parameters ADD COLUMN {column} TEXT")
        self.conn.commit()
