"""
IngestionScheduler — daily data ingestion loop for the corn (ZC) domain.

Runs as a standalone async process.  On startup it optionally backfills the
last `backfill_days` days of data, then sleeps until the next scheduled run
time and repeats indefinitely.

Default schedule: 08:00 UTC daily.  This is after USDA NASS publishes its
Monday weekly crop progress reports (released 15:00 ET Monday = 20:00 UTC)
for the preceding week; and after FAS weekly export inspection summaries are
available (published Tuesday mornings).  Nasdaq ZC1 settlement prices are
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
    NASDAQ_API_KEY   — required (loaded from .env if python-dotenv is installed)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import CornV1, get_variables
from .ingestion.nasdaq_client import NASDAQClient
from .ingestion.pipeline import CornPipeline
from .ingestion.usda_fas_client import USDAFASClient
from .ingestion.usda_nass_client import USDANASSClient

logger = logging.getLogger(__name__)


class IngestionScheduler:
    """
    Daily ingestion scheduler for the corn domain.

    Parameters
    ----------
    engine : ProbabilisticOntologyEngine
        A registered and activated engine.
    pipeline : CornPipeline
        Configured pipeline with NASS, FAS, and Nasdaq clients.
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
        backfill_days: int = 7,
    ) -> None:
        self._engine       = engine
        self._pipeline     = pipeline
        self._run_hour     = run_hour_utc
        self._backfill_days = backfill_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_once(self, target_date: date | None = None) -> bool:
        """
        Fetch and ingest data for `target_date` (defaults to yesterday UTC).
        Returns True on success, False if fetching failed.
        """
        if target_date is None:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        logger.info("Ingesting corn data for %s", target_date)
        try:
            record = await self._pipeline.fetch_evidence(target_date)
            self._engine.ingest(record)
            logger.info(
                "Ingested evidence_id=%s for %s", record.evidence_id, target_date
            )
            return True
        except Exception as exc:
            logger.error("Ingestion failed for %s: %s", target_date, exc)
            return False

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

    nasdaq_key = os.environ.get("NASDAQ_API_KEY", "")
    if not nasdaq_key:
        raise SystemExit(
            "NASDAQ_API_KEY environment variable is not set. "
            "Add it to .env or export it before running.  "
            "Free registration at https://data.nasdaq.com/sign-up"
        )

    engine = ProbabilisticOntologyEngine(db_path="corn.db", random_seed=42)
    domain = CornV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    nass   = USDANASSClient()
    fas    = USDAFASClient()
    nasdaq = NASDAQClient(api_key=nasdaq_key)
    pipeline = CornPipeline(nass, fas, nasdaq)

    scheduler = IngestionScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=8,
        backfill_days=30,
    )

    try:
        async with nass, fas, nasdaq:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Corn scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
