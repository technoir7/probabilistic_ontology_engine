"""
IngestionScheduler — weekly data ingestion loop for the corn (ZC) domain.

Runs as a standalone async process.  On startup it optionally backfills the
last `backfill_days` days of data, then sleeps until the next scheduled run
time and repeats indefinitely.

Default schedule: 08:00 UTC daily.  This is after USDA NASS publishes its
Monday weekly crop progress reports (released 15:00 ET Monday = 20:00 UTC)
for the preceding week. Yahoo Finance ZC=F close prices are
available the evening of each trading day.

Running standalone
------------------
    python -m src.domains.corn_v1.scheduler

Programmatic usage
------------------
    from src.domains.corn_v1.scheduler import IngestionScheduler
    scheduler = IngestionScheduler(engine, pipeline, run_hour_utc=8)
    await scheduler.run_forever()

Environment variables
---------------------
    None required for corn price data. NASS_API_KEY is optional for USDA NASS.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from ..agriculture_weekly import (
    is_duplicate_recent_state,
    latest_complete_week_ending,
    latest_week_ending_on_or_before,
    weekly_backfill_dates,
)
from .domain import CornV1, get_variables
from .ingestion.nasdaq_client import NASDAQClient
from .ingestion.pipeline import CornPipeline
from .ingestion.usda_nass_client import USDANASSClient

logger = logging.getLogger(__name__)


class IngestionScheduler:
    """
    Weekly ingestion scheduler for the corn domain.

    Parameters
    ----------
    engine : ProbabilisticOntologyEngine
        A registered and activated engine.
    pipeline : CornPipeline
        Configured pipeline with NASS and price clients.
    run_hour_utc : int
        Hour of day (UTC, 0–23) at which to run the daily fetch.  Default 8.
    backfill_days : int
        On first startup, attempt to backfill this many prior days.
        Set to 0 to disable.
    """

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: CornPipeline,
        run_hour_utc: int = 8,
        run_weekday_utc: int = 1,
        backfill_days: int = 7,
    ) -> None:
        self._engine       = engine
        self._pipeline     = pipeline
        self._run_hour     = run_hour_utc
        self._run_weekday  = run_weekday_utc
        self._backfill_days = backfill_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_once(self, target_date: date | None = None) -> bool:
        """
        Fetch, ingest, and learn from data for `target_date` (defaults to
        the latest completed ISO week-ending Sunday).

        Returns True on success, False if fetching failed.

        Note: ingestion and learning are both attempted.  A learning failure
        is logged but does not make the run return False — the evidence record
        is still persisted.
        """
        if target_date is None:
            target_date = latest_complete_week_ending(datetime.now(timezone.utc).date())
        else:
            target_date = latest_week_ending_on_or_before(target_date)

        logger.info("Ingesting corn data for %s", target_date)
        try:
            record = await self._pipeline.fetch_evidence(target_date)
            domain_id = self._engine.active_domain
            recent = (
                self._engine.evidence_store.load_recent(domain_id, limit=1)
                if domain_id
                else []
            )
            if is_duplicate_recent_state(record, recent):
                logger.info("Skipping duplicate corn state for week ending %s", target_date)
                return True
            self._engine.ingest(record)
            logger.info(
                "Ingested evidence_id=%s for %s", record.evidence_id, target_date
            )
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", target_date, exc)
            return False

        # Trigger the learning / evolution cycle for every ingested record.
        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
                logger.debug(
                    "Learning cycle complete for corn-v1 @ %s", target_date
                )
            except Exception as exc:
                logger.error(
                    "Learning cycle failed for corn-v1 @ %s: %s",
                    target_date, exc, exc_info=True,
                )

        return True

    async def backfill(self) -> int:
        """
        Ingest weekly records covering the prior `backfill_days` window.
        Returns the count of records actually inserted.
        """
        today = datetime.now(timezone.utc).date()
        successes = 0
        domain_id = self._engine.active_domain
        for target in weekly_backfill_dates(self._backfill_days, today):
            before = self._engine.evidence_store.count(domain_id) if domain_id else 0
            ok = await self.run_once(target)
            after = self._engine.evidence_store.count(domain_id) if domain_id else before
            if ok and after > before:
                successes += 1
            await asyncio.sleep(1.0)   # polite pause between API requests
        return successes

    async def run_forever(self) -> None:
        """
        Run the ingestion loop indefinitely.  Backfills on startup, then
        sleeps until the next daily run time.
        """
        logger.info(
            "CornIngestionScheduler starting. run_hour_utc=%d, backfill_days=%d",
            self._run_hour, self._backfill_days,
        )

        if self._backfill_days > 0:
            n = await self.backfill()
            logger.info("Backfill complete: %d days ingested", n)

        while True:
            now = datetime.now(timezone.utc)
            days_ahead = (self._run_weekday - now.weekday()) % 7
            next_run = (now + timedelta(days=days_ahead)).replace(
                hour=self._run_hour, minute=0, second=0, microsecond=0
            )
            if next_run <= now:
                next_run += timedelta(weeks=1)

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

    engine = ProbabilisticOntologyEngine(db_path="corn.db", random_seed=42)
    domain = CornV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    nass   = USDANASSClient()
    nasdaq = NASDAQClient()
    pipeline = CornPipeline(nass, nasdaq)

    scheduler = IngestionScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=8,
        backfill_days=30,
    )

    try:
        async with nass, nasdaq:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Corn scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
