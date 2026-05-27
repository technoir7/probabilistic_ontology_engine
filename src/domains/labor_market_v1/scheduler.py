"""LaborMarketScheduler — weekly ingestion loop for labor-market-v1."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from ...engine.engine import ProbabilisticOntologyEngine
from .domain import LaborMarketV1
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import LaborMarketPipeline, _last_friday, _weekly_backfill_dates

logger = logging.getLogger(__name__)
_DEFAULT_RUN_HOUR_UTC = 9


class LaborMarketScheduler:
    """Weekly ingestion scheduler for labor-market-v1."""

    def __init__(
        self,
        engine: ProbabilisticOntologyEngine,
        pipeline: LaborMarketPipeline,
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
        try:
            record = await self._pipeline.fetch_evidence(target_date)
            self._engine.ingest(record)
        except Exception as exc:
            logger.error("Labor market ingestion failed for %s: %s", target_date, exc)
            return False
        domain_id = self._engine.active_domain
        if domain_id:
            try:
                self._engine.learn([record], domain_id)
            except Exception as exc:
                logger.error("Learning failed for labor-market-v1 @ %s: %s", target_date, exc)
        return True

    async def backfill(self) -> int:
        today = datetime.now(timezone.utc).date()
        targets = _weekly_backfill_dates(self._backfill_weeks, today)
        successes = 0
        for target in targets:
            if await self.run_once(target):
                successes += 1
            await asyncio.sleep(2.0)
        return successes

    async def run_forever(self) -> None:
        if self._backfill_weeks > 0:
            n = await self.backfill()
            logger.info("Labor market backfill complete: %d weeks ingested", n)
        while True:
            now = datetime.now(timezone.utc)
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= self._run_hour:
                days_until_monday = 7
            next_run = (now + timedelta(days=days_until_monday)).replace(
                hour=self._run_hour, minute=0, second=0, microsecond=0
            )
            await asyncio.sleep((next_run - now).total_seconds())
            await self.run_once()
