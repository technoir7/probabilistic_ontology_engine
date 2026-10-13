"""FastAPI application and Railway runtime startup."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..engine import ProbabilisticOntologyEngine
from ..runtime.data_migrations import move_friday_weekly_records_to_sunday
from ..runtime.registry import REGISTRY, DomainRegistration
from ..runtime.scheduler import run_scheduler
from ..runtime.settings import Settings, load_dotenv_unless_disabled
from ..model.cadence import Weekly
from ..model.errors import EngineError, UnknownValue
from . import context
from .routers import debug, evidence, export, inference, ingest, population, reports, service

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv_unless_disabled()
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    scheduler_enabled = settings.scheduler_enabled

    # Always build shared engines so API routes work regardless of scheduler state
    app.state.engines: dict[str, ProbabilisticOntologyEngine] = {}
    for reg in REGISTRY:
        try:
            domain_module = reg.build_domain()
        except ModuleNotFoundError as exc:
            if not reg.optional:
                raise
            # An optional domain's package is absent: serve the others; its
            # routes answer 503 ("engine not initialised").
            logger.warning("%s disabled: %s", reg.display_name, exc)
            continue
        app.state.engines[reg.key] = context.build_engine(domain_module, data_dir / reg.db_filename)
    for reg in REGISTRY:
        if isinstance(reg.cadence, Weekly) and reg.key in app.state.engines:
            move_friday_weekly_records_to_sunday(app.state.engines[reg.key], reg.module_id)
    app.state.scheduler_tasks: list[asyncio.Task] = []
    app.state.scheduler_enabled = scheduler_enabled
    app.state.ingest_locks: dict[str, asyncio.Lock] = {r.key: asyncio.Lock() for r in REGISTRY}

    if scheduler_enabled:
        tasks = []
        for reg in REGISTRY:
            if not reg.scheduled or reg.key not in app.state.engines:
                continue
            missing = settings.missing_env(reg)
            if missing:
                logger.info(
                    "%s not set — %s scheduler disabled; engine initialised but "
                    "no data will be fetched automatically.",
                    ", ".join(missing), reg.display_name,
                )
                continue
            tasks.append(asyncio.create_task(
                _run_domain_scheduler(reg, app.state.engines[reg.key], app.state.ingest_locks[reg.key], settings),
                name=reg.scheduler_task_name,
            ))
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

@app.exception_handler(UnknownValue)
async def _unknown_value(_request: Request, exc: UnknownValue) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(EngineError)
async def _engine_error(_request: Request, exc: EngineError) -> JSONResponse:
    logger.error("Engine error: %s", exc, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# No credentials: the monitor frontend sends no cookies, and a wildcard origin combined
# with credentials would let any site act as a logged-in user. POE_CORS_ORIGINS narrows
# the origins (e.g. to the Vercel deploy URL); operator routes are guarded by api.auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(Settings.from_env().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


for _router in (service, population, debug, ingest, inference, export, reports, evidence):
    app.include_router(_router.router)


# ── Scheduler ─────────────────────────────────────────────────────────────────

async def _run_domain_scheduler(
    reg: DomainRegistration,
    engine: ProbabilisticOntologyEngine,
    lock: asyncio.Lock,
    settings: Settings,
) -> None:
    """Open the domain's source once and run its schedule until cancelled."""
    async with reg.open_source(settings.environ) as source:
        await run_scheduler(
            engine,
            reg.module_id,
            source.fetch_evidence,
            reg.cadence,
            run_hour_utc=settings.run_hour_utc(reg),
            startup_window_days=settings.startup_window_days(reg),
            pause_s=reg.backfill_pause_s,
            lock=lock,
            skip_unchanged_state=reg.skip_unchanged_state,
            clock=context.utcnow,
        )


# ── Utilities ─────────────────────────────────────────────────────────────────

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
