"""
CryptoRegimeScheduler — weekly ingestion loop for crypto-regime-v1.

Cadence: WEEKLY on Mondays at 09:00 UTC.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import CryptoRegimeV1, get_variables
from .ingestion.coingecko_client import CoinGeckoClient
from .ingestion.yfinance_client import CryptoYFinanceClient
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import CryptoRegimePipeline, _last_friday, _weekly_backfill_dates

logger = logging.getLogger(__name__)

_DEFAULT_RUN_HOUR_UTC = 9


class CryptoRegimeScheduler:
    """Weekly ingestion scheduler for crypto-regime-v1."""

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: CryptoRegimePipeline,
        run_hour_utc: int = _DEFAULT_RUN_HOUR_UTC,
        backfill_weeks: int = 8,
    ) -> None:
        self._engine = engine
        self._pipeline = pipeline
        self._run_hour = run_hour_utc
        self._backfill_weeks = backfill_weeks

    async def run_once(self, target_date: date | None = None) -> bool:
        if target_date is None:
            target_date = _last_friday()
        logger.info("Ingesting crypto regime data for week ending %s", target_date)
        try:
            record = await self._pipeline.fetch_evidence(target_date)
            self._engine.ingest(record)
        except Exception as exc:
            logger.error("Crypto regime ingestion failed for %s: %s", target_date, exc)
            return False

        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
            except Exception as exc:
                logger.error("Learning failed for crypto-regime-v1 @ %s: %s", target_date, exc)
        return True

    async def backfill(self) -> int:
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
        logger.info(
            "CryptoRegimeScheduler starting. run_hour_utc=%d, backfill_weeks=%d",
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
                "Next crypto regime run at %s UTC (%.0f s)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                sleep_s,
            )
            await asyncio.sleep(sleep_s)
            await self.run_once()


async def _main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        raise SystemExit("FRED_API_KEY environment variable is not set.")

    engine = ProbabilisticOntologyEngine(db_path="crypto_regime.db", random_seed=42)
    domain = CryptoRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())

    cg = CoinGeckoClient()
    yf = CryptoYFinanceClient()
    fred = FREDClient(api_key=api_key)
    pipeline = CryptoRegimePipeline(cg, yf, fred)
    scheduler = CryptoRegimeScheduler(engine=engine, pipeline=pipeline, backfill_weeks=52)

    try:
        async with cg, fred:
            await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    asyncio.run(_main())
