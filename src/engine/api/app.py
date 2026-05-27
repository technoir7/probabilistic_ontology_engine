"""FastAPI application and Railway runtime startup."""
from __future__ import annotations

import asyncio
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ...domains.ai_regime_v1.domain import AIRegimeV1
from ...domains.ai_regime_v1.ingestion.edgar_client import EDGARClient as AIEdgarClient
from ...domains.ai_regime_v1.ingestion.fred_client import FREDClient as AIFredClient
from ...domains.ai_regime_v1.ingestion.pipeline import AIRegimePipeline
from ...domains.ai_regime_v1.ingestion.yfinance_client import AIYFinanceClient
from ...domains.ai_regime_v1.scheduler import AIRegimeScheduler
from ...domains.macro_regime_v1.domain import MacroRegimeV1
from ...domains.macro_regime_v1.ingestion.fred_client import FREDClient
from ...domains.macro_regime_v1.ingestion.pipeline import MacroRegimePipeline
from ...domains.macro_regime_v1.scheduler import MacroRegimeScheduler
from ...domains.natural_gas_v1.domain import NaturalGasV1
from ...domains.natural_gas_v1.ingestion.eia_client import EIAClient
from ...domains.natural_gas_v1.ingestion.noaa_client import NOAAClient
from ...domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline
from ...domains.natural_gas_v1.scheduler import IngestionScheduler as NaturalGasScheduler
from ...domains.sovereign_debt_v1.domain import SovereignDebtV1
from ...domains.sovereign_debt_v1.ingestion.fred_client import FREDClient as SDFredClient
from ...domains.sovereign_debt_v1.ingestion.pipeline import SovereignDebtPipeline
from ...domains.sovereign_debt_v1.scheduler import SovereignDebtScheduler
from ...domains.credit_cycle_v1.domain import CreditCycleV1
from ...domains.credit_cycle_v1.ingestion.fred_client import FREDClient as CCFredClient
from ...domains.credit_cycle_v1.ingestion.pipeline import CreditCyclePipeline
from ...domains.credit_cycle_v1.scheduler import CreditCycleScheduler
from ...domains.energy_regime_v1.domain import EnergyRegimeV1
from ...domains.energy_regime_v1.ingestion.fred_client import FREDClient as ERFredClient
from ...domains.energy_regime_v1.ingestion.yfinance_client import EnergyYFinanceClient
from ...domains.energy_regime_v1.ingestion.pipeline import EnergyRegimePipeline
from ...domains.energy_regime_v1.scheduler import EnergyRegimeScheduler
from ...domains.labor_market_v1.domain import LaborMarketV1
from ...domains.labor_market_v1.ingestion.fred_client import FREDClient as LMFredClient
from ...domains.labor_market_v1.ingestion.pipeline import LaborMarketPipeline
from ...domains.labor_market_v1.scheduler import LaborMarketScheduler
from ...domains.agriculture_weekly import (
    is_agriculture_domain,
    is_duplicate_recent_state,
    latest_complete_week_ending,
    latest_week_ending_on_or_before,
    weekly_backfill_dates,
)
from ..engine import ProbabilisticOntologyEngine
from ..schemas import (
    EvidenceRecord,
    InferenceQuery,
    OntologyCandidate,
    PopulationAggregation,
    QueryType,
)
from ..config import get_structure_mode_config
from ..services.evidence_diagnostics import build_entropy_diagnostics
from ..services.evidence_geometry import build_evidence_geometry_diagnostics
from ..services.structure_diagnostics import build_structure_diagnostics

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ("EIA_API_KEY",)

# Short name → (domain_module_id, display_name)
_DOMAIN_MAP: dict[str, tuple[str, str]] = {
    "ng": ("natural-gas-v1",   "Natural Gas"),
    "mr": ("macro-regime-v1",  "Macro Regime"),
    "ai": ("ai-regime-v1",     "AI Regime"),
    "sd": ("sovereign-debt-v1", "Sovereign Debt"),
    "cc": ("credit-cycle-v1",  "Credit Cycle"),
    "er": ("energy-regime-v1", "Energy Regime"),
    "lm": ("labor-market-v1",  "Labor Market"),
}


# ── Response models ───────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_domain(
    short_name: str,
    state: Any,
) -> tuple[ProbabilisticOntologyEngine, str, str]:
    """Return (engine, domain_module_id, display_name) or raise HTTP 404/503."""
    key = short_name.lower()
    if key not in _DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{short_name}'")
    domain_id, display_name = _DOMAIN_MAP[key]
    engines: dict[str, ProbabilisticOntologyEngine] = getattr(state, "engines", {})
    if key not in engines:
        raise HTTPException(status_code=503, detail=f"Domain '{key}' engine not initialised")
    return engines[key], domain_id, display_name


def _find_variable_fuzzy(cand: OntologyCandidate, raw_name: str):
    """
    Case/separator-insensitive lookup; suffix matching handles the frontend
    hardcoding 'price_up' for all domains (matches 'CornPriceUp', 'SoyPriceUp', etc.).
    """
    normalized = raw_name.lower().replace("_", "").replace("-", "").replace(" ", "")
    # Exact normalised match
    for v in cand.variables:
        if v.name.lower().replace("_", "").replace("-", "") == normalized:
            return v
    # Suffix match
    for v in cand.variables:
        if v.name.lower().replace("_", "").replace("-", "").endswith(normalized):
            return v
    return None


def _time_ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - ts).total_seconds()
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff / 60)}m ago"
        if diff < 86400:
            return f"{int(diff / 3600)}h ago"
        return f"{int(diff / 86400)}d ago"
    except Exception:
        return "unknown"


def _normalize_scores(
    candidates: list[OntologyCandidate],
    avg_fn: Callable[[OntologyCandidate], float],
) -> dict[UUID, float]:
    """Map candidate_id → score in [0.05, 0.95]."""
    scored = [(c.candidate_id, avg_fn(c)) for c in candidates]
    finite_vals = [s for _, s in scored if math.isfinite(s)]
    if not finite_vals or len(set(finite_vals)) == 1:
        # Rank-based when all equal or all -inf
        ranked = sorted(candidates, key=lambda c: avg_fn(c))
        n = len(ranked)
        return {
            c.candidate_id: 0.05 + 0.90 * (i / max(n - 1, 1))
            for i, c in enumerate(ranked)
        }
    min_s, max_s = min(finite_vals), max(finite_vals)
    result: dict[UUID, float] = {}
    for cid, s in scored:
        if not math.isfinite(s):
            result[cid] = 0.05
        else:
            result[cid] = 0.05 + 0.90 * (s - min_s) / (max_s - min_s)
    return result


def _edge_status_label(
    prob: float, explore_lo: float, explore_hi: float
) -> Literal["strong", "explore", "weak"]:
    if prob > explore_hi:
        return "strong"
    if prob >= explore_lo:
        return "explore"
    return "weak"


