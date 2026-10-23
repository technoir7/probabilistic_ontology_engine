"""
PopulationStore — persisted OntologyPopulation, its candidates and their edges.

CPTs live in ParameterStore. save_population_state / load_population round-trip
a whole population so a restart resumes it (REFACTOR_SPEC 3.3).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ..schemas import (
    CandidateStatus,
    DependencyEdge,
    DependencyKind,
    OntologyCandidate,
    OntologyPopulation,
    Variable,
)
from .database import Database


class PopulationStore:

    def __init__(self, db: Database | str | Path = ":memory:"):
        self._db = db if isinstance(db, Database) else Database(db)
        self._conn = self._db.conn
        self.db_path = self._db.path

    # ------------------------------------------------------------------
    # Population CRUD
    # ------------------------------------------------------------------

    def save_population(self, pop: OntologyPopulation) -> None:
        self._conn.execute(
            """
            INSERT INTO ontology_populations
              (population_id, domain_module_id, max_population_size,
               active_candidate_id, generation, paradigm_shift_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (domain_module_id) DO UPDATE SET
              population_id = excluded.population_id,
              max_population_size = excluded.max_population_size,
              active_candidate_id = excluded.active_candidate_id,
              generation = excluded.generation,
              paradigm_shift_count = excluded.paradigm_shift_count,
              updated_at = excluded.updated_at
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
        self._db.commit()

    def save_population_state(
        self,
        pop: OntologyPopulation,
        state: dict,
        candidates: list[OntologyCandidate],
    ) -> None:
        """
        Persist the population row with *state* (JSON) plus *candidates*' rows
        and edges. Callers pass only candidates that may have changed; the
        state's ordered candidate id list is what load_population reads back.
        """
        self.save_population(pop)
        self._conn.execute(
            "UPDATE ontology_populations SET state=? WHERE domain_module_id=?",
            (json.dumps(state), pop.domain_module_id),
        )
        for cand in candidates:
            self.save_candidate(cand)
            self._save_edges(cand)
        self._db.commit()

    def load_population(
        self, domain_module_id: str, variables: list[Variable]
    ) -> tuple[OntologyPopulation, dict] | None:
        """
        The persisted population and its state, or None if there is none or
        it was written before population persistence (state IS NULL).
        Two queries per population plus one for all edges.
        """
        row = self._conn.execute(
            "SELECT * FROM ontology_populations WHERE domain_module_id=?",
            (domain_module_id,),
        ).fetchone()
        if row is None or row["state"] is None:
            return None
        state = json.loads(row["state"])
        ids = state["candidate_ids"]
        placeholders = ",".join("?" for _ in ids)
        cand_rows = {
            r["candidate_id"]: r
            for r in self._conn.execute(
                f"SELECT * FROM ontology_candidates WHERE candidate_id IN ({placeholders})", ids
            )
        }
        edges: dict[str, list[DependencyEdge]] = {cid: [] for cid in ids}
        for e in self._conn.execute(
            f"SELECT * FROM candidate_edges WHERE candidate_id IN ({placeholders})"
            " ORDER BY candidate_id, ordinal",
            ids,
        ):
            edges[e["candidate_id"]].append(DependencyEdge(
                edge_id=UUID(e["edge_id"]),
                parent_variable_id=UUID(e["parent_variable_id"]),
                child_variable_id=UUID(e["child_variable_id"]),
                dependency_kind=DependencyKind(e["dependency_kind"]),
                existence_prior=e["existence_prior"],
                existence_probability=e["existence_probability"],
                existence_update_count=e["existence_update_count"],
                explore_weight=e["explore_weight"],
                explanatory_label=e["explanatory_label"],
                learnable=bool(e["learnable"]),
                enabled=bool(e["enabled"]),
            ))
        missing = [cid for cid in ids if cid not in cand_rows]
        if missing:
            raise RuntimeError(
                f"population for {domain_module_id} lists candidates with no row: {missing[:3]}"
            )
        candidates = []
        for cid in ids:
            c = cand_rows[cid]
            candidates.append(OntologyCandidate(
                candidate_id=UUID(cid),
                domain_module_id=c["domain_module_id"],
                generation=c["generation"],
                parent_candidate_id=UUID(c["parent_candidate_id"]) if c["parent_candidate_id"] else None,
                variables=variables,
                edges=edges[cid],
                log_score=c["log_score"],
                evidence_count=c["evidence_count"],
                window_log_score=c["window_log_score"],
                window_evidence=c["window_evidence"],
                status=CandidateStatus(c["status"]),
                introduced_at=datetime.fromisoformat(c["introduced_at"]),
                pruned_at=datetime.fromisoformat(c["pruned_at"]) if c["pruned_at"] else None,
                pruning_reason=c["pruning_reason"],
                description=c["description"],
                lineage=json.loads(c["metadata"] or "{}").get("lineage", ""),
            ))
        active_id = row["active_candidate_id"]
        pop = OntologyPopulation(
            population_id=UUID(row["population_id"]),
            domain_module_id=domain_module_id,
            max_population_size=row["max_population_size"],
            candidates=candidates,
            active_candidate_id=UUID(active_id) if active_id else None,
            generation=row["generation"],
            paradigm_shift_count=row["paradigm_shift_count"],
        )
        return pop, state

    def delete_domain(self, domain_module_id: str) -> None:
        """Delete the domain's population, candidates, their scores and edges, and its shift log."""
        ids = [
            r[0] for r in self._conn.execute(
                "SELECT candidate_id FROM ontology_candidates WHERE domain_module_id=?", (domain_module_id,)
            )
        ]
        for cid in ids:
            self._conn.execute("DELETE FROM candidate_scores WHERE candidate_id=?", (cid,))
            self._conn.execute("DELETE FROM candidate_edges WHERE candidate_id=?", (cid,))
        for table in ("ontology_candidates", "paradigm_shifts", "ontology_populations"):
            self._conn.execute(f"DELETE FROM {table} WHERE domain_module_id=?", (domain_module_id,))
        self._db.commit()

    def _save_edges(self, cand: OntologyCandidate) -> None:
        cid = str(cand.candidate_id)
        self._conn.execute("DELETE FROM candidate_edges WHERE candidate_id=?", (cid,))
        self._conn.executemany(
            """
            INSERT INTO candidate_edges
              (edge_id, candidate_id, ordinal, parent_variable_id, child_variable_id,
               dependency_kind, existence_prior, existence_probability,
               existence_update_count, explore_weight, explanatory_label,
               learnable, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(e.edge_id), cid, i, str(e.parent_variable_id), str(e.child_variable_id),
                    e.dependency_kind.value, e.existence_prior, e.existence_probability,
                    e.existence_update_count, e.explore_weight, e.explanatory_label,
                    int(e.learnable), int(e.enabled),
                )
                for i, e in enumerate(cand.edges)
            ],
        )

    # ------------------------------------------------------------------
    # Candidate CRUD
    # ------------------------------------------------------------------

    def save_candidate(self, cand: OntologyCandidate) -> None:
        self._conn.execute(
            """
            INSERT INTO ontology_candidates
              (candidate_id, domain_module_id, generation, parent_candidate_id,
               log_score, evidence_count, window_log_score, window_evidence,
               status, introduced_at, pruned_at, pruning_reason, description, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (candidate_id) DO UPDATE SET
              domain_module_id = excluded.domain_module_id,
              generation = excluded.generation,
              parent_candidate_id = excluded.parent_candidate_id,
              log_score = excluded.log_score,
              evidence_count = excluded.evidence_count,
              window_log_score = excluded.window_log_score,
              window_evidence = excluded.window_evidence,
              status = excluded.status,
              introduced_at = excluded.introduced_at,
              pruned_at = excluded.pruned_at,
              pruning_reason = excluded.pruning_reason,
              description = excluded.description,
              metadata = excluded.metadata
            """,
            (
                str(cand.candidate_id),
                cand.domain_module_id,
                cand.generation,
                str(cand.parent_candidate_id) if cand.parent_candidate_id else None,
                cand.log_score,
                cand.evidence_count,
                cand.window_log_score,
                cand.window_evidence,
                cand.status.value,
                cand.introduced_at.isoformat(),
                cand.pruned_at.isoformat() if cand.pruned_at else None,
                cand.pruning_reason,
                cand.description,
                json.dumps({"lineage": cand.lineage}),
            ),
        )
        self._db.commit()

    def update_score(
        self,
        candidate_id: UUID,
        log_score: float,
        evidence_count: int,
        *,
        window: tuple[float, float] | None = None,
    ) -> None:
        """Cumulative score, and the score window when given (the art package passes none)."""
        if window is None:
            self._conn.execute(
                "UPDATE ontology_candidates SET log_score=?, evidence_count=? WHERE candidate_id=?",
                (log_score, evidence_count, str(candidate_id)),
            )
        else:
            self._conn.execute(
                "UPDATE ontology_candidates SET log_score=?, evidence_count=?,"
                " window_log_score=?, window_evidence=? WHERE candidate_id=?",
                (log_score, evidence_count, window[0], window[1], str(candidate_id)),
            )
        self._db.commit()

    def mark_pruned(self, candidate_id: UUID, reason: str) -> None:
        self._conn.execute(
            """
            UPDATE ontology_candidates
            SET status='PRUNED', pruned_at=?, pruning_reason=?
            WHERE candidate_id=?
            """,
            (datetime.utcnow().isoformat(), reason, str(candidate_id)),
        )
        self._db.commit()

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
        self._db.commit()

    # ------------------------------------------------------------------
    # Paradigm shift events
    # ------------------------------------------------------------------

    def append_shift_event(
        self,
        *,
        domain_module_id: str,
        generation: int,
        prev_dominant_id: UUID,
        prev_dominant_name: str,
        new_dominant_id: UUID,
        new_dominant_name: str,
        evidence_count_at_shift: int,
    ) -> None:
        """Persist one paradigm-shift event (dominant candidate changed)."""
        from uuid import uuid4
        self._conn.execute(
            """
            INSERT INTO paradigm_shifts
              (shift_id, domain_module_id, generation, shift_ts,
               prev_dominant_id, prev_dominant_name,
               new_dominant_id, new_dominant_name,
               evidence_count_at_shift)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                domain_module_id,
                generation,
                datetime.utcnow().isoformat(),
                str(prev_dominant_id),
                prev_dominant_name,
                str(new_dominant_id),
                new_dominant_name,
                evidence_count_at_shift,
            ),
        )
        self._db.commit()

    def count_shift_events(self, domain_module_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM paradigm_shifts WHERE domain_module_id = ?",
            (domain_module_id,),
        ).fetchone()[0]

    def load_shift_events(self, domain_module_id: str, last: int | None = None) -> list[dict]:
        """
        Paradigm-shift events for a domain in chronological order; with *last*,
        only the most recent *last* events (still oldest first).

        Each dict contains:
            shift_id, domain_module_id, generation, shift_ts,
            prev_dominant_id, prev_dominant_name,
            new_dominant_id, new_dominant_name, evidence_count_at_shift
        """
        cur = self._conn.execute(
            """
            SELECT shift_id, domain_module_id, generation, shift_ts,
                   prev_dominant_id, prev_dominant_name,
                   new_dominant_id, new_dominant_name,
                   evidence_count_at_shift
            FROM paradigm_shifts
            WHERE domain_module_id = ?
            ORDER BY shift_ts DESC
            LIMIT ?
            """,
            (domain_module_id, -1 if last is None else last),  # SQLite: LIMIT -1 = no limit
        )
        return [dict(row) for row in reversed(cur.fetchall())]
