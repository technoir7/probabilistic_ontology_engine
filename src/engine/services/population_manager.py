"""
PopulationManager — Level 3 belief management.  Novel component.

Responsibilities:
  - Maintains OntologyPopulation for each active domain.
  - Scores candidates after each learning cycle.
  - Introduces new candidates as variants of high-scoring survivors.
  - Prunes low-scoring candidates (bottom quartile after min evidence).
  - Enforces max_population_size.
  - Tracks dominant (highest-scoring) candidate.
  - Tracks paradigm_shift_count.
"""
from __future__ import annotations

import math
import random
from uuid import UUID, uuid4


from ..model.doubt import Surprise
from ..model.scoring import add_to_window, candidate_score
from ..model.scoring import dominant as best_candidate
from ..schemas import (
    CandidateStatus,
    DependencyEdge,
    DependencyKind,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
    OntologyPopulation,
)
from ..stores.parameter_store import ParameterStore
from ..stores.population_store import PopulationStore
from ..model.clock import naive_utc_now


# Pruning starts once any candidate has scored this many evidence records.
_MIN_RECORDS_FOR_PRUNING = 3
# Jeffreys' "decisive": a Bayes factor above 100 for the leader over a rival.
_DECISIVE_LOG_BAYES_FACTOR = math.log(100)


def _breeding_order(ranked: list[OntologyCandidate], turn: int) -> list[OntologyCandidate]:
    """Each programme's best, best programme first and rotated by `turn`,
    then everyone else by score."""
    champions: dict[str, OntologyCandidate] = {}
    for c in ranked:
        champions.setdefault(c.lineage, c)
    order = list(champions.values())
    if order:
        k = turn % len(order)
        order = order[k:] + order[:k]
    return order + [c for c in ranked if c not in order]


def _refuted(candidate: OntologyCandidate, leader: OntologyCandidate) -> bool:
    """Is the evidence for the leader over this candidate decisive? Log Bayes
    factor approximated as each one's window total less its BIC penalty."""
    gap = leader.window_evidence * candidate_score(leader) - candidate.window_evidence * candidate_score(candidate)
    return gap > _DECISIVE_LOG_BAYES_FACTOR


