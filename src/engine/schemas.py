"""
Core Pydantic v2 schemas for the Probabilistic Ontology Engine.
All schema objects are defined here per the SPEC.
"""
from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

import networkx as nx
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DomainType(str, Enum):
    BOOLEAN = "BOOLEAN"
    CATEGORICAL = "CATEGORICAL"
    ORDINAL = "ORDINAL"
    CONTINUOUS = "CONTINUOUS"
    COUNT = "COUNT"


class DependencyKind(str, Enum):
    DIRECTED_CONDITIONAL = "DIRECTED_CONDITIONAL"
    FACTOR_LINK = "FACTOR_LINK"
    AGGREGATION_LINK = "AGGREGATION_LINK"


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PRUNED = "PRUNED"
    ARCHIVED = "ARCHIVED"


class MissingnessType(str, Enum):
    OBSERVED = "OBSERVED"
    MISSING = "MISSING"
    IMPUTED = "IMPUTED"
    REDACTED = "REDACTED"
    SOFT_OBSERVED = "SOFT_OBSERVED"   # probabilistic/soft observation


class SourceType(str, Enum):
    STREAM = "STREAM"
    BATCH = "BATCH"
    MANUAL = "MANUAL"
    SIMULATION = "SIMULATION"
    API = "API"
    FILE = "FILE"


class RelationSemantics(str, Enum):
    CAUSAL = "CAUSAL"
    CORRELATIONAL = "CORRELATIONAL"
    TAXONOMIC = "TAXONOMIC"
    TEMPORAL = "TEMPORAL"
    COMPOSITIONAL = "COMPOSITIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"


# ---------------------------------------------------------------------------
# Ontology primitives
# ---------------------------------------------------------------------------

class Variable(BaseModel):
    variable_id: UUID = Field(default_factory=uuid4)
    name: str
    domain_type: DomainType
    support: list[Any]          # e.g. [True, False] for BOOLEAN
    time_indexed: bool = False
    hidden: bool = False


class DependencyEdge(BaseModel):
    edge_id: UUID = Field(default_factory=uuid4)
    parent_variable_id: UUID
    child_variable_id: UUID
    dependency_kind: DependencyKind = DependencyKind.DIRECTED_CONDITIONAL
    existence_prior: float = 0.5
    existence_probability: float = 0.5
    existence_update_count: int = 0
    explore_weight: float = 1.0
    explanatory_label: str = ""
    learnable: bool = True
    enabled: bool = True        # False once pruned below threshold


class ObservedAssignment(BaseModel):
    variable_id: UUID
    observed_value: Any
    missingness: MissingnessType = MissingnessType.OBSERVED
    confidence: float = 1.0
    probabilities: Optional[dict] = None
    """
    Optional soft-evidence distribution over the variable's support.

    Keys are variable support values (e.g. ``True``/``False`` for BOOLEAN),
    values are probabilities that must sum to approximately 1.0.

    * When *missingness* is ``OBSERVED``, this field is ``None``; the hard
      value in *observed_value* carries the full weight.
    * When *missingness* is ``SOFT_OBSERVED``, this dict provides the
      fractional weights used by the learning service.  *observed_value*
      is kept as the MAP (highest-probability) value for backward
      compatibility with callers that only read the hard field.

    Example (Boolean)::

        probabilities={True: 0.64, False: 0.36}
    """

    @model_validator(mode="after")
    def _validate_probabilities(self) -> "ObservedAssignment":
        if self.probabilities is not None:
            total = sum(float(v) for v in self.probabilities.values())
            if abs(total - 1.0) > 0.02:
                raise ValueError(
                    f"ObservedAssignment.probabilities must sum to 1.0 ± 0.02, "
                    f"got {total:.4f} for variable {self.variable_id}"
                )
        return self


