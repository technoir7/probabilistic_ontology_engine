"""FastAPI application and Railway runtime startup."""
from __future__ import annotations

import asyncio
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ...domains.corn_v1.domain import CornV1
from ...domains.corn_v1.ingestion.nasdaq_client import NASDAQClient as CornNASDAQClient
from ...domains.corn_v1.ingestion.pipeline import CornPipeline
from ...domains.corn_v1.ingestion.usda_fas_client import USDAFASClient as CornFASClient
from ...domains.corn_v1.ingestion.usda_nass_client import USDANASSClient as CornNASSClient
from ...domains.corn_v1.scheduler import IngestionScheduler as CornScheduler
from ...domains.natural_gas_v1.domain import NaturalGasV1
from ...domains.natural_gas_v1.ingestion.eia_client import EIAClient
from ...domains.natural_gas_v1.ingestion.noaa_client import NOAAClient
from ...domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline
from ...domains.natural_gas_v1.scheduler import IngestionScheduler as NaturalGasScheduler
from ...domains.soybean_v1.domain import SoybeanV1
from ...domains.soybean_v1.ingestion.nasdaq_client import NASDAQClient as SoyNASDAQClient
from ...domains.soybean_v1.ingestion.pipeline import SoybeanPipeline
from ...domains.soybean_v1.ingestion.usda_fas_client import USDAFASClient as SoyFASClient
from ...domains.soybean_v1.ingestion.usda_nass_client import USDANASSClient as SoyNASSClient
from ...domains.soybean_v1.scheduler import IngestionScheduler as SoybeanScheduler
from ..engine import ProbabilisticOntologyEngine
from ..schemas import InferenceQuery, OntologyCandidate, PopulationAggregation, QueryType

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ("EIA_API_KEY", "NASDAQ_API_KEY")

# Short name → (domain_module_id, display_name)
_DOMAIN_MAP: dict[str, tuple[str, str]] = {
    "ng": ("natural-gas-v1", "Natural Gas"),
    "zc": ("corn-v1", "Corn"),
    "zs": ("soybean-v1", "Soybeans"),
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
    zc_engine = _build_engine(CornV1(), data_dir / "corn.db")
    zs_engine = _build_engine(SoybeanV1(), data_dir / "soybean.db")

    app.state.engines: dict[str, ProbabilisticOntologyEngine] = {
        "ng": ng_engine,
        "zc": zc_engine,
        "zs": zs_engine,
    }
    app.state.scheduler_tasks: list[asyncio.Task] = []
    app.state.scheduler_enabled = scheduler_enabled

    if scheduler_enabled:
        _require_env(REQUIRED_ENV_VARS)
        tasks = [
            asyncio.create_task(
                _run_natural_gas_scheduler(
                    engine=ng_engine,
                    api_key=os.environ["EIA_API_KEY"],
                    run_hour_utc=_env_int("NATURAL_GAS_RUN_HOUR_UTC", 7),
                    backfill_days=backfill_days,
                ),
                name="natural-gas-evidence-scheduler",
            ),
            asyncio.create_task(
                _run_corn_scheduler(
                    engine=zc_engine,
                    nasdaq_api_key=os.environ["NASDAQ_API_KEY"],
                    nass_api_key=os.environ.get("NASS_API_KEY", ""),
                    run_hour_utc=_env_int("CORN_RUN_HOUR_UTC", 8),
                    backfill_days=backfill_days,
                ),
                name="corn-evidence-scheduler",
            ),
            asyncio.create_task(
                _run_soybean_scheduler(
                    engine=zs_engine,
                    nasdaq_api_key=os.environ["NASDAQ_API_KEY"],
                    nass_api_key=os.environ.get("NASS_API_KEY", ""),
                    run_hour_utc=_env_int("SOYBEAN_RUN_HOUR_UTC", 9),
                    backfill_days=backfill_days,
                ),
                name="soybean-evidence-scheduler",
            ),
        ]
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
    pop = engine.get_population(domain_id)
    summary = pop.summary()
    dom = pop.dominant()

    # Frontier edges: explore-band edges on the dominant candidate
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

    # Resolve candidate
    cand: OntologyCandidate | None = None
    if body.candidate_id:
        target_uuid = UUID(body.candidate_id)
        for c in pop.active_candidates():
            if c.candidate_id == target_uuid:
                cand = c
                break
        if cand is None:
            raise HTTPException(status_code=404, detail=f"Candidate '{body.candidate_id}' not found")
    else:
        cand = pop.dominant()
        if cand is None:
            raise HTTPException(status_code=503, detail="No active candidates")

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

    # Find the requested candidate (active or pruned)
    all_cands = {str(c.candidate_id): c for c in pop.candidates}
    if candidate_id not in all_cands:
        raise HTTPException(status_code=404, detail=f"Candidate '{candidate_id}' not found")

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

async def _run_natural_gas_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    api_key: str,
    run_hour_utc: int,
    backfill_days: int,
) -> None:
    noaa = NOAAClient()
    eia = EIAClient(api_key=api_key)
    pipeline = NaturalGasPipeline(noaa, eia)
    scheduler = NaturalGasScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_days=backfill_days,
    )
    async with noaa, eia:
        await scheduler.run_forever()


async def _run_corn_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    nasdaq_api_key: str,
    nass_api_key: str,
    run_hour_utc: int,
    backfill_days: int,
) -> None:
    nass = CornNASSClient(api_key=nass_api_key)
    fas = CornFASClient()
    nasdaq = CornNASDAQClient(api_key=nasdaq_api_key)
    pipeline = CornPipeline(nass, fas, nasdaq)
    scheduler = CornScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_days=backfill_days,
    )
    async with nass, fas, nasdaq:
        await scheduler.run_forever()


async def _run_soybean_scheduler(
    *,
    engine: ProbabilisticOntologyEngine,
    nasdaq_api_key: str,
    nass_api_key: str,
    run_hour_utc: int,
    backfill_days: int,
) -> None:
    nass = SoyNASSClient(api_key=nass_api_key)
    fas = SoyFASClient()
    nasdaq = SoyNASDAQClient(api_key=nasdaq_api_key)
    pipeline = SoybeanPipeline(nass, fas, nasdaq)
    scheduler = SoybeanScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_days=backfill_days,
    )
    async with nass, fas, nasdaq:
        await scheduler.run_forever()


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