def _node_status_label(
    var_name: str,
    target_var_name: str,
    cand: OntologyCandidate,
    explore_lo: float,
    explore_hi: float,
) -> Literal["established", "exploring", "weak", "target"]:
    if var_name == target_var_name:
        return "target"
    var = cand.get_variable_by_name(var_name)
    if var is None:
        return "weak"
    max_ep = max(
        (
            e.existence_probability
            for e in cand.get_active_edges()
            if e.parent_variable_id == var.variable_id
            or e.child_variable_id == var.variable_id
        ),
        default=0.0,
    )
    if max_ep > explore_hi:
        return "established"
    if max_ep >= explore_lo:
        return "exploring"
    return "weak"


def _build_engine(domain_module: Any, db_path: Path) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=str(db_path), random_seed=42)
    engine.register_domain(domain_module)
    engine.activate_domain(domain_module.module_id())
    return engine


def _build_population_status(
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    display_name: str,
) -> PopStatusOut:
    pop = engine.get_population(domain_id)
    summary = pop.summary()
    dom = pop.dominant()

    thresholds = engine._modules[domain_id].existence_thresholds()
    explore_lo, explore_hi = thresholds.explore_band
    frontier_count = 0
    if dom:
        for edge in dom.get_active_edges():
            if explore_lo <= edge.existence_probability <= explore_hi:
                frontier_count += 1

    last_ts = engine.evidence_store.latest_timestamp(domain_id)

    dom_name = (dom.description or "Hypothesis A") if dom else "none"
    dom_cid = str(dom.candidate_id) if dom else ""
    gens_dominant = max(0, pop.generation - dom.generation) if dom else 0

    return PopStatusOut(
        domain=display_name,
        structure_entropy=summary["structure_entropy"],
        active_candidates=summary["active_candidates"],
        max_candidates=pop.max_population_size,
        current_generation=pop.generation,
        dominant_hypothesis=DominantHypothesis(
            name=dom_name,
            candidate_id=dom_cid,
            generations_dominant=gens_dominant,
        ),
        paradigm_shifts_this_window=pop.paradigm_shift_count,
        frontier_edge_count=frontier_count,
        last_evidence_cycle_ago=_time_ago(last_ts),
        engine_status="online",
    )


def _resolve_query_candidate(
    pop: Any,
    raw_candidate_id: str | None,
) -> OntologyCandidate:
    active = pop.active_candidates()
    if not active:
        raise HTTPException(status_code=503, detail="No active candidates")

    if not raw_candidate_id:
        cand = pop.dominant()
        if cand is None:
            raise HTTPException(status_code=503, detail="No active candidates")
        return cand

    raw = raw_candidate_id.strip()
    for cand in active:
        label = getattr(cand, "label", None)
        if str(cand.candidate_id) == raw or label == raw:
            return cand

    try:
        target_uuid = UUID(raw)
    except ValueError:
        cand = pop.dominant()
        return cand or active[0]

    for cand in active:
        if cand.candidate_id == target_uuid:
            return cand

    raise HTTPException(status_code=404, detail=f"Candidate '{raw_candidate_id}' not found")


def _ingest_lock(state: Any, domain_key: str) -> asyncio.Lock:
    locks: dict[str, asyncio.Lock] = getattr(state, "ingest_locks", {})
    if domain_key not in locks:
        locks[domain_key] = asyncio.Lock()
        state.ingest_locks = locks
    return locks[domain_key]


def _require_domain_env(domain_key: str) -> None:
    if domain_key == "ng":
        _require_env(("EIA_API_KEY",))
    if domain_key in ("mr", "ai", "sd", "cc", "er", "lm"):
        _require_env(("FRED_API_KEY",))


async def _fetch_evidence_record(domain_key: str, target_date: date) -> EvidenceRecord:
    _require_domain_env(domain_key)

    if domain_key == "ng":
        noaa = NOAAClient()
        eia = EIAClient(api_key=os.environ["EIA_API_KEY"])
        async with noaa, eia:
            return await NaturalGasPipeline(noaa, eia).fetch_evidence(target_date)

    if domain_key == "mr":
        fred = FREDClient(api_key=os.environ["FRED_API_KEY"])
        async with fred:
            return await MacroRegimePipeline(fred).fetch_evidence(target_date)

    if domain_key == "ai":
        fred = AIFredClient(api_key=os.environ["FRED_API_KEY"])
        yf_client = AIYFinanceClient()
        edgar = AIEdgarClient()
        async with fred, edgar, yf_client:
            return await AIRegimePipeline(yf_client, fred, edgar).fetch_evidence(target_date)

    if domain_key == "sd":
        fred = SDFredClient(api_key=os.environ["FRED_API_KEY"])
        async with fred:
            return await SovereignDebtPipeline(fred).fetch_evidence(target_date)

    if domain_key == "cc":
        fred = CCFredClient(api_key=os.environ["FRED_API_KEY"])
        async with fred:
            return await CreditCyclePipeline(fred).fetch_evidence(target_date)

    if domain_key == "er":
        fred = ERFredClient(api_key=os.environ["FRED_API_KEY"])
        yf_client = EnergyYFinanceClient()
        async with fred, yf_client:
            return await EnergyRegimePipeline(fred, yf_client).fetch_evidence(target_date)

    if domain_key == "lm":
        fred = LMFredClient(api_key=os.environ["FRED_API_KEY"])
        async with fred:
            return await LaborMarketPipeline(fred).fetch_evidence(target_date)

    raise ValueError(f"Unknown domain '{domain_key}'")


async def _ingest_domain_evidence(
    *,
    domain_key: str,
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    target_date: date | None = None,
) -> int:
    if target_date is None:
        if is_agriculture_domain(domain_id):
            target_date = latest_complete_week_ending(datetime.now(timezone.utc).date())
        else:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    elif is_agriculture_domain(domain_id):
        target_date = latest_week_ending_on_or_before(target_date)

    record = await _fetch_evidence_record(domain_key, target_date)
    if is_agriculture_domain(domain_id):
        recent = engine.evidence_store.load_recent(domain_id, limit=1)
        if is_duplicate_recent_state(record, recent):
            logger.info(
                "Skipping duplicate %s state for week ending %s",
                domain_id,
                target_date,
            )
            return 0
    before = engine.evidence_store.count(domain_id)
    engine.ingest(record)
    after = engine.evidence_store.count(domain_id)
    ingested = after - before
    if ingested > 0:
        engine.learn([record], domain_id)
    return ingested


