"""Request and response models of the HTTP API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

# Validated: the report routes build cache file names from it.



class DominantHypothesis(BaseModel):
    name: str
    candidate_id: str
    generations_dominant: Optional[int]  # None when the shift log cannot place the last shift (B1)


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
    degree: Optional[float] = None
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
    # The target's most likely value, and its degree from 0 to 1: P(True)
    # for a yes/no, the mean position from low to high for levels (D25).
    target_level: Optional[str]
    target_degree: Optional[float]
    target_distribution: dict[str, float]
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    frontier_edges: list[FrontierEdgeOut]


class QueryBodyIn(BaseModel):
    domain: str
    target_variable: str
    candidate_id: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None
    aggregation: Optional[Literal["weighted_avg", "map", "marginal"]] = None


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
    evidence_date: Optional[str] = None  # date of the evidence that caused it; None if recorded before this was kept
    previous_programme: Optional[str] = None  # research programme of each leader; equal when a variant
    new_programme: Optional[str] = None       # overtook one of its own programme (a revision, not a new worldview)


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
    level: Optional[str]      # the most likely value
    degree: Optional[float]   # 0 to 1: P(True) for a yes/no, mean position for levels (D25)


class NarrativeEdgeOut(BaseModel):
    source: str
    target: str
    existence_probability: float


class NarrativeDominantHypothesisOut(BaseModel):
    name: str
    candidate_id: str
    edge_count: int
    edges: list[NarrativeEdgeOut]
    generations_dominant: Optional[int]  # None when the shift log cannot place the last shift (B1)
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
    evidence_date: Optional[str] = None
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


class NarrativeCaseMechanismOut(BaseModel):
    mechanism: str
    gain_nats: float          # evidence over each case's own past; 3 is strong


class NarrativeCaseForecastOut(BaseModel):
    case: str
    own_past_chance: float    # of the outcome at all, from the case's own past alone
    with_leader_chance: float


class NarrativeCaseSetOut(BaseModel):
    title: str
    outcome: str
    leader: str
    leader_since: Optional[int]
    gain_nats_over_own_past: float
    mechanisms: list[NarrativeCaseMechanismOut]
    belief_changes: list[str]
    forecast_for: Optional[int]
    most_raised: list[NarrativeCaseForecastOut]


class NarrativeTrendOut(BaseModel):
    trend: str
    broad_since: int
    writers_this_year: int
    share_this_year_pct: float        # of every critic writing that year
    share_before_pct: float           # average over the years before
    share_by_year_pct: dict[str, float]   # this year and the years it is set against
    papers: list[str]
    approvals: int
    disapprovals: int
    distinctive_words: list[str]
    what_critics_said: list[str]      # this year's claims, as the reader of the press put them


class NarrativeTrendsOut(BaseModel):
    period: str
    compared_with: str
    note: str
    new: list[NarrativeTrendOut]
    growing: list[NarrativeTrendOut]
    fading: list[NarrativeTrendOut]
    argued_over: list[NarrativeTrendOut]


class NarrativeTrendListOut(BaseModel):
    """One trend list, for its own written report (D30)."""
    domain: str
    list: str
    rule: str                        # what put a trend on this list
    period: str
    compared_with: str
    note: str
    trends: list[NarrativeTrendOut]


class NarrativeSnapshotOut(BaseModel):
    metadata: NarrativeMetadataOut
    current_regime_state: list[NarrativeRegimeVariableOut]
    dominant_hypothesis: Optional[NarrativeDominantHypothesisOut]
    competing_candidates: NarrativeCompetingCandidatesOut
    ontology_competition: NarrativeOntologyCompetitionOut
    frontier: NarrativeFrontierOut
    interpretation_hints: list[str]
    case_mechanisms: list[NarrativeCaseSetOut] = []   # D29: only a domain judged by cases
    trends: Optional[NarrativeTrendsOut] = None       # D30: only a domain with trends


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


class DomainRebuildOut(BaseModel):
    domain: str
    state: Literal["idle", "running", "done", "failed"]
    days_requested: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    records_learned: Optional[int] = None
    targets_missed: list[date] = []  # periods with no record: no data, or fetch still failing after a retry
    error: Optional[str] = None


class IngestBackfillOut(BaseModel):
    domain: str
    days_requested: int
    days_successfully_ingested: int


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
    generated_at: str
    snapshot_hash: str
    report: str
    cached: bool = True
    regenerated: bool = False
    stale: bool = False


class DomainReportNotFound(BaseModel):
    found: bool = False
    domain: str


# ── Cases (D29) ───────────────────────────────────────────────────────────────

class CaseShiftOut(BaseModel):
    year: int                 # the year whose evidence made the change
    frm: list[str]
    to: list[str]


class CaseYearOut(BaseModel):
    year: int
    engine: float             # nats: the log score of the leader chosen before the year
    own_past: float
    cases: int


class CaseMechanismOut(BaseModel):
    features: list[str]
    gain: float               # nats over own past, all scored years


class CaseForecastOut(BaseModel):
    case: str
    label: str
    own_past: list[float]     # chance of none, one, several
    with_leader: list[float]


class CaseSetOut(BaseModel):
    key: str
    title: str
    outcome: str
    pool: list[str]
    leader: list[str]         # empty: own past alone
    shifts: list[CaseShiftOut]
    years: list[CaseYearOut]
    gain: float               # nats over own past, all scored years
    mechanisms: list[CaseMechanismOut]   # every rival set of mechanisms, best first
    forecast_year: Optional[int]   # the state year forecast from; its outcome is the year after
    most_raised: list[CaseForecastOut]


class CasesOut(BaseModel):
    domain: str
    case_sets: list[CaseSetOut]


# ── Trends (D30) ──────────────────────────────────────────────────────────────

class TrendOut(BaseModel):
    key: str
    name: str
    start: int                # first year broad
    words: list[str]
    writers: list[int]        # each year of TrendListsOut.years
    papers: list[str]         # this year
    verdicts: list[int]       # approvals, disapprovals this year
    sample: list[str]         # a few of this year's claims, as the reader put them


class TrendListsOut(BaseModel):
    year: int                 # the year to September shown
    before: int               # years it is set against
    years: list[int]
    all_writers: list[int]    # every writer each year
    lists: dict[str, list[str]]   # new, growing, fading, argued: trend keys in order
    trends: dict[str, TrendOut]


class TrendsOut(BaseModel):
    domain: str
    trends: Optional[TrendListsOut]   # None: the domain has no trends


# ── Success (D31) ─────────────────────────────────────────────────────────────

class SuccessKindOut(BaseModel):
    key: str
    title: str
    outcome: str
    leader: list[str]                 # empty: own past alone
    leader_since: Optional[int]
    gain: float                       # nats over own past, all scored years
    mechanisms: list[tuple[str, float]]
    effects: dict[str, float]         # "feature=level" -> push on the log-odds of any outcome
    dealt: dict[str, list[float]]     # engine gain with that feature dealt at random
    placebo: float                    # engine gain with features from the year after
    placebo_fair: bool                # False: the year-after features count part of the outcome itself
    most_raised: list[tuple[str, float, float]]   # artist, chance from own past, with the leader
    years: list[tuple[int, float]]


class RewardedOut(BaseModel):
    kind: str
    name: str
    approvals: int
    disapprovals: int
    approved: list[str]
    disapproved: list[str]


class SuccessSnapshotOut(BaseModel):
    year: int
    forecast_for: int
    kinds: dict[str, SuccessKindOut]
    rewarded: list[RewardedOut]


class SuccessOut(BaseModel):
    domain: str
    success: Optional[SuccessSnapshotOut]   # None: the domain has none


class NarrativeSuccessMechanismOut(BaseModel):
    mechanisms: str                   # in words
    gain_nats: float


class NarrativeSuccessEffectOut(BaseModel):
    feature: str                      # in words, with its level ("one" or "several")
    push: float                       # change in the log-odds of any success next year: + helps, - hurts


class NarrativeSuccessAddsOut(BaseModel):
    feature: str                      # in words
    nats: float                       # gain lost when this feature alone is dealt at random, mean of the deals


class NarrativeOtherKindOut(BaseModel):
    leading_features: list[str]       # in words; empty: own past alone
    gain_nats_over_own_past: float
    helps: list[str]                  # leading features whose pushes are above 0
    hurts: list[str]


class NarrativeSuccessOut(BaseModel):
    """One kind of success, for its own written report (D31)."""
    domain: str
    kind: str
    title: str
    success_means: str
    forecast_for: int
    leader: str
    leader_since: Optional[int]
    gain_nats_over_own_past: float
    scored_years: int
    verdicts: list[str]               # fixed by rule (narrative._verdicts); the report states them as they are
    best_rival_sets: list[NarrativeSuccessMechanismOut]
    leader_effects: list[NarrativeSuccessEffectOut]
    each_leading_feature_adds: list[NarrativeSuccessAddsOut]
    control_placebo_features_from_the_year_after_gain_nats: float
    control_placebo_is_a_fair_test: bool   # False: next year's features count part of next year's success
    artists_the_leader_favours: list[NarrativeCaseForecastOut]
    other_kinds: dict[str, NarrativeOtherKindOut]   # by title
    critics_rewarded_this_year: list[RewardedOut]
    note: str
