"""
ParameterStore — CPT storage per candidate, with optional SQLite persistence.

Each candidate has one CPTData (src/engine/model/cpt.py) per variable.

Persistence schema (one row per candidate × variable):
  parameters(candidate_id TEXT, variable_name TEXT, alpha REAL,
             counts_json TEXT, parent_ids_json TEXT, updated_at TIMESTAMP)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ..model.cpt import CPTData, deserialize_counts
from .database import Database


# ---------------------------------------------------------------------------
# ParameterStore
# ---------------------------------------------------------------------------

class ParameterStore:
    """
    CPT store mapping (candidate_id, variable_name) → CPTData.

    Holds CPTs in memory and mirrors them to the ``parameters`` table of the
    shared Database (an in-memory one for ``":memory:"``). Call
    :meth:`load_from_db` after initialising candidates to restore learned
    parameters, and :meth:`save_candidate` at the end of a learning cycle.
    """

    def __init__(self, db: Database | str = ":memory:") -> None:
        # {str(candidate_id): {variable_name: CPTData}}
        self._store: dict[str, dict[str, CPTData]] = {}
        self._db = db if isinstance(db, Database) else Database(db)
        self._conn = self._db.conn

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

    def save_candidates(self, candidate_ids: list[UUID], domain_module_id: str) -> None:
        """Persist all CPTs of these candidates to ``candidate_parameters`` (one executemany)."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                str(cid), vname, domain_module_id, cpt.alpha,
                cpt.serialized_counts(), json.dumps(cpt.parents), now,
            )
            for cid in candidate_ids
            for vname, cpt in self._store.get(str(cid), {}).items()
        ]
        self._conn.executemany(
            """
            INSERT INTO candidate_parameters
              (candidate_id, variable_name, domain_module_id, alpha,
               counts_json, parent_names_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (candidate_id, variable_name) DO UPDATE SET
              alpha = excluded.alpha,
              counts_json = excluded.counts_json,
              parent_names_json = excluded.parent_names_json,
              updated_at = excluded.updated_at
            """,
            rows,
        )
        self._db.commit()

    def load_candidates(self, candidate_ids: list[UUID]) -> None:
        """
        Restore saved CPTs for these candidates over the initialized ones
        (call initialize_candidate first: support comes from the domain).
        One query.
        """
        ids = [str(cid) for cid in candidate_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        for row in self._conn.execute(
            f"""
            SELECT candidate_id, variable_name, alpha, counts_json, parent_names_json
              FROM candidate_parameters WHERE candidate_id IN ({placeholders})
            """,
            ids,
        ):
            cid, vname = row["candidate_id"], row["variable_name"]
            if cid not in self._store or vname not in self._store[cid]:
                continue  # variable no longer in the domain
            self._store[cid][vname] = CPTData(
                variable_name=vname,
                parents=json.loads(row["parent_names_json"]),
                support=self._store[cid][vname].support,  # authoritative from domain definition
                counts=deserialize_counts(row["counts_json"]),
                alpha=row["alpha"],
            )

    def load_from_db(
        self,
        domain_module_id: str,
        sig_to_candidate_id: dict[str, UUID],
    ) -> None:
        """
        Migration only: restore CPTs from the pre-0002 ``parameters`` table.

        Used once, when a database has no resumable population yet. Those rows
        are keyed by edge signature, which changes whenever an edge is pruned,
        so only seed candidates whose structure never changed are matched.

        *sig_to_candidate_id* maps each candidate's edge_signature string to
        its current-session UUID.  Rows in the DB are matched by
        (domain_module_id, edge_signature, variable_name); the current UUID is
        used to write back into ``_store``.

        Must be called *after* :meth:`initialize_candidate` so that the
        ``support`` list (which comes from the domain definition) is already
        populated.
        """
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
            counts = deserialize_counts(counts_json)
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
