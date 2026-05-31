#!/usr/bin/env python3
"""
Backfill SF Urban evidence for arbitrary number of weeks.

Usage:
    python scripts/backfill_sf_urban.py --weeks 52
    python scripts/backfill_sf_urban.py --weeks 104 --dry-run
    python scripts/backfill_sf_urban.py --weeks 52 --delay 3.0 --max-retries 5

Features:
    - Idempotent: skips existing records by date
    - Dry-run mode: preview without writing
    - Progress tracking: shows inserted, skipped, and failed counts
    - FRED series caching: fetches each series once, not per-date
    - Exponential backoff for FRED 429 (rate limit)
    - Respects Retry-After header
    - Configurable delay between targets and retry policy
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

# Add src to path so we can import from the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domains.sf_urban_v1.domain import SFUrbanV1
from src.domains.sf_urban_v1.ingestion.sfgov_client import SFGovClient
from src.domains.sf_urban_v1.ingestion.fred_client import (
    FREDClient as SFFredClient,
    FREDObservation,
    FRED_SERIES,
)
from src.domains.sf_urban_v1.ingestion.pipeline import SFUrbanPipeline
from src.engine.engine import ProbabilisticOntologyEngine

logger = logging.getLogger(__name__)


def _weekly_backfill_dates(backfill_weeks: int, today: date) -> list[date]:
    """Generate list of week-ending Fridays for the past N weeks (oldest first)."""
    fridays: set[date] = set()
    for delta in range(backfill_weeks * 7, 0, -1):
        d = today - timedelta(days=delta)
        if d.weekday() == 4:  # Friday
            fridays.add(d)
    return sorted(fridays)


class _CachedFREDClient:
    """
    Wrapper around FREDClient that caches all series on first fetch.

    Dramatically reduces API load when backfilling 50+ weeks (each series
    is fetched once, not once per target date).
    """
    def __init__(self, fred: SFFredClient, max_retries: int = 3, backoff_base: float = 2.0):
        self._fred = fred
        self._cache: dict[str, list[FREDObservation]] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self.retry_stats = {
            "attempts": 0,
            "retries": 0,
            "rate_limit_hits": 0,
            "final_failures": [],
        }

    async def _fetch_series_with_retry(
        self,
        series_id: str,
        end_date: Optional[date] = None,
    ) -> Optional[list[FREDObservation]]:
        """Fetch a single series with exponential backoff for HTTP 429."""
        for attempt in range(1, self._max_retries + 1):
            self.retry_stats["attempts"] += 1
            try:
                logger.debug(
                    "FRED fetch attempt %d/%d for %s",
                    attempt,
                    self._max_retries,
                    series_id,
                )
                obs = await self._fred.fetch_series(series_id, end_date=end_date)
                return obs
            except IOError as exc:
                error_msg = str(exc)
                if "429" in error_msg or "Too Many Requests" in error_msg:
                    self.retry_stats["rate_limit_hits"] += 1
                    if attempt < self._max_retries:
                        # Exponential backoff with jitter
                        wait_time = (self._backoff_base ** (attempt - 1)) + (
                            asyncio.get_event_loop().time() % 1.0
                        )
                        logger.warning(
                            "FRED 429 for %s; retry %d/%d after %.1fs",
                            series_id,
                            attempt,
                            self._max_retries,
                            wait_time,
                        )
                        self.retry_stats["retries"] += 1
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(
                            "FRED 429 for %s; giving up after %d attempts",
                            series_id,
                            self._max_retries,
                        )
                        self.retry_stats["final_failures"].append(
                            {"series_id": series_id, "error": error_msg}
                        )
                        return None
                else:
                    # Non-rate-limit error
                    logger.error("FRED error for %s: %s", series_id, exc)
                    self.retry_stats["final_failures"].append(
                        {"series_id": series_id, "error": error_msg}
                    )
                    return None
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", series_id, exc)
                self.retry_stats["final_failures"].append(
                    {"series_id": series_id, "error": str(exc)}
                )
                return None

    async def cache_all_series(self, end_date: Optional[date] = None) -> None:
        """Fetch and cache all FRED series (once per run, not once per date)."""
        logger.info("Caching FRED series for entire backfill run...")
        series_ids = list(FRED_SERIES.values())

        for series_id in series_ids:
            obs = await self._fetch_series_with_retry(series_id, end_date=end_date)
            if obs:
                self._cache[series_id] = obs
                logger.debug("Cached %d observations for %s", len(obs), series_id)
            else:
                logger.warning("Failed to cache %s; will mark records as partial", series_id)
                self._cache[series_id] = []

    async def fetch_all_series(self, end_date: Optional[date] = None) -> dict[str, list[FREDObservation]]:
        """Return cached series (cache must be populated via cache_all_series first)."""
        # If cache is empty, this is the first call — populate it
        if not self._cache:
            await self.cache_all_series(end_date=end_date)
        return self._cache.copy()


async def backfill_sf_urban(
    weeks: int,
    db_path: str = "sf_urban.db",
    dry_run: bool = False,
    log_level: str = "INFO",
    delay: float = 2.0,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> dict[str, int | float | list]:
    """
    Backfill SF Urban evidence for the specified number of weeks.

    Parameters
    ----------
    weeks : int
        Number of weeks to backfill
    db_path : str
        Path to sf_urban.db (relative to current working directory)
    dry_run : bool
        If True, preview without writing to database
    log_level : str
        Logging level (DEBUG, INFO, WARNING, ERROR)
    delay : float
        Delay in seconds between weekly targets (default: 2.0)
    max_retries : int
        Max retry attempts for FRED 429 responses (default: 3)
    backoff_base : float
        Exponential backoff base for retries (default: 2.0)

    Returns
    -------
    dict
        Summary with keys: inserted, skipped, failed, total_targets, retry_stats, delay
    """
    # Configure logging
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load environment
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Check FRED API key
    fred_api_key = os.environ.get("FRED_API_KEY", "")
    if not fred_api_key:
        raise RuntimeError("FRED_API_KEY environment variable is not set")

    # Initialize engine and domain
    domain_id = "sf-urban-v1"
    engine = ProbabilisticOntologyEngine(db_path=db_path, random_seed=42)
    domain = SFUrbanV1()
    engine.register_domain(domain)
    engine.activate_domain(domain_id)

    # Initialize pipeline with cached FRED client
    sfgov = SFGovClient()
    fred_raw = SFFredClient(api_key=fred_api_key)
    fred_cached = _CachedFREDClient(fred_raw, max_retries=max_retries, backoff_base=backoff_base)
    pipeline = SFUrbanPipeline(sfgov, fred_cached)

    # Generate target dates
    today = datetime.now(timezone.utc).date()
    targets = _weekly_backfill_dates(weeks, today)

    logger.info(
        "SF Urban backfill: %d weeks, %d targets, dry_run=%s, delay=%.1fs, max_retries=%d",
        weeks,
        len(targets),
        dry_run,
        delay,
        max_retries,
    )

    stats = {
        "total_targets": len(targets),
        "inserted": 0,
        "skipped": 0,
        "failed": 0,
        "delay": delay,
        "retry_stats": {},
    }

    try:
        async with sfgov, fred_raw:
            # Pre-cache all FRED series once (not per-target)
            await fred_cached.cache_all_series(end_date=today)
            logger.info("FRED series pre-cached for entire run")

            for i, target in enumerate(targets, 1):
                logger.debug(
                    "Target %d/%d: %s",
                    i,
                    len(targets),
                    target.isoformat(),
                )

                # Check if record already exists for this date
                cursor = engine.evidence_store._conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM evidence_records WHERE domain_module = ? AND timestamp = ?",
                    (domain_id, target.isoformat() + " 00:00:00"),
                )
                exists = cursor.fetchone()[0] > 0

                if exists:
                    logger.info("Skipped %s (already exists)", target.isoformat())
                    stats["skipped"] += 1
                    if i < len(targets):
                        await asyncio.sleep(delay)
                    continue

                try:
                    # Fetch evidence (uses cached FRED series)
                    record = await pipeline.fetch_evidence(target)

                    if dry_run:
                        logger.info(
                            "DRY-RUN: Would insert evidence for %s (confidence=%.2f)",
                            target.isoformat(),
                            record.confidence,
                        )
                        stats["inserted"] += 1
                    else:
                        # Ingest to database
                        before = engine.evidence_store.count(domain_id)
                        engine.ingest(record)
                        after = engine.evidence_store.count(domain_id)

                        if after > before:
                            # Learn from new record
                            engine.learn([record], domain_id)
                            logger.info("Inserted %s (confidence=%.2f)", target.isoformat(), record.confidence)
                            stats["inserted"] += 1
                        else:
                            logger.warning(
                                "Failed to insert %s (ingest returned same count)",
                                target.isoformat(),
                            )
                            stats["failed"] += 1

                except Exception as exc:
                    logger.error(
                        "Backfill failed for %s: %s",
                        target.isoformat(),
                        exc,
                        exc_info=True,
                    )
                    stats["failed"] += 1

                # Polite pause between targets (even for skipped/failed)
                if i < len(targets):
                    await asyncio.sleep(delay)

            # Capture retry statistics
            stats["retry_stats"] = fred_cached.retry_stats

    finally:
        sfgov = None
        fred_raw = None

    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Backfill SF Urban evidence for arbitrary number of weeks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/backfill_sf_urban.py --weeks 52
  python scripts/backfill_sf_urban.py --weeks 104 --dry-run
  python scripts/backfill_sf_urban.py --weeks 52 --delay 2.0 --max-retries 3
  python scripts/backfill_sf_urban.py --weeks 52 --log-level DEBUG --delay 3.0
        """,
    )
    parser.add_argument(
        "--weeks",
        type=int,
        required=True,
        help="Number of weeks to backfill (e.g., 52, 104)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="sf_urban.db",
        help="Path to sf_urban.db (default: sf_urban.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing to database",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between weekly targets (default: 2.0)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retry attempts for FRED 429 responses (default: 3)",
    )
    parser.add_argument(
        "--backoff-base",
        type=float,
        default=2.0,
        help="Exponential backoff base for retries (default: 2.0)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Validate weeks and delay
    if args.weeks <= 0:
        parser.error("--weeks must be positive")
    if args.weeks > 500:
        parser.error("--weeks too large (max 500, which is ~10 years)")
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    if args.max_retries < 0:
        parser.error("--max-retries must be non-negative")
    if args.backoff_base < 1.0:
        parser.error("--backoff-base must be >= 1.0")

    try:
        stats = await backfill_sf_urban(
            weeks=args.weeks,
            db_path=args.db_path,
            dry_run=args.dry_run,
            log_level=args.log_level,
            delay=args.delay,
            max_retries=args.max_retries,
            backoff_base=args.backoff_base,
        )

        # Print summary
        print("\n" + "=" * 70)
        print("SF Urban Backfill Summary")
        print("=" * 70)
        print(f"Total targets:  {stats['total_targets']}")
        print(f"Inserted:       {stats['inserted']}")
        print(f"Skipped:        {stats['skipped']}")
        print(f"Failed:         {stats['failed']}")
        print(f"Delay:          {stats['delay']:.1f}s per target")
        print(f"Dry-run:        {args.dry_run}")
        print()

        # Print FRED retry statistics
        retry_stats = stats.get("retry_stats", {})
        if retry_stats:
            print("FRED Retry Statistics:")
            print(f"  Total fetch attempts:    {retry_stats.get('attempts', 0)}")
            print(f"  HTTP 429 rate limits:    {retry_stats.get('rate_limit_hits', 0)}")
            print(f"  Successful retries:      {retry_stats.get('retries', 0)}")
            final_failures = retry_stats.get("final_failures", [])
            if final_failures:
                print(f"  Final failures:          {len(final_failures)}")
                for failure in final_failures:
                    print(f"    - {failure.get('series_id')}: {failure.get('error')}")
            print()

        print("=" * 70)

        if args.dry_run:
            print("\n✓ Dry-run complete (no changes made)")
        elif stats["failed"] > 0:
            print(f"\n⚠ Backfill complete with {stats['failed']} failure(s)")
        else:
            print("\n✓ Backfill complete")

        return 0 if stats["failed"] == 0 else 1

    except Exception as exc:
        logger.error("Backfill failed: %s", exc, exc_info=True)
        print(f"\n✗ Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
