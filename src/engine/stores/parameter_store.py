"""
ParameterStore — CPT storage per candidate, with optional SQLite persistence.

Each candidate has one CPTData per variable.  CPTData holds:
  - sufficient statistics (counts)
  - Dirichlet prior alpha
  - parent variable names (sorted, for config key construction)
  - variable support (list of possible values)

Parent configuration key format: tuple of (parent_name, value) pairs,
sorted by parent_name, e.g. (("A", True), ("B", False)).

Persistence schema (one row per candidate × variable):
  parameters(candidate_id TEXT, variable_name TEXT, alpha REAL,
             counts_json TEXT, parent_ids_json TEXT, updated_at TIMESTAMP)
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_CREATE_PARAMETERS_TABLE = """
CREATE TABLE IF NOT EXISTS parameters (
    candidate_id     TEXT NOT NULL,
    domain_module_id TEXT NOT NULL DEFAULT '',
    edge_signature   TEXT NOT NULL DEFAULT '',
    variable_name    TEXT NOT NULL,
    alpha            REAL NOT NULL DEFAULT 1.0,
    counts_json      TEXT NOT NULL DEFAULT '[]',
    parent_ids_json  TEXT NOT NULL DEFAULT '[]',
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (domain_module_id, edge_signature, variable_name)
)
"""
# candidate_id is stored as-is per the spec; the actual stable primary key is
# (domain_module_id, edge_signature, variable_name) because candidate_id is a
# session-local UUID that changes on every restart.  domain_module_id +
# edge_signature together identify a structural variant stably across restarts.


# ---------------------------------------------------------------------------
# Counts serialisation helpers
# ---------------------------------------------------------------------------

def _serialize_counts(counts: dict) -> str:
    """
    Serialise a CPTData counts dict to JSON.

    counts key: tuple of (parent_name, value) pairs, e.g. (("A", True), ("B", False))
    counts value: dict of {support_value: float_count}

    Both tuple keys and dict keys are serialised via repr() so that
    ast.literal_eval() can round-trip booleans and strings faithfully.
    """
    entries = []
    for parent_config, val_dict in counts.items():
        entries.append({
            "k": repr(parent_config),
            "v": {repr(k): v for k, v in val_dict.items()},
        })
    return json.dumps(entries)


def _deserialize_counts(counts_json: str) -> dict:
    """Inverse of _serialize_counts."""
    entries = json.loads(counts_json)
    counts: dict = {}
    for entry in entries:
        key = ast.literal_eval(entry["k"])
        val_dict = {ast.literal_eval(k): v for k, v in entry["v"].items()}
        counts[key] = val_dict
    return counts


# ---------------------------------------------------------------------------
# CPTData
# ---------------------------------------------------------------------------

@dataclass
class CPTData:
    variable_name: str
    parents: list[str]              # sorted list of parent names
    support: list[Any]              # variable's possible values
    counts: dict                    # {parent_config_tuple: {value: count}}
    alpha: float = 1.0              # Dirichlet prior pseudo-count per cell

    def _all_parent_configs(self, parent_supports: dict[str, list[Any]]) -> list[tuple]:
        """Generate all parent configurations as sorted tuples."""
        if not self.parents:
            return [()]
        configs = [()]
        for p in self.parents:
            new_configs = []
            for cfg in configs:
                for val in parent_supports[p]:
                    new_configs.append(cfg + ((p, val),))
            configs = new_configs
        return configs

    def ensure_config(self, parent_config: tuple, parent_supports: dict[str, list[Any]]) -> None:
        """Initialize a config row with zero counts if not present."""
        if parent_config not in self.counts:
            self.counts[parent_config] = {v: 0 for v in self.support}

    def increment(self, value: Any, parent_assignment: dict[str, Any]) -> None:
        """Add 1 to the count for (parent_config, value)."""
        parent_config = tuple(sorted(
            (p, parent_assignment[p]) for p in self.parents
        ))
        if parent_config not in self.counts:
            self.counts[parent_config] = {v: 0 for v in self.support}
        if value in self.counts[parent_config]:
            self.counts[parent_config][value] += 1
        else:
            self.counts[parent_config][value] = 1

    def get_probability(self, value: Any, parent_assignment: dict[str, Any]) -> float:
        """Compute smoothed P(variable=value | parent_assignment)."""
        parent_config = tuple(sorted(
            (p, parent_assignment[p]) for p in self.parents
        ))
        r = len(self.support)
        row = self.counts.get(parent_config, {})
        n_q = sum(row.values())
        n_qk = row.get(value, 0)
        return (n_qk + self.alpha) / (n_q + self.alpha * r)

    def get_cpt_dict(self) -> dict:
        """Return full normalized CPT as a dict for inspection."""
        r = len(self.support)
        result = {}
        for parent_config, row in self.counts.items():
            n_q = sum(row.values())
            result[str(parent_config)] = {
                v: (row.get(v, 0) + self.alpha) / (n_q + self.alpha * r)
                for v in self.support
            }
        return result

    def log_prob(self, value: Any, parent_assignment: dict[str, Any]) -> float:
        p = self.get_probability(value, parent_assignment)
        return math.log(max(p, 1e-12))

    def mle_log_likelihood(self) -> float:
        """Log-likelihood of all data under MLE (no smoothing)."""
        ll = 0.0
        for parent_config, row in self.counts.items():
            n_q = sum(row.values())
            if n_q == 0:
                continue
            for v, n_qk in row.items():
                if n_qk > 0:
                    ll += n_qk * math.log(n_qk / n_q)
        return ll

    def bic_score(self) -> float:
        """BIC score = log_lik_MLE - 0.5 * num_free_params * log(N)."""
        n_total = sum(
            sum(row.values()) for row in self.counts.values()
        )
        if n_total == 0:
            return 0.0
        ll = self.mle_log_likelihood()
        # Number of free params = prod(parent cardinalities) * (|support| - 1)
        # We approximate parent cardinalities as len(support) = 2 for BOOLEAN
        n_configs = max(len(self.counts), 1)
        n_free = n_configs * (len(self.support) - 1)
        penalty = 0.5 * n_free * math.log(max(n_total, 1))
        return ll - penalty

    def bic_score_without_parent(self, parent_name: str) -> float:
        """BIC score for the variable as if `parent_name` were removed from Pa."""
        # Marginalize out parent_name from counts
        marginal_counts: dict = {}
        for parent_config, row in self.counts.items():
            reduced = tuple((k, v) for k, v in parent_config if k != parent_name)
            if reduced not in marginal_counts:
                marginal_counts[reduced] = {v: 0 for v in self.support}
            for val, cnt in row.items():
                marginal_counts[reduced][val] = marginal_counts[reduced].get(val, 0) + cnt

        n_total = sum(sum(r.values()) for r in marginal_counts.values())
        if n_total == 0:
            return 0.0

        ll = 0.0
        for reduced, row in marginal_counts.items():
            n_q = sum(row.values())
            if n_q == 0:
                continue
            for v, n_qk in row.items():
                if n_qk > 0:
                    ll += n_qk * math.log(n_qk / n_q)

        n_configs = max(len(marginal_counts), 1)
        n_free = n_configs * (len(self.support) - 1)
        penalty = 0.5 * n_free * math.log(max(n_total, 1))
        return ll - penalty

    def digest(self) -> str:
        """SHA-256 digest of the counts for reproducibility checking."""
        blob = json.dumps(
            {str(k): v for k, v in sorted(self.counts.items(), key=lambda x: str(x[0]))},
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def copy(self) -> CPTData:
        return CPTData(
            variable_name=self.variable_name,
            parents=list(self.parents),
            support=list(self.support),
            counts=copy.deepcopy(self.counts),
            alpha=self.alpha,
        )


# ---------------------------------------------------------------------------
# ParameterStore
# ---------------------------------------------------------------------------

class ParameterStore:
    """
    CPT store mapping (candidate_id, variable_name) → CPTData.

    In-memory by default.  When *db_path* is a real file path the store also
    maintains a ``parameters`` table in the same SQLite database used by
    EvidenceStore / PopulationStore.  Call :meth:`load_from_db` after
    initialising candidates to restore previously learned parameters, and
    :meth:`flush_to_db` at the end of each learning cycle to persist them.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        # {str(candidate_id): {variable_name: CPTData}}
        self._store: dict[str, dict[str, CPTData]] = {}

        # SQLite persistence (None when in-memory / not configured)
        self._conn: sqlite3.Connection | None = None
        if db_path and db_path != ":memory:":
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_PARAMETERS_TABLE)
            for sql in (
                "ALTER TABLE parameters ADD COLUMN edge_signature TEXT",
                "ALTER TABLE parameters ADD COLUMN domain_module_id TEXT",
            ):
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            self._conn.commit()

    # ------------------------------------------------------------------
    def initialize_candidate(
        self,
        candidate_id: UUID,
        variable_name: str,
        parents: list[str],
        support: list[Any],
        alpha: float = 1.0,
    ) -> None:
        cid = str(candidate_id)
        if cid not in self._store:
            self._store[cid] = {}
        self._store[cid][variable_name] = CPTData(
            variable_name=variable_name,
            parents=sorted(parents),
            support=support,
            counts={},
            alpha=alpha,
        )

    # ------------------------------------------------------------------
    def get(self, candidate_id: UUID, variable_name: str) -> CPTData:
        return self._store[str(candidate_id)][variable_name]

    def has(self, candidate_id: UUID, variable_name: str) -> bool:
        cid = str(candidate_id)
        return cid in self._store and variable_name in self._store[cid]

    # ------------------------------------------------------------------
    def get_all_for_candidate(self, candidate_id: UUID) -> dict[str, CPTData]:
        return self._store.get(str(candidate_id), {})

    # ------------------------------------------------------------------
    def update_parents(
        self,
        candidate_id: UUID,
        variable_name: str,
        new_parents: list[str],
    ) -> None:
        """Rebuild CPT for variable with new parent set (resets counts)."""
        cid = str(candidate_id)
        old = self._store[cid][variable_name]
        self._store[cid][variable_name] = CPTData(
            variable_name=variable_name,
            parents=sorted(new_parents),
            support=old.support,
            counts={},
            alpha=old.alpha,
        )

    # ------------------------------------------------------------------
    def clone_candidate(self, src_id: UUID, dst_id: UUID) -> None:
        """Deep-copy all CPTs from src_id to dst_id."""
        src = str(src_id)
        dst = str(dst_id)
        if src not in self._store:
            return
        self._store[dst] = {k: v.copy() for k, v in self._store[src].items()}

    # ------------------------------------------------------------------
    def parameter_hash(self, candidate_id: UUID) -> str:
        """SHA-256 over all CPT digests for a candidate."""
        all_cpts = self.get_all_for_candidate(candidate_id)
        combined = "|".join(
            f"{name}:{cpt.digest()}"
            for name, cpt in sorted(all_cpts.items())
        )
        return hashlib.sha256(combined.encode()).hexdigest()

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    def save_candidate(
        self,
        candidate_id: UUID,
        domain_module_id: str,
        edge_signature: str,
    ) -> None:
        """
        Persist all CPTs for *candidate_id* to the ``parameters`` table.

        *domain_module_id* and *edge_signature* together form the stable
        primary key used for cross-session matching (since candidate_id is a
        session-local UUID).

        No-op when there is no DB connection.
        """
        if self._conn is None:
            return
        cid = str(candidate_id)
        cpts = self._store.get(cid, {})
        if not cpts:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                cid,
                domain_module_id,
                edge_signature,
                vname,
                cpt.alpha,
                _serialize_counts(cpt.counts),
                json.dumps(cpt.parents),
                now,
            )
            for vname, cpt in cpts.items()
        ]
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO parameters
              (candidate_id, domain_module_id, edge_signature,
               variable_name, alpha, counts_json, parent_ids_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def load_from_db(
        self,
        domain_module_id: str,
        sig_to_candidate_id: dict[str, UUID],
    ) -> None:
        """
        Restore persisted CPTs for the given domain into the in-memory store.

        *sig_to_candidate_id* maps each candidate's edge_signature string to
        its current-session UUID.  Rows in the DB are matched by
        (domain_module_id, edge_signature, variable_name); the current UUID is
        used to write back into ``_store``.

        Must be called *after* :meth:`initialize_candidate` so that the
        ``support`` list (which comes from the domain definition) is already
        populated.
        """
        if self._conn is None:
            return
        if not sig_to_candidate_id:
            return
        cur = self._conn.execute(
            """
            SELECT edge_signature, variable_name, alpha, counts_json, parent_ids_json
              FROM parameters
             WHERE domain_module_id = ?
            """,
            (domain_module_id,),
        )
        for row in cur.fetchall():
            edge_sig, vname, alpha, counts_json, parent_ids_json = row
            current_cid = sig_to_candidate_id.get(edge_sig)
            if current_cid is None:
                continue  # no candidate with this structure in the current session
            cid_str = str(current_cid)
            if cid_str not in self._store or vname not in self._store[cid_str]:
                continue  # variable not yet initialised
            existing = self._store[cid_str][vname]
            parents = json.loads(parent_ids_json)
            counts = _deserialize_counts(counts_json)
            self._store[cid_str][vname] = CPTData(
                variable_name=vname,
                parents=parents,
                support=existing.support,  # authoritative from domain definition
                counts=counts,
                alpha=alpha,
            )

    # ------------------------------------------------------------------
    def remove_candidate(self, candidate_id: UUID) -> None:
        self._store.pop(str(candidate_id), None)