class EvidenceRecord(BaseModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    observed_assignments: list[ObservedAssignment]
    source_type: SourceType = SourceType.SIMULATION
    source_ref: str = ""
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# ParadigmShiftEvent — persisted record of a dominant-candidate change
# ---------------------------------------------------------------------------

class ParadigmShiftEvent(BaseModel):
    """
    Immutable record written each time the dominant candidate changes in a domain.

    Written by PopulationManager.end_cycle() whenever update_dominant() returns
    True (i.e. the winning candidate changed since the previous cycle).
    """
    shift_id: UUID = Field(default_factory=uuid4)
    domain_module_id: str
    generation: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    previous_dominant_id: UUID
    previous_dominant_name: str = ""
    new_dominant_id: UUID
    new_dominant_name: str = ""
    evidence_count_at_shift: int = 0


# ---------------------------------------------------------------------------
# OntologyCandidate — Level 3 primitive
# ---------------------------------------------------------------------------

class OntologyCandidate(BaseModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    domain_module_id: str
    generation: int = 0
    parent_candidate_id: Optional[UUID] = None

    variables: list[Variable]
    edges: list[DependencyEdge]

    log_score: float = 0.0
    evidence_count: int = 0
    status: CandidateStatus = CandidateStatus.ACTIVE
    introduced_at: datetime = Field(default_factory=datetime.utcnow)
    pruned_at: Optional[datetime] = None
    pruning_reason: Optional[str] = None
    description: str = ""

    # ---- helpers ----

    def get_variable_by_name(self, name: str) -> Optional[Variable]:
        for v in self.variables:
            if v.name == name:
                return v
        return None

    def get_variable_by_id(self, vid: UUID) -> Optional[Variable]:
        for v in self.variables:
            if v.variable_id == vid:
                return v
        return None

    def get_active_edges(self) -> list[DependencyEdge]:
        return [e for e in self.edges if e.enabled]

    def get_parents(self, variable_id: UUID) -> list[Variable]:
        result = []
        for e in self.get_active_edges():
            if e.child_variable_id == variable_id:
                v = self.get_variable_by_id(e.parent_variable_id)
                if v is not None:
                    result.append(v)
        return result

    def get_children(self, variable_id: UUID) -> list[Variable]:
        result = []
        for e in self.get_active_edges():
            if e.parent_variable_id == variable_id:
                v = self.get_variable_by_id(e.child_variable_id)
                if v is not None:
                    result.append(v)
        return result

    def is_dag(self) -> bool:
        """Check whether active edges form a DAG (no cycles)."""
        g = nx.DiGraph()
        for v in self.variables:
            g.add_node(str(v.variable_id))
        for e in self.get_active_edges():
            g.add_edge(str(e.parent_variable_id), str(e.child_variable_id))
        return nx.is_directed_acyclic_graph(g)

    def topological_order(self) -> list[Variable]:
        """Return variables in topological order (parents before children)."""
        g = nx.DiGraph()
        vid_to_var = {str(v.variable_id): v for v in self.variables}
        for v in self.variables:
            g.add_node(str(v.variable_id))
        for e in self.get_active_edges():
            g.add_edge(str(e.parent_variable_id), str(e.child_variable_id))
        return [vid_to_var[vid] for vid in nx.topological_sort(g)]

    def edge_structure_signature(self) -> frozenset[tuple[str, str]]:
        """Return frozenset of (parent_name, child_name) for all active edges."""
        sig = set()
        for e in self.get_active_edges():
            pv = self.get_variable_by_id(e.parent_variable_id)
            cv = self.get_variable_by_id(e.child_variable_id)
            if pv and cv:
                sig.add((pv.name, cv.name))
        return frozenset(sig)


# ---------------------------------------------------------------------------
# OntologyPopulation — Level 3 container
# ---------------------------------------------------------------------------

class OntologyPopulation(BaseModel):
    population_id: UUID = Field(default_factory=uuid4)
    domain_module_id: str
    max_population_size: int = 10
    candidates: list[OntologyCandidate] = Field(default_factory=list)
    active_candidate_id: Optional[UUID] = None
    generation: int = 0
    paradigm_shift_count: int = 0

    def active_candidates(self) -> list[OntologyCandidate]:
        return [c for c in self.candidates if c.status == CandidateStatus.ACTIVE]

    def _avg_score(self, c: OntologyCandidate, multiplier: float = 1.0) -> float:
        """
        BIC-corrected average log-likelihood; counts ALL edges (incl. disabled).

        Parameters
        ----------
        multiplier : float, default 1.0
            Scale factor applied to the BIC penalty term.  The production
            system always uses the default (1.0).  The diagnostic endpoint
            passes 0.25 for the ``bic_score_explore`` side-by-side column.
        """
        n = c.evidence_count
        if n == 0:
            return float("-inf")
        avg_ll = c.log_score / n
        k = 0
        for v in c.variables:
            n_parents = sum(1 for e in c.edges if e.child_variable_id == v.variable_id)
            k += 2 ** n_parents
        bic_penalty = 0.5 * k * math.log(max(n, 2)) / n * multiplier
        return avg_ll - bic_penalty

    def dominant(self) -> Optional[OntologyCandidate]:
        active = self.active_candidates()
        if not active:
            return None
        return max(active, key=self._avg_score)

    def update_dominant(self) -> bool:
        """Update active_candidate_id; return True if it changed (paradigm shift)."""
        dom = self.dominant()
        if dom is None:
            return False
        prev = self.active_candidate_id
        self.active_candidate_id = dom.candidate_id
        if prev is not None and prev != dom.candidate_id:
            self.paradigm_shift_count += 1
            return True
        return False

    def score_weights(self) -> list[float]:
        active = self.active_candidates()
        if not active:
            return []
        # Use average scores for weighting
        avg_scores = [self._avg_score(c) for c in active]
        max_score = max(avg_scores)
        weights = [math.exp(min(s - max_score, 0)) for s in avg_scores]
        total = sum(weights) or 1.0
        return [w / total for w in weights]

    def summary(self) -> dict:
        active = self.active_candidates()
        dom = self.dominant()
        # Structure entropy: H over score weights
        weights = self.score_weights()
        entropy = -sum(w * math.log(w + 1e-12) for w in weights if w > 0)
        return {
            "domain_module": self.domain_module_id,
            "generation": self.generation,
            "active_candidates": len(active),
            "dominant_candidate": str(dom.candidate_id) if dom else None,
            "dominant_score": dom.log_score if dom else None,
            "structure_entropy": entropy,
            "paradigm_shift_count": self.paradigm_shift_count,
        }


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

class EdgeExistenceThresholdConfig(BaseModel):
    prune_below: float = 0.05
    accept_above: float = 0.90
    explore_band: tuple[float, float] = (0.3, 0.7)


# ---------------------------------------------------------------------------
# Inference primitives
# ---------------------------------------------------------------------------

class QueryType(str, Enum):
    MARGINAL = "MARGINAL"
    MAP = "MAP"
    CONDITIONAL = "CONDITIONAL"
    INTERVENTION = "INTERVENTION"
    EXPLANATION = "EXPLANATION"
    FORECAST = "FORECAST"


class PopulationAggregation(str, Enum):
    ACTIVE_ONLY = "ACTIVE_ONLY"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    TOP_K = "TOP_K"


class InferenceQuery(BaseModel):
    query_id: UUID = Field(default_factory=uuid4)
    domain_module_id: str
    target_variables: list[str]                  # variable names
    conditioned_on: list[ObservedAssignment] = Field(default_factory=list)
    query_type: QueryType = QueryType.MARGINAL
    population_aggregation: PopulationAggregation = PopulationAggregation.ACTIVE_ONLY
    explain: bool = False


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class ModelSnapshot(BaseModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    engine_version: str = "0.1.0"
    domain_module_id: str
    population_state_hash: str = ""
    parameter_hash: str = ""
    evidence_window_start: Optional[datetime] = None
    evidence_window_end: Optional[datetime] = None
    random_seed: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metrics: dict = Field(default_factory=dict)