async def _backfill_if_empty(
    *,
    domain_key: str,
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    display_name: str,
    backfill_days: int,
    lock: asyncio.Lock,
) -> int:
    if backfill_days <= 0:
        return 0

    today = datetime.now(timezone.utc).date()
    successes = 0
    async with lock:
        existing = engine.evidence_store.count(domain_id)
        if existing > 0:
            logger.info(
                "Skipping %s startup backfill; evidence_count=%d",
                display_name,
                existing,
            )
            return 0

        logger.info(
            "Running %d-day %s startup backfill; evidence_count=0",
            backfill_days,
            display_name,
        )
        if is_agriculture_domain(domain_id):
            targets = weekly_backfill_dates(backfill_days, today)
        else:
            targets = [today - timedelta(days=delta) for delta in range(backfill_days, 0, -1)]
        for target in targets:
            try:
                successes += await _ingest_domain_evidence(
                    domain_key=domain_key,
                    engine=engine,
                    domain_id=domain_id,
                    target_date=target,
                )
            except Exception as exc:
                logger.error(
                    "%s startup backfill failed for %s: %s",
                    display_name,
                    target,
                    exc,
                    exc_info=True,
                )
            await asyncio.sleep(1.0)

    logger.info("%s startup backfill complete: %d days ingested", display_name, successes)
    return successes


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_env()
    _configure_logging()

    data_dir = _data_dir()
    backfill_days = _env_int("EVIDENCE_BACKFILL_DAYS", 30)
    scheduler_enabled = _env_bool("EVIDENCE_SCHEDULER_ENABLED", True)

    # Always build shared engines so API routes work regardless of scheduler state
    ng_engine = _build_engine(NaturalGasV1(), data_dir / "natural_gas.db")
    mr_engine = _build_engine(MacroRegimeV1(), data_dir / "macro_regime.db")
    ai_engine = _build_engine(AIRegimeV1(), data_dir / "ai_regime.db")
    sd_engine = _build_engine(SovereignDebtV1(), data_dir / "sovereign_debt.db")
    cc_engine = _build_engine(CreditCycleV1(), data_dir / "credit_cycle.db")
    er_engine = _build_engine(EnergyRegimeV1(), data_dir / "energy_regime.db")
    lm_engine = _build_engine(LaborMarketV1(), data_dir / "labor_market.db")

    app.state.engines: dict[str, ProbabilisticOntologyEngine] = {
        "ng": ng_engine,
        "mr": mr_engine,
        "ai": ai_engine,
        "sd": sd_engine,
        "cc": cc_engine,
        "er": er_engine,
        "lm": lm_engine,
    }
    app.state.scheduler_tasks: list[asyncio.Task] = []
    app.state.scheduler_enabled = scheduler_enabled
    app.state.ingest_locks: dict[str, asyncio.Lock] = {
        "ng": asyncio.Lock(),
        "mr": asyncio.Lock(),
        "ai": asyncio.Lock(),
        "sd": asyncio.Lock(),
        "cc": asyncio.Lock(),
        "er": asyncio.Lock(),
        "lm": asyncio.Lock(),
    }

    if scheduler_enabled:
        _require_env(REQUIRED_ENV_VARS)
        tasks = [
            asyncio.create_task(
                _run_natural_gas_scheduler(
                    engine=ng_engine,
                    api_key=os.environ["EIA_API_KEY"],
                    run_hour_utc=_env_int("NATURAL_GAS_RUN_HOUR_UTC", 7),
                    backfill_days=backfill_days,
                    lock=app.state.ingest_locks["ng"],
                ),
                name="natural-gas-evidence-scheduler",
            ),
        ]
        # FRED-dependent schedulers are optional (FRED_API_KEY may not be set)
        fred_api_key = os.environ.get("FRED_API_KEY", "")
        if fred_api_key:
            backfill_weeks = _env_int("MACRO_REGIME_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_macro_regime_scheduler(
                    engine=mr_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("MACRO_REGIME_RUN_HOUR_UTC", 9),
                    backfill_weeks=backfill_weeks,
                    lock=app.state.ingest_locks["mr"],
                ),
                name="macro-regime-evidence-scheduler",
            ))
            ai_backfill_weeks = _env_int("AI_REGIME_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_ai_regime_scheduler(
                    engine=ai_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("AI_REGIME_RUN_HOUR_UTC", 9),
                    backfill_weeks=ai_backfill_weeks,
                    lock=app.state.ingest_locks["ai"],
                ),
                name="ai-regime-evidence-scheduler",
            ))
            sd_backfill_weeks = _env_int("SOVEREIGN_DEBT_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_sovereign_debt_scheduler(
                    engine=sd_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("SOVEREIGN_DEBT_RUN_HOUR_UTC", 9),
                    backfill_weeks=sd_backfill_weeks,
                    lock=app.state.ingest_locks["sd"],
                ),
                name="sovereign-debt-evidence-scheduler",
            ))
            cc_backfill_weeks = _env_int("CREDIT_CYCLE_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_credit_cycle_scheduler(
                    engine=cc_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("CREDIT_CYCLE_RUN_HOUR_UTC", 9),
                    backfill_weeks=cc_backfill_weeks,
                    lock=app.state.ingest_locks["cc"],
                ),
                name="credit-cycle-evidence-scheduler",
            ))
            er_backfill_weeks = _env_int("ENERGY_REGIME_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_energy_regime_scheduler(
                    engine=er_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("ENERGY_REGIME_RUN_HOUR_UTC", 9),
                    backfill_weeks=er_backfill_weeks,
                    lock=app.state.ingest_locks["er"],
                ),
                name="energy-regime-evidence-scheduler",
            ))
            lm_backfill_weeks = _env_int("LABOR_MARKET_BACKFILL_WEEKS", max(backfill_days // 7, 8))
            tasks.append(asyncio.create_task(
                _run_labor_market_scheduler(
                    engine=lm_engine,
                    fred_api_key=fred_api_key,
                    run_hour_utc=_env_int("LABOR_MARKET_RUN_HOUR_UTC", 9),
                    backfill_weeks=lm_backfill_weeks,
                    lock=app.state.ingest_locks["lm"],
                ),
                name="labor-market-evidence-scheduler",
            ))
        else:
            logger.info(
                "FRED_API_KEY not set — FRED-based domain schedulers disabled; "
                "engines initialised but no data will be fetched automatically."
            )
        for task in tasks:
            task.add_done_callback(_log_scheduler_exit)
        app.state.scheduler_tasks = tasks

    try:
        yield
    finally:
        for task in app.state.scheduler_tasks:
            task.cancel()
        if app.state.scheduler_tasks:
            await asyncio.gather(*app.state.scheduler_tasks, return_exceptions=True)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Probabilistic Ontology Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Tighten to Vercel deploy URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Existing routes ───────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime")
async def runtime_status() -> dict[str, Any]:
    tasks = getattr(app.state, "scheduler_tasks", [])
    return {
        "scheduler_enabled": getattr(app.state, "scheduler_enabled", False),
        "schedulers": [
            {
                "name": task.get_name(),
                "running": not task.done(),
                "done": task.done(),
                "cancelled": task.cancelled(),
            }
            for task in tasks
        ],
    }


# ── v1 API routes ─────────────────────────────────────────────────────────────

@app.get("/v1/population/status", response_model=PopStatusOut)
async def population_status(domain: str = Query("ng")) -> PopStatusOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    return _build_population_status(engine, domain_id, display_name)


@app.get("/v1/debug/entropy", response_model=EntropyDebugOut)
async def debug_entropy(domain: str = Query("ng")) -> EntropyDebugOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)
    pop = engine.get_population(domain_id)
    candidates = pop.candidates
    variables = candidates[0].variables if candidates else []
    diagnostics = build_entropy_diagnostics(
        records=engine.evidence_store.load_all(domain_id),
        variables=variables,
    )

    return EntropyDebugOut(
        domain=display_name,
        domain_key=domain_key,
        domain_module_id=domain_id,
        **diagnostics,
    )


@app.get("/v1/debug/evidence-geometry")
async def debug_evidence_geometry(domain: str = Query("ng")) -> dict[str, Any]:
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)
    pop = engine.get_population(domain_id)
    candidates = pop.candidates
    variables = candidates[0].variables if candidates else []
    diagnostics = build_evidence_geometry_diagnostics(
        records=engine.evidence_store.load_all(domain_id),
        variables=variables,
    )

    return {
        "domain": display_name,
        "domain_key": domain_key,
        "domain_module_id": domain_id,
        **diagnostics,
    }