class PopulationManager:

    def __init__(
        self,
        parameter_store: ParameterStore,
        population_store: PopulationStore,
        thresholds: EdgeExistenceThresholdConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.ps = parameter_store
        self.pop_store = population_store
        self.thresholds = thresholds or EdgeExistenceThresholdConfig()
        self.rng = rng or random.Random(42)

        # In-memory populations: {domain_module_id: OntologyPopulation}
        self._populations: dict[str, OntologyPopulation] = {}
        # Admissible edge pairs per domain: {domain_id: set of (parent_name, child_name)}
        self._admissible_edges: dict[str, set[tuple[str, str]]] = {}
        # Mutation-cycle diagnostics from the most recent introduce_variants() call
        # {domain_module_id: {total_attempts, dag_violations, duplicate_rejections, introduced}}
        self._last_mutation_stats: dict[str, dict[str, int]] = {}
        # Whose turn it is to breed first, per domain (D16).
        self._breed_turn: dict[str, int] = {}
        # The leader's usual surprise, per domain (D17).
        self._surprise: dict[str, Surprise] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(
        self,
        domain_module_id: str,
        initial_candidates: list[OntologyCandidate],
        max_population_size: int = 10,
        admissible_edges: set[tuple[str, str]] | None = None,
        thresholds: EdgeExistenceThresholdConfig | None = None,
    ) -> OntologyPopulation:
        if thresholds:
            self.thresholds = thresholds

        for c in initial_candidates:
            if not c.lineage:
                c.lineage = c.description.split(":")[0].strip() or str(c.candidate_id)
        pop = OntologyPopulation(
            domain_module_id=domain_module_id,
            max_population_size=max_population_size,
            candidates=list(initial_candidates),
        )
        pop.update_dominant()
        self._populations[domain_module_id] = pop
        self._admissible_edges[domain_module_id] = admissible_edges or set()
        self.pop_store.save_population(pop)
        for c in initial_candidates:
            self.pop_store.save_candidate(c)
        return pop

    def adopt(
        self,
        domain_module_id: str,
        population: OntologyPopulation,
        admissible_edges: set[tuple[str, str]],
        state: dict,
    ) -> None:
        """Install a population restored from storage, with the rng where it left off."""
        self._populations[domain_module_id] = population
        self._admissible_edges[domain_module_id] = admissible_edges
        self._last_mutation_stats[domain_module_id] = dict(state.get("mutation_stats", {}))
        self._breed_turn[domain_module_id] = int(state.get("breed_turn", 0))
        self._surprise[domain_module_id] = Surprise.from_state(state.get("surprise"))
        version, internal, gauss_next = state["rng_state"]
        self.rng.setstate((version, tuple(internal), gauss_next))

    def forget(self, domain_module_id: str) -> None:
        """Drop the domain's in-memory population (for a reset; storage is separate)."""
        self._populations.pop(domain_module_id, None)
        self._admissible_edges.pop(domain_module_id, None)
        self._last_mutation_stats.pop(domain_module_id, None)
        self._breed_turn.pop(domain_module_id, None)
        self._surprise.pop(domain_module_id, None)

    def export_state(self, domain_module_id: str) -> dict:
        """What adopt() needs besides the population itself (JSON-serializable)."""
        version, internal, gauss_next = self.rng.getstate()
        return {
            "rng_state": [version, list(internal), gauss_next],
            "breed_turn": self._breed_turn.get(domain_module_id, 0),
            "surprise": self.surprise(domain_module_id).state(),
            "mutation_stats": self.last_mutation_stats(domain_module_id),
        }

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_population(self, domain_module_id: str) -> OntologyPopulation:
        return self._populations[domain_module_id]

    def surprise(self, domain_module_id: str) -> Surprise:
        return self._surprise.setdefault(domain_module_id, Surprise())

    def doubt(self, domain_module_id: str, factor: float) -> None:
        """Count every active candidate's score window for `factor` (D17)."""
        for c in self._populations[domain_module_id].active_candidates():
            c.window_log_score *= factor
            c.window_evidence *= factor

    def dominant(self, domain_module_id: str) -> OntologyCandidate | None:
        """Return highest average-score active candidate (fair to late-arrivals)."""
        return best_candidate(self._populations[domain_module_id].active_candidates())

    def dominant_matches_structure(
        self, domain_module_id: str, target_signature: frozenset[tuple[str, str]]
    ) -> bool:
        dom = self.dominant(domain_module_id)
        if dom is None:
            return False
        return dom.edge_structure_signature() == target_signature

    def summary(self, domain_module_id: str) -> dict:
        return self._populations[domain_module_id].summary()

    # ------------------------------------------------------------------
    # Score update
    # ------------------------------------------------------------------

    def update_score(
        self,
        domain_module_id: str,
        candidate_id: UUID,
        log_likelihood: float,
        batch_index: int = 0,
        batch_size: int = 1,
    ) -> None:
        pop = self._populations[domain_module_id]
        for c in pop.candidates:
            if c.candidate_id == candidate_id:
                c.log_score += log_likelihood
                c.evidence_count += batch_size   # count actual records
                c.window_log_score, c.window_evidence = add_to_window(
                    c.window_log_score, c.window_evidence, log_likelihood, batch_size
                )
                self.pop_store.update_score(
                    c.candidate_id, c.log_score, c.evidence_count,
                    window=(c.window_log_score, c.window_evidence),
                )
                self.pop_store.append_score_record(c.candidate_id, log_likelihood, batch_index)
                break

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune_low_scorers(self, domain_module_id: str) -> list[OntologyCandidate]:
        """
        Mark bottom-quartile candidates as PRUNED if they have accumulated
        enough evidence.  Returns list of pruned candidates.
        """
        pop = self._populations[domain_module_id]
        active = pop.active_candidates()
        if len(active) < 2:
            return []

        # Only prune if enough evidence processed (at least 3 batches of any candidate)
        if not any(c.evidence_count >= _MIN_RECORDS_FOR_PRUNING for c in active):
            return []

        # Rank by average score (fair across candidates with different evidence counts)
        ranked = sorted(active, key=candidate_score)
        n_prune = max(1, len(active) // 4)

        # Each research programme keeps its best candidate until the evidence
        # against it is decisive, so a rival worldview is not lost for ranking
        # low while the evidence is thin, and a shift between them stays
        # possible (D15).
        leader = ranked[-1]
        champions = {}
        for c in reversed(ranked):
            champions.setdefault(c.lineage, c)
        spared = {c.candidate_id for c in champions.values() if not _refuted(c, leader)}

        pruned = []
        for c in ranked[:n_prune]:
            # Don't prune the dominant candidate or a programme's best
            if c.candidate_id == pop.active_candidate_id or c.candidate_id in spared:
                continue
            c.status = CandidateStatus.PRUNED
            c.pruned_at = naive_utc_now()
            c.pruning_reason = "bottom_quartile_log_score"
            self.pop_store.mark_pruned(c.candidate_id, c.pruning_reason)
            pruned.append(c)

        return pruned

    # ------------------------------------------------------------------
    # Variant introduction
    # ------------------------------------------------------------------

    def introduce_variants(self, domain_module_id: str) -> list[OntologyCandidate]:
        """
        Introduce new candidates as variants of the top survivors.
        Variants are: add one edge OR remove one edge.
        All variants must be valid DAGs.
        Population is kept bounded at max_population_size.
        """
        pop = self._populations[domain_module_id]
        active = pop.active_candidates()

        slots = pop.max_population_size - len(active)
        if slots <= 0:
            return []

        # Best first by the same score that decides dominance and pruning; raw
        # log_score mostly measures how much evidence a candidate has seen.
        # Each research programme's best goes first in turn, so a rival gets
        # to revise itself and is not judged unrevised (D16); with one
        # programme this is plain best-first.
        survivors = _breeding_order(sorted(active, key=candidate_score, reverse=True),
                                    self._breed_turn.get(domain_module_id, 0))
        self._breed_turn[domain_module_id] = self._breed_turn.get(domain_module_id, 0) + 1
        admissible = self._admissible_edges.get(domain_module_id, set())

        new_candidates: list[OntologyCandidate] = []
        attempts = 0
        max_attempts = slots * 10

        # Mutation-cycle diagnostics
        _dag_violations = 0
        _duplicate_rejections = 0

        while len(new_candidates) < slots and attempts < max_attempts:
            parent_cand = survivors[attempts % len(survivors)]
            attempts += 1
            variant = self._make_variant(domain_module_id, parent_cand, admissible)
            if variant is None:
                continue
            if not variant.is_dag():
                _dag_violations += 1
                continue
            # Avoid duplicates
            sig = variant.edge_structure_signature()
            existing_sigs = {c.edge_structure_signature() for c in active + new_candidates}
            if sig in existing_sigs:
                _duplicate_rejections += 1
                continue

            pop.candidates.append(variant)
            pop.generation += 1
            self.pop_store.save_candidate(variant)

            # Initialize CPTs for the new candidate (clone from parent)
            self.ps.clone_candidate(parent_cand.candidate_id, variant.candidate_id)

            # The clone has the parent's parent sets; reset the CPT of every
            # variable whose parents the mutation changed.
            for var in variant.variables:
                parent_names = sorted(pv.name for pv in variant.get_parents(var.variable_id))
                old_parents = (
                    self.ps.get(variant.candidate_id, var.name).parents
                    if self.ps.has(variant.candidate_id, var.name)
                    else []
                )
                if set(parent_names) != set(old_parents):
                    self.ps.update_parents(variant.candidate_id, var.name, parent_names)

            new_candidates.append(variant)

        # Record mutation diagnostics for this cycle
        self._last_mutation_stats[domain_module_id] = {
            "total_attempts": attempts,
            "dag_violations": _dag_violations,
            "duplicate_rejections": _duplicate_rejections,
            "introduced": len(new_candidates),
        }

        return new_candidates

    def _make_variant(
        self,
        domain_module_id: str,
        parent: OntologyCandidate,
        admissible: set[tuple[str, str]],
    ) -> OntologyCandidate | None:
        """Create one structural variant of `parent` by add/remove one edge."""
        strategy = self.rng.choice(["add", "remove"])
        active_edges = parent.get_active_edges()
        edge_sigs = {
            (
                parent.get_variable_by_id(e.parent_variable_id).name,
                parent.get_variable_by_id(e.child_variable_id).name,
            )
            for e in active_edges
            if parent.get_variable_by_id(e.parent_variable_id)
            and parent.get_variable_by_id(e.child_variable_id)
        }

        if strategy == "remove" and not active_edges:
            strategy = "add"
        if strategy == "add" and admissible:
            # Pick a random admissible edge not currently present.
            # Sort to ensure deterministic order regardless of PYTHONHASHSEED.
            candidates_to_add = sorted(admissible - edge_sigs)
            if not candidates_to_add:
                strategy = "remove"

        # Clone the parent candidate
        variant_id = uuid4()
        variant_edges = [
            DependencyEdge(
                edge_id=uuid4(),
                parent_variable_id=e.parent_variable_id,
                child_variable_id=e.child_variable_id,
                dependency_kind=e.dependency_kind,
                existence_prior=e.existence_prior,
                existence_probability=e.existence_probability,
                existence_update_count=e.existence_update_count,
                explore_weight=e.explore_weight,
                explanatory_label=e.explanatory_label,
                learnable=e.learnable,
                enabled=e.enabled,
            )
            for e in parent.edges
        ]

        if strategy == "add" and admissible:
            candidates_to_add = sorted(admissible - edge_sigs)
            if not candidates_to_add:
                return None
            pname, cname = self.rng.choice(candidates_to_add)
            pvar = parent.get_variable_by_name(pname)
            cvar = parent.get_variable_by_name(cname)
            if pvar is None or cvar is None:
                return None
            new_edge = DependencyEdge(
                edge_id=uuid4(),
                parent_variable_id=pvar.variable_id,
                child_variable_id=cvar.variable_id,
                dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
                existence_prior=0.5,
                existence_probability=0.5,
                learnable=True,
                enabled=True,
            )
            variant_edges.append(new_edge)
            description = f"variant_add_{pname}->{cname}"
        elif strategy == "remove" and active_edges:
            # Pick a random active edge to remove
            edge_to_remove = self.rng.choice(active_edges)
            variant_edges = [
                e for e in variant_edges if e.edge_id != edge_to_remove.edge_id
            ]
            pvar = parent.get_variable_by_id(edge_to_remove.parent_variable_id)
            cvar = parent.get_variable_by_id(edge_to_remove.child_variable_id)
            pname = pvar.name if pvar else "?"
            cname = cvar.name if cvar else "?"
            description = f"variant_remove_{pname}->{cname}"
        else:
            return None

        # Warm-start: inherit parent's score history so cross-candidate
        # comparison is fair.  Future batches will differentiate the variant.
        variant = OntologyCandidate(
            candidate_id=variant_id,
            domain_module_id=domain_module_id,
            generation=parent.generation + 1,
            parent_candidate_id=parent.candidate_id,
            variables=parent.variables,  # shared; immutable at engine level
            edges=variant_edges,
            log_score=parent.log_score,
            evidence_count=parent.evidence_count,
            window_log_score=parent.window_log_score,
            window_evidence=parent.window_evidence,
            status=CandidateStatus.ACTIVE,
            description=description,
            lineage=parent.lineage,
        )
        return variant

    # ------------------------------------------------------------------
    # Diagnostic accessors
    # ------------------------------------------------------------------

    def last_mutation_stats(self, domain_module_id: str) -> dict[str, int]:
        """
        Return mutation-cycle diagnostics from the most recent
        ``introduce_variants()`` call for *domain_module_id*.

        Returns an empty dict if no cycle has been completed yet.

        Keys
        ----
        total_attempts
            Total times the variant-generation loop ran (some attempts produce
            no variant when the admissible edge set is exhausted or empty).
        dag_violations
            Variants rejected because adding the edge created a cycle.
        duplicate_rejections
            Variants rejected because an identical edge signature already
            exists in the active population.
        introduced
            Variants successfully added to the population.
        """
        return dict(self._last_mutation_stats.get(domain_module_id, {}))

    # ------------------------------------------------------------------
    # Post-cycle bookkeeping
    # ------------------------------------------------------------------

    def end_cycle(self, domain_module_id: str) -> dict:
        """
        Call at end of each learning cycle:
          1. Detect dominant-candidate change and persist a ParadigmShiftEvent.
          2. Update dominant candidate pointer in the population.
          3. Save population metadata.
        Returns summary dict.
        """
        pop = self._populations[domain_module_id]

        # Snapshot the previous dominant BEFORE update_dominant() changes
        # active_candidate_id.  We need both the ID and the display name.
        prev_id = pop.active_candidate_id
        prev_cand = (
            next(
                (c for c in pop.candidates if c.candidate_id == prev_id),
                None,
            )
            if prev_id is not None
            else None
        )

        shifted = pop.update_dominant()

        # Write a durable shift event whenever the dominant changes.
        # We do NOT write on the very first cycle (prev_cand is None) because
        # there was no previous dominant — that is initialisation, not a shift.
        if shifted and prev_cand is not None:
            new_dom = pop.dominant()
            if new_dom is not None:
                # Inside the learning cycle's transaction: a failed write fails
                # the cycle instead of silently losing the event.
                self.pop_store.append_shift_event(
                    domain_module_id=domain_module_id,
                    generation=pop.generation,
                    prev_dominant_id=prev_cand.candidate_id,
                    prev_dominant_name=(
                        prev_cand.description
                        or str(prev_cand.candidate_id)[:8]
                    ),
                    new_dominant_id=new_dom.candidate_id,
                    new_dominant_name=(
                        new_dom.description
                        or str(new_dom.candidate_id)[:8]
                    ),
                    evidence_count_at_shift=new_dom.evidence_count,
                )

        self.pop_store.save_population(pop)
        return pop.summary()
