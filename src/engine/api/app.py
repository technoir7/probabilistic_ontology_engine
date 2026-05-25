"""FastAPI application and Railway runtime startup."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ...domains.corn_v1.domain import CornV1
from ...domains.corn_v1.ingestion.nasdaq_client import NASDAQClient
from ...domains.corn_v1.ingestion.pipeline import CornPipeline
from ...domains.corn_v1.ingestion.usda_fas_client import USDAFASClient
from ...domains.corn_v1.ingestion.usda_nass_client import USDANASSClient
from ...domains.corn_v1.scheduler import IngestionScheduler as CornScheduler
from ...domains.natural_gas_v1.domain import NaturalGasV1
from ...domains.natural_gas_v1.ingestion.eia_client import EIAClient
from ...domains.natural_gas_v1.ingestion.noaa_client import NOAAClient
from ...domains.natural_gas_v1.ingestion.pipeline import NaturalGasPipeline
from ...domains.natural_gas_v1.scheduler import (
    IngestionScheduler as NaturalGasScheduler,
)
from ..engine import ProbabilisticOntologyEngine

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ("EIA_API_KEY", "NASDAQ_API_KEY")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_env()
    _configure_logging()

    app.state.scheduler_tasks = []
    app.state.scheduler_enabled = _env_bool("EVIDENCE_SCHEDULER_ENABLED", True)

    if app.state.scheduler_enabled:
        _require_env(REQUIRED_ENV_VARS)
        data_dir = _data_dir()
        backfill_days = _env_int("EVIDENCE_BACKFILL_DAYS", 30)

        tasks = [
            asyncio.create_task(
                _run_natural_gas_scheduler(
                    db_path=data_dir / "natural_gas.db",
                    api_key=os.environ["EIA_API_KEY"],
                    run_hour_utc=_env_int("NATURAL_GAS_RUN_HOUR_UTC", 7),
                    backfill_days=backfill_days,
                ),
                name="natural-gas-evidence-scheduler",
            ),
            asyncio.create_task(
                _run_corn_scheduler(
                    db_path=data_dir / "corn.db",
                    nasdaq_api_key=os.environ["NASDAQ_API_KEY"],
                    nass_api_key=os.environ.get("NASS_API_KEY", ""),
                    run_hour_utc=_env_int("CORN_RUN_HOUR_UTC", 8),
                    backfill_days=backfill_days,
                ),
                name="corn-evidence-scheduler",
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


app = FastAPI(
    title="Probabilistic Ontology Engine",
    version="0.1.0",
    lifespan=lifespan,
)


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


async def _run_natural_gas_scheduler(
    *,
    db_path: Path,
    api_key: str,
    run_hour_utc: int,
    backfill_days: int,
) -> None:
    engine = ProbabilisticOntologyEngine(db_path=str(db_path), random_seed=42)
    domain = NaturalGasV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

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
    db_path: Path,
    nasdaq_api_key: str,
    nass_api_key: str,
    run_hour_utc: int,
    backfill_days: int,
) -> None:
    engine = ProbabilisticOntologyEngine(db_path=str(db_path), random_seed=42)
    domain = CornV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    nass = USDANASSClient(api_key=nass_api_key)
    fas = USDAFASClient()
    nasdaq = NASDAQClient(api_key=nasdaq_api_key)
    pipeline = CornPipeline(nass, fas, nasdaq)
    scheduler = CornScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=run_hour_utc,
        backfill_days=backfill_days,
    )

    async with nass, fas, nasdaq:
        await scheduler.run_forever()


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
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variable(s): {joined}")


def _data_dir() -> Path:
    data_dir = Path(os.environ.get("POE_DATA_DIR", "."))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


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
