"""
MacroRegimeScheduler — weekly data ingestion loop for the macro regime domain.

Runs as a standalone async process.  On startup it optionally backfills the
last `backfill_weeks` weeks of data (skipped if the engine already has records
for those dates).  Then it sleeps until the next scheduled Monday run and
repeats indefinitely.

Cadence: WEEKLY on Mondays at 09:00 UTC.
---------------------------------------
Reasoning:
  - WALCL (Fed balance sheet) publishes weekly on Thursdays.  Running Monday
    ensures the previous week's complete data is available.
  - CPI and UNRATE are monthly but we read their latest published value;
    weekly runs capture any monthly updates promptly.
  - Daily signals (T10Y2Y, VIX, credit spreads, FX) are aggregated to weekly
    medians within the pipeline — no value in running daily.
  - Weekly cadence produces ~52 evidence records per year, sufficient for
    the ontology learning cycle to detect regime shifts over 6–18 months.
  - Avoids the high-frequency oversampling issue observed in agriculture
    domains where daily data produced low-entropy repeating states.

Running standalone
------------------
    python -m src.domains.macro_regime_v1.scheduler

Programmatic usage
------------------
    from src.domains.macro_regime_v1.scheduler import MacroRegimeScheduler
    scheduler = MacroRegimeScheduler(engine, pipeline)
    await scheduler.run_forever()

Environment variables
---------------------
    FRED_API_KEY   — required (loaded from .env if python-dotenv is installed)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import MacroRegimeV1, get_variables
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import MacroRegimePipeline, _last_friday

logger = logging.getLogger(__name__)

# The scheduler runs on Mondays at this UTC hour
_DEFAULT_RUN_HOUR_UTC = 9


def _most_recent_monday(as_of: date) -> date:
    """Return the most recent Monday on or before as_of."""
    return as_of - timedelta(days=as_of.weekday())  # weekday() Monday=0


def _weekly_backfill_dates(backfill_weeks: int, today: date) -> list[date]:
    """
    Return list of unique week-ending Fridays for the past backfill_weeks.

    Each date is the Friday of a past week, oldest first.
    """
    fridays: set[date] = set()
    for delta in range(backfill_weeks * 7, 0, -1):
        d = today - timedelta(days=delta)
        if d.weekday() == 4:  # Friday
            fridays.add(d)
    return sorted(fridays)


class MacroRegimeScheduler:
    """
    Weekly ingestion scheduler for the macro regime domain.

    Parameters
    ----------
    engine : ProbabilisticOntologyEngine
        A registered and activated engine (caller must have called
        ``engine.register_domain`` and ``engine.activate_domain`` first).
    pipeline : MacroRegimePipeline
        Configured pipeline with FREDClient.
    run_hour_utc : int
        Hour of day (UTC, 0–23) at which to run the Monday fetch.
        Default 9 (09:00 UTC).
    backfill_weeks : int
        On first startup, attempt to backfill this many prior weeks.
        Set to 0 to disable backfill.
    """

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: MacroRegimePipeline,
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

        `target_date` should be a Friday (week-ending date).  If omitted,
        defaults to the previous Friday.

        Returns True on success, False if fetching failed.
        """
        if target_date is None:
            target_date = _last_friday()

        logger.info(
            "Ingesting macro regime data for week ending %s", target_date
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
                "Macro regime ingestion failed for %s: %s", target_date, exc
            )
            return False

        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
                logger.debug(
                    "Learning cycle complete for macro-regime-v1 @ week-ending %s",
                    target_date,
                )
            except Exception as exc:
                logger.error(
                    "Learning cycle failed for macro-regime-v1 @ %s: %s",
                    target_date, exc, exc_info=True,
                )

        return True

    async def backfill(self) -> int:
        """
        Ingest the last `backfill_weeks` weeks sequentially (oldest first).

        Returns the count of successfully ingested weeks.
        """
        today = datetime.now(timezone.utc).date()
        targets = _weekly_backfill_dates(self._backfill_weeks, today)
        successes = 0
        for target in targets:
            ok = await self.run_once(target)
            if ok:
                successes += 1
            await asyncio.sleep(2.0)  # polite pause between API requests
        return successes

    async def run_forever(self) -> None:
        """
        Run the ingestion loop indefinitely.

        On startup, backfills the last `backfill_weeks` weeks, then sleeps
        until the next Monday at run_hour_utc and repeats.
        """
        logger.info(
            "MacroRegimeScheduler starting. run_hour_utc=%d, backfill_weeks=%d",
            self._run_hour, self._backfill_weeks,
        )

        if self._backfill_weeks > 0:
            n = await self.backfill()
            logger.info("Backfill complete: %d weeks ingested", n)

        while True:
            now = datetime.now(timezone.utc)
            # Next Monday at run_hour_utc
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= self._run_hour:
                days_until_monday = 7
            next_run = (now + timedelta(days=days_until_monday)).replace(
                hour=self._run_hour, minute=0, second=0, microsecond=0
            )

            sleep_s = (next_run - now).total_seconds()
            logger.info(
                "Next macro regime run at %s UTC (%.0f seconds from now)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                sleep_s,
            )
            await asyncio.sleep(sleep_s)
            await self.run_once()  # uses last Friday as default target


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
        db_path="macro_regime.db", random_seed=42
    )
    domain = MacroRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    fred = FREDClient(api_key=api_key)
    pipeline = MacroRegimePipeline(fred)

    scheduler = MacroRegimeScheduler(
        engine=engine,
        pipeline=pipeline,
        run_hour_utc=_DEFAULT_RUN_HOUR_UTC,
        backfill_weeks=52,  # ~1 year of weekly history on first run
    )

    try:
        async with fred:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