@app.get("/v1/debug/learning", response_model=LearningDebugOut)
async def debug_learning(domain: str = Query("ng")) -> LearningDebugOut:
    """
    Learning-pipeline diagnostics.

    Returns:
    - Evidence record count vs candidate scoring counts
    - How many times ``engine.learn()`` has been called in the current session
    - Last learn timestamp
    - Mutation cycle stats
    - Pipeline status flags (which code paths call learn)

    Useful for diagnosing the "evidence accumulates but candidates never
    score / evolve" failure mode that occurs when the scheduler calls
    ``engine.ingest()`` without ``engine.learn()``.
    """
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)

    pop = engine.get_population(domain_id)
    dom = pop.dominant()
    active = pop.active_candidates()
    mutation_stats = engine.population_manager.last_mutation_stats(domain_id)

    return LearningDebugOut(
        domain=display_name,
        domain_module_id=domain_id,
        total_evidence_records=engine.evidence_store.count(domain_id),
        active_candidates=len(active),
        dominant_evidence_count=dom.evidence_count if dom else 0,
        dominant_log_score=dom.log_score if dom else 0.0,
        learn_calls_this_session=engine._learn_call_count.get(domain_id, 0),
        last_learn_timestamp=engine._learn_last_ts.get(domain_id),
        records_scored_this_session=engine._learn_records_total.get(domain_id, 0),
        last_mutation_total_attempts=mutation_stats.get("total_attempts", 0),
        last_mutation_introduced=mutation_stats.get("introduced", 0),
        current_generation=pop.generation,
        pipeline_status=LearningPipelineStatusOut(
            # All three scheduler run_once() methods now call engine.learn()
            scheduler_calls_learn=True,
            # _backfill_if_empty() uses _ingest_domain_evidence() which calls learn()
            backfill_calls_learn=True,
            # /v1/ingest/trigger uses _ingest_domain_evidence() which calls learn()
            trigger_calls_learn=True,
        ),
    )


@app.get("/v1/debug/structure", response_model=StructureDiagOut)
async def debug_structure(domain: str = Query("ng")) -> StructureDiagOut:
    """
    Per-candidate structure-learning diagnostics.

    Returns BIC scores under both strict (multiplier=1.0) and explore
    (multiplier=0.25) regimes so operators can distinguish genuine graph
    sparsity from over-regularisation.  Also reports mutation-cycle stats
    (attempts, DAG violations, duplicate rejections, introductions) from the
    most recent ``introduce_variants()`` call.

    The ``env_mode`` and ``env_bic_multiplier`` fields reflect the current
    value of the ``POE_STRUCTURE_MODE`` environment variable.  Setting it to
    ``explore`` does **not** change live population management — it only
    controls which multiplier is shown in ``env_bic_multiplier``.
    """
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)

    pop = engine.get_population(domain_id)
    mutation_stats = engine.population_manager.last_mutation_stats(domain_id)
    total_evidence = engine.evidence_store.count(domain_id)

    try:
        cfg = get_structure_mode_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    diags = build_structure_diagnostics(
        pop=pop,
        mutation_stats=mutation_stats,
        total_evidence_records=total_evidence,
        env_mode=cfg.mode,
        env_bic_multiplier=cfg.bic_penalty_multiplier,
    )

    return StructureDiagOut(
        domain=display_name,
        domain_module_id=diags.domain_module_id,
        env_mode=diags.env_mode,
        env_bic_multiplier=diags.env_bic_multiplier,
        total_evidence_records=diags.total_evidence_records,
        candidates=[
            CandidateDiagOut(
                candidate_id=cd.candidate_id,
                description=cd.description,
                generation=cd.generation,
                status=cd.status,
                edge_structure=cd.edge_structure,
                active_edge_count=cd.active_edge_count,
                total_edge_count=cd.total_edge_count,
                evidence_count=cd.evidence_count,
                log_score=cd.log_score,
                avg_ll=cd.avg_ll,
                bic_penalty_raw=cd.bic_penalty_raw,
                bic_score_strict=cd.bic_score_strict,
                bic_score_explore=cd.bic_score_explore,
                is_dominant=cd.is_dominant,
            )
            for cd in diags.candidates
        ],
        last_mutation_cycle=MutationCycleDiagOut(
            total_attempts=diags.last_mutation_cycle.total_attempts,
            dag_violations=diags.last_mutation_cycle.dag_violations,
            duplicate_rejections=diags.last_mutation_cycle.duplicate_rejections,
            introduced=diags.last_mutation_cycle.introduced,
        ),
    )


@app.post("/v1/ingest/trigger", response_model=IngestTriggerOut)
async def ingest_trigger(domain: str = Query("ng")) -> IngestTriggerOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)
    lock = _ingest_lock(app.state, domain_key)

    async with lock:
        try:
            ingested = await _ingest_domain_evidence(
                domain_key=domain_key,
                engine=engine,
                domain_id=domain_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "Manual ingestion trigger failed for %s: %s",
                display_name,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Ingestion failed for domain '{domain_key}'",
            ) from exc

    return IngestTriggerOut(
        domain=display_name,
        evidence_records_ingested=ingested,
        population_status=_build_population_status(engine, domain_id, display_name),
    )


