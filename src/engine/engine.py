"""
ProbabilisticOntologyEngine — top-level orchestrator.

Implements the pseudocode from SPEC §17.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

from .schemas import (
    EdgeExistenceThresholdConfig,
    EvidenceRecord,
    InferenceQuery,
    ModelSnapshot,
    OntologyCandidate,
    OntologyPopulation,
)
from .services.edge_existence import EdgeExistenceService
from .services.inference import InferenceService
from .services.learning import LearningService
from .services.population_manager import PopulationManager
from .stores.evidence_store import EvidenceStore
from .stores.parameter_store import ParameterStore
from .stores.population_store import PopulationStore


class ProbabilisticOntologyEngine:
    """
    Domain-agnostic probabilistic ontology engine.

    Usage::

        engine = ProbabilisticOntologyEngine()
        engine.register_domain(domain_module)
        engine.activate_domain(domain_module.module_id())

        engine.ingest_batch(evidence_records)
        engine.learn(batch_size=50)
        result = engine.query(inference_query)
    """

    def __init__(self, db_path: str = ":memory:", random_seed: int = 42) -> None:
        self.random_seed = random_seed

        # Stores — all three share the same SQLite file (or :memory:)
        self.evidence_store = EvidenceStore(db_path)
        self.parameter_store = ParameterStore(db_path)
        self.population_store = PopulationStore(db_path)

        # Services
        self.learning_service = LearningService(self.parameter_store)
        self.edge_existence_service = EdgeExistenceService(self.parameter_store)
        self.inference_service = InferenceService(self.parameter_store)
        self.population_manager = PopulationManager(
            parameter_store=self.parameter_store,
            population_store=self.population_store,
        )

        # Active domain
        self.active_domain: str | None = None

        # Registered domain modules
        self._modules: dict[str, Any] = {}

        # Batch counter per domain
        self._batch_index: dict[str, int] = {}

        # Learning telemetry (in-memory only; reset on restart)
        self._learn_call_count: dict[str, int] = {}       # total learn() calls
        self._learn_last_ts: dict[str, str] = {}          # ISO timestamp of last learn()
        self._learn_records_total: dict[str, int] = {}    # cumulative records scored

    # ------------------------------------------------------------------
    # Domain lifecycle
    # ------------------------------------------------------------------

    def register_domain(self, domain_module: Any) -> None:
        """Register a domain module (must implement the DomainModule interface)."""
        module_id = domain_module.module_id()
        self._modules[module_id] = domain_module

        thresholds = domain_module.existence_thresholds()

        # Build initial candidates
        initial_candidates = domain_module.initial_candidates()
        if initial_candidates:
            migration = self.evidence_store.migrate_variable_ids_by_position(
                module_id,
                initial_candidates[0].variables,
            )
            if migration["migrated_records"]:
                logger.info(
                    "Migrated legacy evidence variable IDs for domain '%s': "
                    "%d records, %d assignments",
                    module_id,
                    migration["migrated_records"],
                    migration["migrated_assignments"],
                )
            if migration["mismatched_records"]:
                logger.debug(
                    "Skipped %d evidence records during variable ID migration for domain '%s'",
                    migration["mismatched_records"],
                    module_id,
                )

        # Initialize CPTs for each candidate (empty counts; support from domain)
        for cand in initial_candidates:
            self.learning_service.initialize_candidate(cand, alpha=1.0)

        # Restore any previously persisted parameters for these candidates.
        # Must run AFTER initialize_candidate so that support lists are in
        # place; load_from_db matches by (domain_module_id, edge_signature)
        # because candidate UUIDs are session-local and differ on each restart.
        sig_to_cid = {
            _candidate_edge_sig(cand): cand.candidate_id
            for cand in initial_candidates
        }
        self.parameter_store.load_from_db(module_id, sig_to_cid)

        # Determine admissible edges from domain schema
        admissible = _derive_admissible_edges(initial_candidates)

        # Initialize population
        self.population_manager.initialize(
            domain_module_id=module_id,
            initial_candidates=initial_candidates,
            max_population_size=10,
            admissible_edges=admissible,
            thresholds=thresholds,
        )

        self._batch_index[module_id] = 0

        # Restore candidate scores from persisted evidence so that a server
        # restart doesn't wipe out evidence_count / log_score.  CPT parameters
        # are already restored above (load_from_db); we use them here to
        # compute log_likelihoods over historical records without re-accumulating
        # counts (which would double-count the sufficient statistics).
        self._restore_candidate_scores(module_id)

    def _restore_candidate_scores(self, domain_module_id: str) -> None:
        """
        Re-compute candidate scores from persisted evidence records.

        Called at the end of :meth:`register_domain` so that a server restart
        does not wipe out ``evidence_count`` and ``log_score``.  CPT parameters
        are already loaded from the database at this point, so the computed
        log-likelihoods correctly reflect the learned distributions.

        Only the score metadata is updated — CPT counts are NOT touched, so
        there is no double-counting of the sufficient statistics.
        """
        records = self.evidence_store.load_all(domain_module_id)
        if not records:
            return  # first startup or in-memory mode; nothing to restore

        pop = self.population_manager.get_population(domain_module_id)
        active = pop.active_candidates()
        if not active:
            return

        logger.info(
            "Restoring candidate scores for domain '%s' from %d stored evidence records",
            domain_module_id,
            len(records),
        )

        for candidate in active:
            log_lik = self.learning_service.compute_log_likelihood(records, candidate)
            candidate.log_score = log_lik
            candidate.evidence_count = len(records)
            self.population_store.update_score(
                candidate.candidate_id, log_lik, len(records)
            )
            logger.debug(
                "Restored scores: domain=%s candidate=%s evidence_count=%d log_score=%.4f",
                domain_module_id,
                str(candidate.candidate_id)[:8],
                candidate.evidence_count,
                candidate.log_score,
            )

        pop.update_dominant()
        dom = pop.dominant()
        logger.info(
            "Score restoration complete for domain '%s': "
            "%d candidates; dominant=%s",
            domain_module_id,
            len(active),
            str(dom.candidate_id)[:8] if dom else "none",
        )

    def activate_domain(self, module_id: str) -> None:
        """Set the active domain for ingestion and learning."""
        if module_id not in self._modules:
            raise ValueError(f"Domain '{module_id}' not registered")
        self.active_domain = module_id

    # ------------------------------------------------------------------
    # Evidence ingestion
    # ------------------------------------------------------------------

    def ingest(self, record: EvidenceRecord) -> UUID:
        """Append a single evidence record to the store."""
        assert self.active_domain, "No active domain"
        self.evidence_store.append(record, self.active_domain)
        return record.evidence_id

    def ingest_batch(self, records: list[EvidenceRecord]) -> int:
        """Append a batch of evidence records."""
        assert self.active_domain, "No active domain"
        self.evidence_store.append_batch(records, self.active_domain)
        return len(records)

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def learn(self, batch: list[EvidenceRecord], domain_module_id: str | None = None) -> ModelSnapshot:
        """
        Run one learning cycle on the given evidence batch.

        Steps:
          1. For each active candidate:
             a. Level 1: update CPT parameters (sufficient statistics)
             b. Level 2: update edge existence probabilities
             c. Compute log-likelihood; update candidate score
             d. Prune edges below threshold
          2. Level 3: prune low-scoring candidates
          3. Introduce variants of top survivors
          4. Return a model snapshot
        """
        domain = domain_module_id or self.active_domain
        assert domain, "No active domain"

        pop = self.population_manager.get_population(domain)
        idx = self._batch_index.get(domain, 0)
        n_records = len(batch)

        logger.debug(
            "learn() entered: domain=%s batch_index=%d batch_size=%d active_candidates=%d",
            domain, idx, n_records, len(pop.active_candidates()),
        )

        for candidate in pop.active_candidates():
            prev_ec = candidate.evidence_count
            prev_ls = candidate.log_score

            # Level 1 — parameter update
            logger.debug(
                "accumulate(): domain=%s candidate=%s",
                domain, str(candidate.candidate_id)[:8],
            )
            self.learning_service.accumulate(batch, candidate)

            # Level 2 — edge existence update
            self.edge_existence_service.update(candidate)
            self.edge_existence_service.prune_below_threshold(candidate, self.parameter_store)

            # Score candidate
            log_lik = self.learning_service.compute_log_likelihood(batch, candidate)
            self.population_manager.update_score(
                domain, candidate.candidate_id, log_lik, idx, batch_size=n_records
            )

            logger.debug(
                "scored: domain=%s candidate=%s "
                "evidence_count %d→%d  log_score %.4f→%.4f  batch_ll=%.4f",
                domain, str(candidate.candidate_id)[:8],
                prev_ec, candidate.evidence_count,
                prev_ls, candidate.log_score,
                log_lik,
            )

        # Level 3 — population management
        pruned = self.population_manager.prune_low_scorers(domain)
        if pruned:
            logger.info(
                "Pruned %d low-scoring candidates in domain '%s'",
                len(pruned), domain,
            )

        logger.debug("introduce_variants(): domain=%s", domain)
        new_variants = self.population_manager.introduce_variants(domain, self.learning_service)
        if new_variants:
            for v in new_variants:
                logger.info(
                    "New variant introduced: domain=%s candidate=%s generation=%d description=%r",
                    domain, str(v.candidate_id)[:8], v.generation, v.description,
                )

        self._batch_index[domain] = idx + 1

        # Update telemetry
        self._learn_call_count[domain] = self._learn_call_count.get(domain, 0) + 1
        self._learn_last_ts[domain] = datetime.now(timezone.utc).isoformat()
        self._learn_records_total[domain] = (
            self._learn_records_total.get(domain, 0) + n_records
        )

        logger.info(
            "learn() complete: domain=%s batch_index=%d records=%d "
            "learn_calls_this_session=%d",
            domain, idx, n_records, self._learn_call_count[domain],
        )

        # End of cycle
        summary = self.population_manager.end_cycle(domain)

        # Persist learned parameters so they survive a restart.
        # save_candidate is a no-op when the engine uses :memory:.
        pop_snapshot = self.population_manager.get_population(domain)
        for candidate in pop_snapshot.candidates:
            self.parameter_store.save_candidate(
                candidate.candidate_id,
                domain,
                _candidate_edge_sig(candidate),
            )

        return self._make_snapshot(domain, batch, summary)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def query(self, inference_query: InferenceQuery) -> dict:
        """Answer an inference query against the current population."""
        domain = inference_query.domain_module_id or self.active_domain
        assert domain, "No active domain"
        pop = self.population_manager.get_population(domain)
        return self.inference_service.query(inference_query, pop)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def _make_snapshot(self, domain: str, batch: list, summary: dict) -> ModelSnapshot:
        pop = self.population_manager.get_population(domain)
        dom = pop.dominant()

        pop_hash = hashlib.sha256(
            json.dumps(summary, sort_keys=True, default=str).encode()
        ).hexdigest()

        param_hash = ""
        if dom:
            param_hash = self.parameter_store.parameter_hash(dom.candidate_id)

        return ModelSnapshot(
            domain_module_id=domain,
            population_state_hash=pop_hash,
            parameter_hash=param_hash,
            random_seed=self.random_seed,
            metrics=summary,
        )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def population_status(self, domain_module_id: str | None = None) -> dict:
        domain = domain_module_id or self.active_domain
        return self.population_manager.summary(domain)

    def get_population(self, domain_module_id: str | None = None) -> OntologyPopulation:
        domain = domain_module_id or self.active_domain
        return self.population_manager.get_population(domain)

    def get_edge_existence(
        self, candidate_id: UUID, parent_name: str, child_name: str
    ) -> float | None:
        """Get existence_probability for a specific edge in a candidate."""
        domain = self.active_domain
        if domain is None:
            return None
        pop = self.population_manager.get_population(domain)
        for c in pop.candidates:
            if c.candidate_id == candidate_id:
                for e in c.edges:
                    pv = c.get_variable_by_id(e.parent_variable_id)
                    cv = c.get_variable_by_id(e.child_variable_id)
                    if pv and cv and pv.name == parent_name and cv.name == child_name:
                        return e.existence_probability
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate_edge_sig(candidate: OntologyCandidate) -> str:
    """
    Return a stable string key for a candidate's edge structure.

    The key is a sorted JSON array of (parent_name, child_name) pairs from
    all active edges.  This is stable across restarts because it is derived
    purely from variable *names* (not UUIDs), making it suitable as a
    cross-session lookup key for the parameters table.
    """
    return json.dumps(
        sorted(candidate.edge_structure_signature()),
        ensure_ascii=False,
    )


def _derive_admissible_edges(
    candidates: list[OntologyCandidate],
) -> set[tuple[str, str]]:
    """
    Derive admissible edge pairs from the union of all edges across all candidates.
    In a full implementation this would come from domain schema TemplateRules.
    For MVP we use all edges seen in initial candidates.
    """
    edges: set[tuple[str, str]] = set()
    var_names: set[str] = set()
    for cand in candidates:
        for v in cand.variables:
            var_names.add(v.name)
        for e in cand.edges:
            pv = cand.get_variable_by_id(e.parent_variable_id)
            cv = cand.get_variable_by_id(e.child_variable_id)
            if pv and cv:
                edges.add((pv.name, cv.name))
    # Add all variable pairs as potentially admissible
    # (in a real system this would be schema-constrained)
    for a in var_names:
        for b in var_names:
            if a != b:
                edges.add((a, b))
    return edges
