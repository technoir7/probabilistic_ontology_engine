"""Request and response models of the HTTP API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

# Validated: the report routes build cache file names from it.
OntologyMode = Literal["apriori", "dynamic"]



class DominantHypothesis(BaseModel):
    name: str
    candidate_id: str
    generations_dominant: int


class PopStatusOut(BaseModel):
    domain: str
    structure_entropy: float
    active_candidates: int
    max_candidates: int
    current_generation: int
    dominant_hypothesis: DominantHypothesis
    paradigm_shifts_this_window: int
    frontier_edge_count: int
    last_evidence_cycle_ago: str
    engine_status: Literal["online", "degraded", "offline"]


class CandidateOut(BaseModel):
    id: str
    name: str
    log_score: float
    evidence_count: int
    generation_introduced: int
    edge_count: int
    status: Literal["dominant", "rising", "falling", "neutral"]
    score_normalized: float


class CandidatesOut(BaseModel):
    domain: str
    generation: int
    candidates: list[CandidateOut]


class GraphNodeOut(BaseModel):
    id: str
    label: str
    probability: Optional[float] = None
    observation: Optional[str] = None
    status: Literal["established", "exploring", "weak", "target"]


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    probability: float
    status: Literal["strong", "explore", "weak"]


class FrontierEdgeOut(BaseModel):
    relation: str
    source: str
    target: str
    probability: float
    note: str
    explore_weight: Optional[float] = None


class InferenceOut(BaseModel):
    candidate_id: str
    target_variable: str
    target_probability: float
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    frontier_edges: list[FrontierEdgeOut]


class QueryBodyIn(BaseModel):
    domain: str
    target_variable: str
    candidate_id: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None
    aggregation: Optional[Literal["weighted_avg", "map", "marginal"]] = None
    ontology_mode: Optional[OntologyMode] = None


class LineageEventOut(BaseModel):
    generation: int
    event_type: Literal["shift", "introduce", "milestone", "current"]
    description: str
    dominant_after: Optional[str] = None


class LineageOut(BaseModel):
    domain: str
    candidate_id: str
    events: list[LineageEventOut]


class ParadigmShiftEventOut(BaseModel):
    shift_id: str
    generation: int
    timestamp: str
    previous_dominant_id: str
    previous_dominant_name: str
    new_dominant_id: str
    new_dominant_name: str
    evidence_count_at_shift: int


class ParadigmShiftsOut(BaseModel):
    domain: str
    domain_module_id: str
    total_shifts: int
    events: list[ParadigmShiftEventOut]


# ── Narrative snapshot response models ────────────────────────────────────────

class NarrativeMetadataOut(BaseModel):
    domain: str
    domain_module_id: str
    timestamp: str
    evidence_count: int
    current_generation: int


class NarrativeRegimeVariableOut(BaseModel):
    name: str
    boolean_state: Optional[bool]
    probability: Optional[float]


class NarrativeEdgeOut(BaseModel):
    source: str
    target: str
    existence_probability: float


class NarrativeDominantHypothesisOut(BaseModel):
    name: str
    candidate_id: str
    edge_count: int
    edges: list[NarrativeEdgeOut]
    generations_dominant: int
    log_score: float


class NarrativeCompetitorOut(BaseModel):
    name: str
    log_score: float
    edge_count: int
    status: str
    score_normalized: float


class NarrativeCompetingCandidatesOut(BaseModel):
    candidates: list[NarrativeCompetitorOut]
    score_gap_to_dominant: Optional[float]


class NarrativeRecentShiftOut(BaseModel):
    timestamp: str
    from_name: str
    to_name: str
    generation: int


class NarrativeOntologyCompetitionOut(BaseModel):
    structure_entropy: float
    entropy_interpretation: str   # "low" | "medium" | "high"
    active_candidates: int
    paradigm_shifts_total: int
    recent_shifts: list[NarrativeRecentShiftOut]


class NarrativeFrontierEdgeOut(BaseModel):
    source: str
    target: str
    probability: float
    relation: str


class NarrativeFrontierOut(BaseModel):
    frontier_edge_count: int
    frontier_edges: list[NarrativeFrontierEdgeOut]


class NarrativeSnapshotOut(BaseModel):
    metadata: NarrativeMetadataOut
    current_regime_state: list[NarrativeRegimeVariableOut]
    dominant_hypothesis: Optional[NarrativeDominantHypothesisOut]
    competing_candidates: NarrativeCompetingCandidatesOut
    ontology_competition: NarrativeOntologyCompetitionOut
    frontier: NarrativeFrontierOut
    interpretation_hints: list[str]


class EvidenceRecordOut(BaseModel):
    id: str
    timestamp: str
    description: str
    impact_delta: float
    strength: Literal["strong", "shift", "weak"]
    variables_updated: Optional[int] = None


class EvidenceOut(BaseModel):
    domain: str
    records: list[EvidenceRecordOut]


class IngestTriggerOut(BaseModel):
    domain: str
    evidence_records_ingested: int
    population_status: PopStatusOut


class IngestReplaceOut(BaseModel):
    domain: str
    records_supplied: int
    records_learned: int


class IngestBackfillOut(BaseModel):
    domain: str
    days_requested: int
    days_successfully_ingested: int


class ArtReportIngestOut(BaseModel):
    domain: str
    input_path: str
    files_scanned: int
    items_found: int
    records_found: int              # one per report document
    records_learned: int
    records_skipped_duplicates: int
    failed: list[str]               # unreadable files and invalid items, with the reason


class ArtRebuildOut(BaseModel):
    """The latest art rebuild since the service started (state "idle" if none)."""
    domain: str
    state: Literal["idle", "running", "done", "failed"]
    months_requested: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    reports_found: Optional[int] = None
    records_learned: Optional[int] = None   # fetched months plus reports
    failed_reports: list[str] = []
    error: Optional[str] = None


class VariableEntropyDebugOut(BaseModel):
    value_counts: dict[str, int]
    observed_count: int
    missing_count: int
    entropy: float


class ObservedPatternOut(BaseModel):
    pattern: dict[str, Any]
    count: int


class PairwiseMutualInformationOut(BaseModel):
    variable_x: str
    variable_y: str
    joint_observed_count: int
    mutual_information: float


class EntropyDebugOut(BaseModel):
    domain: str
    domain_key: str
    domain_module_id: str
    total_evidence_rows: int
    variables: dict[str, VariableEntropyDebugOut]
    unique_observed_patterns: list[ObservedPatternOut]
    pairwise_mutual_information: list[PairwiseMutualInformationOut]


# ── Learning diagnostics response model ───────────────────────────────────────

class LearningPipelineStatusOut(BaseModel):
    """Flags showing which code paths call engine.learn()."""
    scheduler_calls_learn: bool
    backfill_calls_learn: bool
    trigger_calls_learn: bool


class LearningDebugOut(BaseModel):
    domain: str
    domain_module_id: str
    total_evidence_records: int
    active_candidates: int
    dominant_evidence_count: int     # evidence_count of the current dominant
    dominant_log_score: float
    learn_calls_this_session: int    # how many times learn() was called since restart
    last_learn_timestamp: Optional[str]   # ISO timestamp or null
    records_scored_this_session: int
    last_mutation_total_attempts: int
    last_mutation_introduced: int
    current_generation: int
    pipeline_status: LearningPipelineStatusOut


# ── Structure diagnostics response models ─────────────────────────────────────

class CandidateDiagOut(BaseModel):
    candidate_id: str
    description: str
    generation: int
    status: str                                  # "ACTIVE" | "PRUNED" | "ARCHIVED"
    edge_structure: list[tuple[str, str]]        # sorted (parent, child) name pairs
    active_edge_count: int
    total_edge_count: int
    evidence_count: int
    log_score: float
    avg_ll: float
    bic_penalty_raw: float
    bic_score_strict: float
    bic_score_explore: float
    is_dominant: bool


class MutationCycleDiagOut(BaseModel):
    total_attempts: int
    dag_violations: int
    duplicate_rejections: int
    introduced: int


class StructureDiagOut(BaseModel):
    domain: str
    domain_module_id: str
    env_mode: str            # "strict" | "explore" (from POE_STRUCTURE_MODE)
    env_bic_multiplier: float
    total_evidence_records: int
    candidates: list[CandidateDiagOut]
    last_mutation_cycle: MutationCycleDiagOut


class DomainReportOut(BaseModel):
    found: bool = True
    domain: str
    ontology_mode: str
    generated_at: str
    snapshot_hash: str
    report: str
    cached: bool = True
    regenerated: bool = False
    stale: bool = False


class DomainReportNotFound(BaseModel):
    found: bool = False
    domain: str
    ontology_mode: str