@app.post("/v1/ingest/backfill", response_model=IngestBackfillOut)
async def ingest_backfill(
    domain: str = Query("ng"),
    days: int = Query(90, ge=1),
) -> IngestBackfillOut:
    domain_key = domain.lower()
    engine, domain_id, display_name = _resolve_domain(domain_key, app.state)
    lock = _ingest_lock(app.state, domain_key)

    today = datetime.now(timezone.utc).date()
    successes = 0
    if is_agriculture_domain(domain_id):
        targets = weekly_backfill_dates(days, today)
    else:
        targets = [today - timedelta(days=delta) for delta in range(days, 0, -1)]
    async with lock:
        for target in targets:
            try:
                successes += await _ingest_domain_evidence(
                    domain_key=domain_key,
                    engine=engine,
                    domain_id=domain_id,
                    target_date=target,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                logger.error(
                    "Manual %s backfill failed for %s: %s",
                    display_name,
                    target,
                    exc,
                    exc_info=True,
                )

    return IngestBackfillOut(
        domain=display_name,
        days_requested=days,
        days_successfully_ingested=successes,
    )


@app.get("/v1/population/candidates", response_model=CandidatesOut)
async def population_candidates(domain: str = Query("ng")) -> CandidatesOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    pop = engine.get_population(domain_id)
    active = pop.active_candidates()
    dom = pop.dominant()
    dom_id = dom.candidate_id if dom else None

    avg_fn = pop._avg_score
    score_map = _normalize_scores(active, avg_fn)

    # Sort best-first
    sorted_cands = sorted(active, key=avg_fn, reverse=True)
    n = len(sorted_cands)

    out: list[CandidateOut] = []
    for i, c in enumerate(sorted_cands):
        if c.candidate_id == dom_id:
            status: Literal["dominant", "rising", "falling", "neutral"] = "dominant"
        elif i < max(1, n // 3) and c.evidence_count > 0:
            status = "rising"
        elif i >= max(1, 2 * n // 3) and c.evidence_count > 0:
            status = "falling"
        else:
            status = "neutral"

        out.append(CandidateOut(
            id=str(c.candidate_id),
            name=c.description or f"Candidate {str(c.candidate_id)[:8]}",
            log_score=c.log_score,
            evidence_count=c.evidence_count,
            generation_introduced=c.generation,
            edge_count=len(c.get_active_edges()),
            status=status,
            score_normalized=score_map.get(c.candidate_id, 0.5),
        ))

    return CandidatesOut(
        domain=display_name,
        generation=pop.generation,
        candidates=out,
    )


@app.post("/v1/inference/query", response_model=InferenceOut)
async def inference_query(body: QueryBodyIn) -> InferenceOut:
    engine, domain_id, display_name = _resolve_domain(body.domain, app.state)
    pop = engine.get_population(domain_id)

    cand = _resolve_query_candidate(pop, body.candidate_id)

    # Fuzzy-resolve target variable
    target_var = _find_variable_fuzzy(cand, body.target_variable)
    if target_var is None:
        raise HTTPException(
            status_code=422,
            detail=f"Variable '{body.target_variable}' not found in domain '{body.domain}'",
        )

    # Run inference (single candidate ACTIVE_ONLY)
    iq = InferenceQuery(
        domain_module_id=domain_id,
        target_variables=[target_var.name],
        query_type=QueryType.MARGINAL,
        population_aggregation=PopulationAggregation.ACTIVE_ONLY,
    )
    raw = engine.inference_service.query(iq, pop)
    posteriors = raw.get("posteriors", {})
    dist = posteriors.get(target_var.name, {})
    # P(True) for BOOLEAN variables; first value otherwise
    target_prob = dist.get("True", dist.get("true", next(iter(dist.values()), 0.5)))

    # Build graph
    thresholds = engine._modules[domain_id].existence_thresholds()
    explore_lo, explore_hi = thresholds.explore_band

    nodes: list[GraphNodeOut] = []
    for v in cand.variables:
        node_status = _node_status_label(v.name, target_var.name, cand, explore_lo, explore_hi)
        prob: float | None = None
        if v.name == target_var.name:
            prob = target_prob
        nodes.append(GraphNodeOut(
            id=v.name,
            label=v.name,
            probability=prob,
            status=node_status,
        ))

    edges: list[GraphEdgeOut] = []
    frontier: list[FrontierEdgeOut] = []
    for e in cand.get_active_edges():
        pv = cand.get_variable_by_id(e.parent_variable_id)
        cv = cand.get_variable_by_id(e.child_variable_id)
        if not pv or not cv:
            continue
        ep = e.existence_probability
        estatus = _edge_status_label(ep, explore_lo, explore_hi)
        edges.append(GraphEdgeOut(
            source=pv.name,
            target=cv.name,
            probability=ep,
            status=estatus,
        ))
        if explore_lo <= ep <= explore_hi:
            frontier.append(FrontierEdgeOut(
                relation=e.explanatory_label or f"{pv.name}→{cv.name}",
                source=pv.name,
                target=cv.name,
                probability=ep,
                note=f"existence_probability={ep:.3f} in explore band [{explore_lo}, {explore_hi}]",
                explore_weight=e.explore_weight,
            ))

    return InferenceOut(
        candidate_id=str(cand.candidate_id),
        target_variable=target_var.name,
        target_probability=target_prob,
        nodes=nodes,
        edges=edges,
        frontier_edges=frontier,
    )


@app.get("/v1/population/lineage/{candidate_id}", response_model=LineageOut)
async def population_lineage(candidate_id: str, domain: str = Query("ng")) -> LineageOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    pop = engine.get_population(domain_id)

    # Find the requested candidate (active or pruned) in the specified domain first.
    all_cands = {str(c.candidate_id): c for c in pop.candidates}

    # Cross-domain fallback: if the candidate isn't in the specified domain's
    # population, search all other loaded engines.  This handles the common
    # case where the caller omits ?domain=<key> or passes the wrong one
    # (e.g. calling lineage with an MR UUID while domain defaults to "ng").
    if candidate_id not in all_cands:
        engines_map: dict[str, ProbabilisticOntologyEngine] = getattr(
            app.state, "engines", {}
        )
        found = False
        for dk, alt_engine in engines_map.items():
            if dk == domain.lower():
                continue  # already searched this one
            alt_dm_id, alt_display = _DOMAIN_MAP[dk]
            alt_pop = alt_engine.get_population(alt_dm_id)
            alt_cands = {str(c.candidate_id): c for c in alt_pop.candidates}
            if candidate_id in alt_cands:
                pop = alt_pop
                all_cands = alt_cands
                domain_id = alt_dm_id
                display_name = alt_display
                found = True
                break
        if not found:
            raise HTTPException(
                status_code=404, detail=f"Candidate '{candidate_id}' not found"
            )

    target_cand = all_cands[candidate_id]

    # Walk the parent chain (oldest ancestor first)
    chain: list[OntologyCandidate] = []
    cur: OntologyCandidate | None = target_cand
    visited: set[str] = set()
    while cur is not None:
        cid = str(cur.candidate_id)
        if cid in visited:
            break
        visited.add(cid)
        chain.append(cur)
        parent_id = str(cur.parent_candidate_id) if cur.parent_candidate_id else None
        cur = all_cands.get(parent_id) if parent_id else None

    chain.reverse()  # oldest first

    dom = pop.dominant()
    dom_id = str(dom.candidate_id) if dom else None

    events: list[LineageEventOut] = []
    for i, c in enumerate(chain):
        cid_str = str(c.candidate_id)
        if cid_str == candidate_id:
            event_type: Literal["shift", "introduce", "milestone", "current"] = "current"
        elif i == 0:
            event_type = "introduce"
        else:
            event_type = "introduce"

        dominant_after: str | None = None
        if cid_str == dom_id:
            dominant_after = c.description or cid_str

        events.append(LineageEventOut(
            generation=c.generation,
            event_type=event_type,
            description=c.description or f"Candidate introduced at generation {c.generation}",
            dominant_after=dominant_after,
        ))

    # Add a 'shift' event if the target is (or was) dominant
    if dom_id and dom_id == candidate_id and pop.paradigm_shift_count > 0:
        events.append(LineageEventOut(
            generation=pop.generation,
            event_type="shift",
            description=f"Became dominant candidate after {pop.paradigm_shift_count} paradigm shift(s)",
            dominant_after=target_cand.description or candidate_id,
        ))

    return LineageOut(
        domain=display_name,
        candidate_id=candidate_id,
        events=events,
    )


@app.get("/v1/population/shifts", response_model=ParadigmShiftsOut)
async def population_shifts(domain: str = Query("ng")) -> ParadigmShiftsOut:
    """
    Return the full chronological history of paradigm shifts for a domain.

    A paradigm shift is recorded each time the dominant candidate changes
    during a learning cycle.  Events are written by PopulationManager.end_cycle()
    and persisted to the ``paradigm_shifts`` SQLite table.

    Note: Events are only available from the point when shift logging was first
    enabled.  Older engines that ran before this feature was introduced will
    return an empty list even if shifts occurred historically — the
    ``dominant_hypothesis.candidate_id`` in /v1/population/status still reflects
    the current dominant, and ``paradigm_shifts_this_window`` in that response
    gives the cumulative shift count since startup.
    """
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    raw = engine.population_store.load_shift_events(domain_id)

    events = [
        ParadigmShiftEventOut(
            shift_id=row["shift_id"],
            generation=row["generation"],
            timestamp=row["shift_ts"],
            previous_dominant_id=row["prev_dominant_id"],
            previous_dominant_name=row["prev_dominant_name"],
            new_dominant_id=row["new_dominant_id"],
            new_dominant_name=row["new_dominant_name"],
            evidence_count_at_shift=row["evidence_count_at_shift"],
        )
        for row in raw
    ]

    return ParadigmShiftsOut(
        domain=display_name,
        domain_module_id=domain_id,
        total_shifts=len(events),
        events=events,
    )


@app.get("/v1/export/narrative-snapshot", response_model=NarrativeSnapshotOut)
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
    """
    Structured epistemic-state snapshot designed to be passed to an LLM for
    prose interpretation.  Returns the full current state of the probabilistic
    engine for a domain: regime variables, dominant hypothesis, population
    competition, causal frontier, and machine-readable interpretation hints.
    """
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    pop = engine.get_population(domain_id)
    dom = pop.dominant()
    active = pop.active_candidates()
    summary = pop.summary()

    # ── metadata ──────────────────────────────────────────────────────────────
    evidence_count = engine.evidence_store.count(domain_id)
    metadata = NarrativeMetadataOut(
        domain=display_name,
        domain_module_id=domain_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        evidence_count=evidence_count,
        current_generation=pop.generation,
    )

    # ── current_regime_state: marginal inference per variable ─────────────────
    # Matches RegimeStatePanel: call inference for each variable and use the
    # real posterior P(var=True) rather than raw soft-evidence weights.
    regime_state: list[NarrativeRegimeVariableOut] = []
    variables = pop.candidates[0].variables if pop.candidates else []

    if evidence_count == 0 or not variables:
        # No evidence yet — list variables as unobserved so the LLM knows
        # that scores are prior-only.
        for v in variables:
            regime_state.append(NarrativeRegimeVariableOut(
                name=v.name, boolean_state=None, probability=None
            ))
    else:
        for v in variables:
            try:
                iq = InferenceQuery(
                    domain_module_id=domain_id,
                    target_variables=[v.name],
                    query_type=QueryType.MARGINAL,
                    population_aggregation=PopulationAggregation.ACTIVE_ONLY,
                )
                raw_inf = engine.inference_service.query(iq, pop)
                dist = raw_inf.get("posteriors", {}).get(v.name, {})
                prob: float = float(
                    dist.get("True", dist.get("true", next(iter(dist.values()), 0.5)))
                )
            except Exception:
                prob = 0.5
            regime_state.append(NarrativeRegimeVariableOut(
                name=v.name,
                boolean_state=prob > 0.5,
                probability=prob,
            ))

    # ── dominant_hypothesis ───────────────────────────────────────────────────
    dominant_out: Optional[NarrativeDominantHypothesisOut] = None
    if dom:
        dom_edges: list[NarrativeEdgeOut] = []
        for e in dom.get_active_edges():
            pv = dom.get_variable_by_id(e.parent_variable_id)
            cv = dom.get_variable_by_id(e.child_variable_id)
            if pv and cv:
                dom_edges.append(NarrativeEdgeOut(
                    source=pv.name,
                    target=cv.name,
                    existence_probability=e.existence_probability,
                ))
        gens_dominant = max(0, pop.generation - dom.generation)
        dominant_out = NarrativeDominantHypothesisOut(
            name=dom.description or str(dom.candidate_id)[:8],
            candidate_id=str(dom.candidate_id),
            edge_count=len(dom_edges),
            edges=dom_edges,
            generations_dominant=gens_dominant,
            log_score=dom.log_score,
        )

    # ── competing_candidates ──────────────────────────────────────────────────
    avg_fn = pop._avg_score
    score_map = _normalize_scores(active, avg_fn)
    dom_id = dom.candidate_id if dom else None
    sorted_cands = sorted(active, key=avg_fn, reverse=True)
    n_cands = len(sorted_cands)

    competitor_list: list[NarrativeCompetitorOut] = []
    for i, c in enumerate(sorted_cands):
        if c.candidate_id == dom_id:
            cstatus = "dominant"
        elif i < max(1, n_cands // 3) and c.evidence_count > 0:
            cstatus = "rising"
        elif i >= max(1, 2 * n_cands // 3) and c.evidence_count > 0:
            cstatus = "falling"
        else:
            cstatus = "neutral"
        competitor_list.append(NarrativeCompetitorOut(
            name=c.description or f"Candidate {str(c.candidate_id)[:8]}",
            log_score=c.log_score,
            edge_count=len(c.get_active_edges()),
            status=cstatus,
            score_normalized=score_map.get(c.candidate_id, 0.5),
        ))

    # Score gap: dominant avg score minus second-place avg score
    score_gap: Optional[float] = None
    if len(sorted_cands) >= 2 and dom:
        dom_avg = avg_fn(dom)
        second_cand = sorted_cands[1] if sorted_cands[0].candidate_id == dom_id else sorted_cands[0]
        second_avg = avg_fn(second_cand)
        if math.isfinite(dom_avg) and math.isfinite(second_avg):
            score_gap = dom_avg - second_avg

    competing_out = NarrativeCompetingCandidatesOut(
        candidates=competitor_list,
        score_gap_to_dominant=score_gap,
    )

    # ── ontology_competition ──────────────────────────────────────────────────
    entropy = summary["structure_entropy"]
    if entropy < 0.5:
        entropy_interp = "low"
    elif entropy < 1.5:
        entropy_interp = "medium"
    else:
        entropy_interp = "high"

    shift_events = engine.population_store.load_shift_events(domain_id)
    total_shifts = len(shift_events)
    recent_shifts = [
        NarrativeRecentShiftOut(
            timestamp=ev["shift_ts"],
            from_name=ev["prev_dominant_name"],
            to_name=ev["new_dominant_name"],
            generation=ev["generation"],
        )
        for ev in shift_events[-3:]
    ]

    ontology_out = NarrativeOntologyCompetitionOut(
        structure_entropy=entropy,
        entropy_interpretation=entropy_interp,
        active_candidates=len(active),
        paradigm_shifts_total=total_shifts,
        recent_shifts=recent_shifts,
    )

    # ── frontier ──────────────────────────────────────────────────────────────
    thresholds = engine._modules[domain_id].existence_thresholds()
    explore_lo, explore_hi = thresholds.explore_band
    frontier_edges_out: list[NarrativeFrontierEdgeOut] = []
    if dom:
        for e in dom.get_active_edges():
            if explore_lo <= e.existence_probability <= explore_hi:
                pv = dom.get_variable_by_id(e.parent_variable_id)
                cv = dom.get_variable_by_id(e.child_variable_id)
                if pv and cv:
                    frontier_edges_out.append(NarrativeFrontierEdgeOut(
                        source=pv.name,
                        target=cv.name,
                        probability=e.existence_probability,
                        relation=e.explanatory_label or f"{pv.name}→{cv.name}",
                    ))

    frontier_out = NarrativeFrontierOut(
        frontier_edge_count=len(frontier_edges_out),
        frontier_edges=frontier_edges_out,
    )

    # ── interpretation_hints ──────────────────────────────────────────────────
    hints: list[str] = []

    # Entropy
    if entropy_interp == "low":
        hints.append(
            f"structure_entropy is low ({entropy:.3f}): engine has converged on "
            "a single dominant causal story"
        )
    elif entropy_interp == "medium":
        hints.append(
            f"structure_entropy is medium ({entropy:.3f}): engine is converging "
            "but competing hypotheses remain plausible"
        )
    else:
        hints.append(
            f"structure_entropy is high ({entropy:.3f}): engine has not converged; "
            "multiple causal stories remain plausible"
        )

    # Dominant tenure
    if dom:
        gens = max(0, pop.generation - dom.generation)
        if gens == 0:
            hints.append("dominant hypothesis was introduced in the current generation")
        elif gens == 1:
            hints.append("dominant hypothesis has held for 1 generation")
        else:
            hints.append(f"dominant hypothesis has held for {gens} generations")
    else:
        hints.append("no dominant hypothesis has been established yet")

    # Last paradigm shift timing
    if shift_events:
        last_ts_str = shift_events[-1]["shift_ts"]
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            days_ago = (datetime.now(timezone.utc) - last_ts).days
            if days_ago == 0:
                hints.append("last paradigm shift occurred today")
            elif days_ago == 1:
                hints.append("last paradigm shift was 1 day ago")
            else:
                hints.append(f"last paradigm shift was {days_ago} days ago")
        except Exception:
            hints.append("last paradigm shift timestamp could not be parsed")
    else:
        hints.append("no paradigm shifts recorded since shift logging was enabled")

    # Evidence base size
    if evidence_count == 0:
        hints.append("no evidence has been ingested; scores reflect priors only")
    elif evidence_count < 10:
        hints.append(
            f"evidence base is small ({evidence_count} records); "
            "scores may not yet be reliable"
        )
    else:
        hints.append(f"evidence base: {evidence_count} records ingested")

    # Frontier
    if frontier_edges_out:
        hints.append(
            f"{len(frontier_edges_out)} edge(s) are in the explore band: "
            "causal structure is still being refined in these relations"
        )
    else:
        hints.append(
            "no edges are in the explore band: "
            "dominant causal structure is well-determined"
        )

    return NarrativeSnapshotOut(
        metadata=metadata,
        current_regime_state=regime_state,
        dominant_hypothesis=dominant_out,
        competing_candidates=competing_out,
        ontology_competition=ontology_out,
        frontier=frontier_out,
        interpretation_hints=hints,
    )


@app.get("/v1/evidence/recent", response_model=EvidenceOut)
async def evidence_recent(
    domain: str = Query("ng"),
    limit: int = Query(20, ge=1, le=100),
) -> EvidenceOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    raw_records = engine.evidence_store.load_recent(domain_id, limit)

    records: list[EvidenceRecordOut] = []
    for r in raw_records:
        confidence: float = r.get("confidence", 1.0)
        assignments: list = r.get("assignments", [])
        n_vars = len([a for a in assignments if a.get("missingness", "OBSERVED") == "OBSERVED"])

        if confidence > 0.8:
            strength: Literal["strong", "shift", "weak"] = "strong"
        elif confidence > 0.4:
            strength = "shift"
        else:
            strength = "weak"

        source_ref: str = r.get("source_ref", "")
        description = source_ref if source_ref else f"Evidence record {r['evidence_id'][:8]}"

        records.append(EvidenceRecordOut(
            id=r["evidence_id"],
            timestamp=r["timestamp"],
            description=description,
            impact_delta=confidence,
            strength=strength,
            variables_updated=n_vars if n_vars > 0 else None,
        ))

    return EvidenceOut(domain=display_name, records=records)


# ── Scheduler coroutines ──────────────────────────────────────────────────────

async def _run_macro_regime_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    """
    Weekly macro regime ingestion scheduler.

    Runs on Mondays at run_hour_utc UTC.  On startup, backfills the last
    backfill_weeks weeks if the engine has no evidence yet.

    Cadence rationale: weekly because WALCL (Fed balance sheet) publishes
    weekly (Thursday), and macro regime variables evolve on a weekly-to-monthly
    timescale.  Daily cadence would be noisy and epistemically wasteful.
    """
    from ...domains.macro_regime_v1.ingestion.pipeline import _last_friday
    fred = FREDClient(api_key=fred_api_key)
    pipeline = MacroRegimePipeline(fred)
    scheduler = MacroRegimeScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_weeks=0,
    )
    await _backfill_macro_if_empty(
        engine=engine,
        pipeline=pipeline,
        domain_id="macro-regime-v1",
        display_name="Macro Regime",
        backfill_weeks=backfill_weeks,
        lock=lock,
    )
    async with fred:
        await scheduler.run_forever()


async def _backfill_macro_if_empty(
    *,
    engine: ProbabilisticOntologyEngine,
    pipeline: MacroRegimePipeline,
    domain_id: str,
    display_name: str,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> int:
    """Backfill macro regime if the engine has no evidence records."""
    if backfill_weeks <= 0:
        return 0

    from datetime import timedelta
    from ...domains.macro_regime_v1.scheduler import _weekly_backfill_dates

    today = datetime.now(timezone.utc).date()
    successes = 0
    async with lock:
        existing = engine.evidence_store.count(domain_id)
        if existing > 0:
            logger.info(
                "Skipping %s startup backfill; evidence_count=%d",
                display_name,
                existing,
            )
            return 0

        logger.info(
            "Running %d-week %s startup backfill; evidence_count=0",
            backfill_weeks,
            display_name,
        )
        targets = _weekly_backfill_dates(backfill_weeks, today)
        for target in targets:
            try:
                record = await pipeline.fetch_evidence(target)
                before = engine.evidence_store.count(domain_id)
                engine.ingest(record)
                after = engine.evidence_store.count(domain_id)
                if after > before:
                    engine.learn([record], domain_id)
                    successes += 1
            except Exception as exc:
                logger.error(
                    "%s backfill failed for %s: %s",
                    display_name, target, exc, exc_info=True,
                )
            await asyncio.sleep(2.0)

    logger.info("%s startup backfill complete: %d weeks ingested", display_name, successes)
    return successes


async def _run_ai_regime_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    """
    Weekly AI regime ingestion scheduler.

    Runs on Mondays at run_hour_utc UTC.  On startup, backfills the last
    backfill_weeks weeks if the engine has no evidence yet.

    Cadence rationale: weekly because AI regime variables evolve on a
    weekly-to-quarterly timescale.  yfinance prices are aggregated weekly.
    EDGAR data is cached.  FRED quarterly series are read at their latest
    published value.
    """
    from ...domains.ai_regime_v1.ingestion.pipeline import _last_friday as _ai_last_friday

    yf_client = AIYFinanceClient()
    fred = AIFredClient(api_key=fred_api_key)
    edgar = AIEdgarClient()
    pipeline = AIRegimePipeline(yf_client, fred, edgar)
    scheduler = AIRegimeScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_weeks=0,
    )
    await _backfill_ai_if_empty(
        engine=engine,
        pipeline=pipeline,
        domain_id="ai-regime-v1",
        display_name="AI Regime",
        backfill_weeks=backfill_weeks,
        lock=lock,
    )
    async with fred, edgar, yf_client:
        await scheduler.run_forever()


async def _backfill_ai_if_empty(
    *,
    engine: ProbabilisticOntologyEngine,
    pipeline: AIRegimePipeline,
    domain_id: str,
    display_name: str,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> int:
    """Backfill AI regime if the engine has no evidence records."""
    if backfill_weeks <= 0:
        return 0

    from ...domains.ai_regime_v1.ingestion.pipeline import _weekly_backfill_dates as _ai_backfill_dates

    today = datetime.now(timezone.utc).date()
    successes = 0
    async with lock:
        existing = engine.evidence_store.count(domain_id)
        if existing > 0:
            logger.info(
                "Skipping %s startup backfill; evidence_count=%d",
                display_name,
                existing,
            )
            return 0

        logger.info(
            "Running %d-week %s startup backfill; evidence_count=0",
            backfill_weeks,
            display_name,
        )
        targets = _ai_backfill_dates(backfill_weeks, today)
        for target in targets:
            try:
                record = await pipeline.fetch_evidence(target)
                before = engine.evidence_store.count(domain_id)
                engine.ingest(record)
                after = engine.evidence_store.count(domain_id)
                if after > before:
                    engine.learn([record], domain_id)
                    successes += 1
            except Exception as exc:
                logger.error(
                    "%s backfill failed for %s: %s",
                    display_name, target, exc, exc_info=True,
                )
            await asyncio.sleep(2.0)

    logger.info("%s startup backfill complete: %d weeks ingested", display_name, successes)
    return successes


async def _run_natural_gas_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    api_key: str,
    run_hour_utc: int,
    backfill_days: int,
    lock: asyncio.Lock,
) -> None:
    noaa = NOAAClient()
    eia = EIAClient(api_key=api_key)
    pipeline = NaturalGasPipeline(noaa, eia)
    scheduler = NaturalGasScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_days=0,
    )
    await _backfill_if_empty(
        domain_key="ng",
        engine=engine,
        domain_id="natural-gas-v1",
        display_name="Natural Gas",
        backfill_days=backfill_days,
        lock=lock,
    )
    async with noaa, eia:
        await scheduler.run_forever()


async def _run_sovereign_debt_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    fred = SDFredClient(api_key=fred_api_key)
    pipeline = SovereignDebtPipeline(fred)
    scheduler = SovereignDebtScheduler(engine=engine, pipeline=pipeline,
                                       run_hour_utc=run_hour_utc, backfill_weeks=0)
    await _backfill_fred_domain_if_empty(
        engine=engine, pipeline=pipeline, domain_id="sovereign-debt-v1",
        display_name="Sovereign Debt", backfill_weeks=backfill_weeks, lock=lock,
    )
    async with fred:
        await scheduler.run_forever()


async def _run_credit_cycle_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    fred = CCFredClient(api_key=fred_api_key)
    pipeline = CreditCyclePipeline(fred)
    scheduler = CreditCycleScheduler(engine=engine, pipeline=pipeline,
                                     run_hour_utc=run_hour_utc, backfill_weeks=0)
    await _backfill_fred_domain_if_empty(
        engine=engine, pipeline=pipeline, domain_id="credit-cycle-v1",
        display_name="Credit Cycle", backfill_weeks=backfill_weeks, lock=lock,
    )
    async with fred:
        await scheduler.run_forever()


async def _run_energy_regime_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    fred = ERFredClient(api_key=fred_api_key)
    yf_client = EnergyYFinanceClient()
    pipeline = EnergyRegimePipeline(fred, yf_client)
    scheduler = EnergyRegimeScheduler(engine=engine, pipeline=pipeline,
                                      run_hour_utc=run_hour_utc, backfill_weeks=0)
    await _backfill_fred_domain_if_empty(
        engine=engine, pipeline=pipeline, domain_id="energy-regime-v1",
        display_name="Energy Regime", backfill_weeks=backfill_weeks, lock=lock,
    )
    async with fred, yf_client:
        await scheduler.run_forever()


async def _run_labor_market_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    fred_api_key: str,
    run_hour_utc: int,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> None:
    fred = LMFredClient(api_key=fred_api_key)
    pipeline = LaborMarketPipeline(fred)
    scheduler = LaborMarketScheduler(engine=engine, pipeline=pipeline,
                                     run_hour_utc=run_hour_utc, backfill_weeks=0)
    await _backfill_fred_domain_if_empty(
        engine=engine, pipeline=pipeline, domain_id="labor-market-v1",
        display_name="Labor Market", backfill_weeks=backfill_weeks, lock=lock,
    )
    async with fred:
        await scheduler.run_forever()


async def _backfill_fred_domain_if_empty(
    *,
    engine: ProbabilisticOntologyEngine,
    pipeline: Any,
    domain_id: str,
    display_name: str,
    backfill_weeks: int,
    lock: asyncio.Lock,
) -> int:
    """Generic FRED-domain backfill using weekly targets if engine has no evidence."""
    if backfill_weeks <= 0:
        return 0
    from ...domains.macro_regime_v1.scheduler import _weekly_backfill_dates
    today = datetime.now(timezone.utc).date()
    successes = 0
    async with lock:
        existing = engine.evidence_store.count(domain_id)
        if existing > 0:
            logger.info("Skipping %s startup backfill; evidence_count=%d", display_name, existing)
            return 0
        logger.info("Running %d-week %s startup backfill; evidence_count=0", backfill_weeks, display_name)
        targets = _weekly_backfill_dates(backfill_weeks, today)
        for target in targets:
            try:
                record = await pipeline.fetch_evidence(target)
                before = engine.evidence_store.count(domain_id)
                engine.ingest(record)
                after = engine.evidence_store.count(domain_id)
                if after > before:
                    engine.learn([record], domain_id)
                    successes += 1
            except Exception as exc:
                logger.error("%s backfill failed for %s: %s", display_name, target, exc, exc_info=True)
            await asyncio.sleep(2.0)
    logger.info("%s startup backfill complete: %d weeks ingested", display_name, successes)
    return successes


# ── Utilities ─────────────────────────────────────────────────────────────────

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _require_env(names: tuple[str, ...]) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")


def _data_dir() -> Path:
    d = Path(os.environ.get("POE_DATA_DIR", "."))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


def _log_scheduler_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Scheduler task %s exited with error",
            task.get_name(),
            exc_info=(type(exc), exc, exc.__traceback__),
        )
