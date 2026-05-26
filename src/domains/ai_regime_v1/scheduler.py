"""
AIRegimeScheduler — weekly data ingestion loop for the ai-regime-v1 domain.

Runs as a standalone async process.  On startup it optionally backfills
the last `backfill_weeks` weeks of data.  Then it sleeps until the next
scheduled Monday run and repeats indefinitely.

Cadence: WEEKLY on Mondays at 09:00 UTC.
---------------------------------------
Reasoning:
    - Consistent with macro_regime_v1 (weekly, Monday 09:00 UTC).
    - yfinance prices update daily; weekly aggregation reduces noise
      without losing interpretive value.
    - FRED quarterly series (Y033RC1Q027SBEA, PRS85006092, A191RL1Q225SBEA)
      publish every ~3 months.  Weekly runs capture revisions and new
      releases promptly.
    - SEC EDGAR 10-Q filings publish quarterly; the EDGAR client caches
      responses for 6 hours, so weekly runs impose minimal EDGAR load.
    - AI regime transitions (infrastructure buildout → bubble → productivity
      regime) operate on month-to-quarter timescales.  Weekly evidence
      provides ~52 data points/year — sufficient for ontology learning.
    - Daily cadence would inject noise from day-to-day price volatility
      without increasing interpretive signal.

Running standalone
------------------
    python -m src.domains.ai_regime_v1.scheduler

Programmatic usage
------------------
    from src.domains.ai_regime_v1.scheduler import AIRegimeScheduler
    scheduler = AIRegimeScheduler(engine, pipeline)
    await scheduler.run_forever()

Environment variables
---------------------
    FRED_API_KEY   — required for FRED data (loaded from .env if python-dotenv)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import AIRegimeV1, get_variables
from .ingestion.edgar_client import EDGARClient
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import AIRegimePipeline, _last_friday, _weekly_backfill_dates
from .ingestion.yfinance_client import AIYFinanceClient

logger = logging.getLogger(__name__)

_DEFAULT_RUN_HOUR_UTC = 9


class AIRegimeScheduler:
    """
    Weekly ingestion scheduler for the ai-regime-v1 domain.

    Parameters
    ----------
    engine : ProbabilisticOntologyEngine
        Registered and activated engine (caller must have called
        engine.register_domain and engine.activate_domain first).
    pipeline : AIRegimePipeline
        Configured pipeline with yfinance, FRED, and EDGAR clients.
    run_hour_utc : int
        Hour (UTC) at which the Monday fetch runs.  Default 9.
    backfill_weeks : int
        On first startup, backfill this many prior weeks.  0 = disabled.
    """

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: AIRegimePipeline,
        run_hour_utc: int = _DEFAULT_RUN_HOUR_UTC,
        backfill_weeks: int = 8,
    ) -> None:
        self._engine = engine
        self._pipeline = pipeline
        self._run_hour = run_hour_utc
        self._backfill_weeks = backfill_weeks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_once(self, target_date: date | None = None) -> bool:
        """
        Fetch, ingest, and learn from data for the week ending `target_date`.

        Returns True on success, False if fetching failed.
        """
        if target_date is None:
            target_date = _last_friday()

        logger.info(
            "Ingesting ai-regime data for week ending %s", target_date
        )
        try:
            record = await self._pipeline.fetch_evidence(target_date)
            self._engine.ingest(record)
            logger.info(
                "Ingested evidence_id=%s for week ending %s",
                record.evidence_id, target_date,
            )
        except Exception as exc:
            logger.error(
                "AI regime ingestion failed for %s: %s", target_date, exc
            )
            return False

        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
                logger.debug(
                    "Learning cycle complete for ai-regime-v1 @ week-ending %s",
                    target_date,
                )
            except Exception as exc:
                logger.error(
                    "Learning cycle failed for ai-regime-v1 @ %s: %s",
                    target_date, exc, exc_info=True,
                )

        return True

    async def backfill(self) -> int:
        """
        Ingest the last `backfill_weeks` weeks sequentially (oldest first).

        Returns count of successfully ingested weeks.
        """
        today = datetime.now(timezone.utc).date()
        targets = _weekly_backfill_dates(self._backfill_weeks, today)
        successes = 0
        for target in targets:
            ok = await self.run_once(target)
            if ok:
                successes += 1
            await asyncio.sleep(2.0)
        return successes

    async def run_forever(self) -> None:
        """
        Run the ingestion loop indefinitely.

        On startup, backfills the last `backfill_weeks` weeks if needed,
        then sleeps until the next Monday at run_hour_utc and repeats.
        """
        logger.info(
            "AIRegimeScheduler starting. run_hour_utc=%d, backfill_weeks=%d",
            self._run_hour, self._backfill_weeks,
        )

        if self._backfill_weeks > 0:
            n = await self.backfill()
            logger.info("Backfill complete: %d weeks ingested", n)

        while True:
            now = datetime.now(timezone.utc)
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= self._run_hour:
                days_until_monday = 7
            next_run = (now + timedelta(days=days_until_monday)).replace(
                hour=self._run_hour, minute=0, second=0, microsecond=0
            )

            sleep_s = (next_run - now).total_seconds()
            logger.info(
                "Next ai-regime run at %s UTC (%.0f seconds from now)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                sleep_s,
            )
            await asyncio.sleep(sleep_s)
            await self.run_once()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _load_env() -> None:
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

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "FRED_API_KEY environment variable is not set. "
            "Add it to .env or export it before running."
        )

    engine = ProbabilisticOntologyEngine(
        db_path="ai_regime.db", random_seed=42
    )
    domain = AIRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    yf_client = AIYFinanceClient()
    fred = FREDClient(api_key=api_key)
    edgar = EDGARClient()
    pipeline = AIRegimePipeline(yf_client, fred, edgar)

    scheduler = AIRegimeScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=_DEFAULT_RUN_HOUR_UTC,
        backfill_weeks=52,
    )

    try:
        async with fred, edgar, yf_client:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
