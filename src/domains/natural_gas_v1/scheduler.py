"""
IngestionScheduler — daily data ingestion loop for the natural gas domain.

Runs as a standalone async process.  On startup it optionally backfills the
last `backfill_days` days of data (skipped if the engine already has records
for those dates).  Then it sleeps until the next scheduled run time and
repeats indefinitely.

Default schedule: 07:00 UTC daily.  This is after the NWS observation rollup
for the previous day is complete and after EIA publishes Thursday storage
reports (published 10:30 ET / 15:30 UTC, but we read the stored value, not the
release event, so 07:00 UTC the following morning is safe).

Running standalone
------------------
    python -m src.domains.natural_gas_v1.scheduler

Programmatic usage
------------------
    from src.domains.natural_gas_v1.scheduler import IngestionScheduler
    scheduler = IngestionScheduler(engine, pipeline, run_hour_utc=7)
    await scheduler.run_forever()

Environment variables
---------------------
    EIA_API_KEY   — required (loaded from .env if python-dotenv is installed)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import NaturalGasV1, get_variables
from .ingestion.eia_client import EIAClient
from .ingestion.noaa_client import NOAAClient
from .ingestion.pipeline import NaturalGasPipeline

logger = logging.getLogger(__name__)


class IngestionScheduler:
    """
    Daily ingestion scheduler for the natural gas domain.

    Parameters
    ----------
    engine : ProbabilisticOntologyEngine
        A registered and activated engine (caller must call
        ``engine.register_domain`` and ``engine.activate_domain`` before
        passing it here).
    pipeline : NaturalGasPipeline
        Configured pipeline with NOAA and EIA clients.
    run_hour_utc : int
        Hour of day (UTC, 0–23) at which to run the daily fetch.
        Default 7.
    backfill_days : int
        On first startup, attempt to backfill this many prior days.
        Set to 0 to disable backfill.
    """

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: NaturalGasPipeline,
        run_hour_utc: int = 7,
        backfill_days: int = 7,
    ) -> None:
        self._engine = engine
        self._pipeline = pipeline
        self._run_hour = run_hour_utc
        self._backfill_days = backfill_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_once(self, target_date: date | None = None) -> bool:
        """
        Fetch, ingest, and learn from data for `target_date` (defaults to
        yesterday UTC).

        Returns True on success, False if fetching failed.

        Note: ingestion and learning are both attempted.  A learning failure
        is logged but does not make the run return False — the evidence record
        is still persisted.
        """
        explicit_target_date = target_date is not None
        if target_date is None:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        logger.info("Ingesting natural gas data for %s", target_date)
        try:
            record = await self._pipeline.fetch_evidence(
                target_date,
                eia_target_date=target_date if explicit_target_date else None,
                use_latest_eia=not explicit_target_date,
            )
            self._engine.ingest(record)
            logger.info("Ingested evidence_id=%s for %s", record.evidence_id, target_date)
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", target_date, exc)
            return False

        # Trigger the learning / evolution cycle for every ingested record.
        # This updates candidate CPT parameters, edge existence probabilities,
        # candidate scores (evidence_count, log_score), and introduces variants.
        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
                logger.debug(
                    "Learning cycle complete for natural-gas-v1 @ %s", target_date
                )
            except Exception as exc:
                logger.error(
                    "Learning cycle failed for natural-gas-v1 @ %s: %s",
                    target_date, exc, exc_info=True,
                )

        return True

    async def backfill(self) -> int:
        """
        Ingest the last `backfill_days` days sequentially (oldest first).
        Returns the count of successfully ingested days.
        """
        today = datetime.now(timezone.utc).date()
        successes = 0
        for delta in range(self._backfill_days, 0, -1):
            target = today - timedelta(days=delta)
            ok = await self.run_once(target)
            if ok:
                successes += 1
            # Brief pause between requests to be polite to the APIs
            await asyncio.sleep(1.0)
        return successes

    async def run_forever(self) -> None:
        """
        Run the ingestion loop indefinitely.

        On startup, backfills the last `backfill_days` days, then sleeps
        until the next daily run time.
        """
        logger.info(
            "IngestionScheduler starting. run_hour_utc=%d, backfill_days=%d",
            self._run_hour, self._backfill_days,
        )

        if self._backfill_days > 0:
            n = await self.backfill()
            logger.info("Backfill complete: %d days ingested", n)

        while True:
            now = datetime.now(timezone.utc)
            next_run = now.replace(
                hour=self._run_hour, minute=0, second=0, microsecond=0
            )
            if next_run <= now:
                next_run += timedelta(days=1)

            sleep_s = (next_run - now).total_seconds()
            logger.info(
                "Next run at %s UTC (%.0f seconds from now)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                sleep_s,
            )
            await asyncio.sleep(sleep_s)
            await self.run_once()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load .env if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


async def _main() -> None:
    _load_env()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    api_key = os.environ.get("EIA_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "EIA_API_KEY environment variable is not set. "
            "Add it to .env or export it before running."
        )

    engine = ProbabilisticOntologyEngine(db_path="natural_gas.db", random_seed=42)
    domain = NaturalGasV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    noaa = NOAAClient()
    eia = EIAClient(api_key=api_key)
    pipeline = NaturalGasPipeline(noaa, eia)

    scheduler = IngestionScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=7,
        backfill_days=30,
    )

    try:
        async with noaa, eia:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
