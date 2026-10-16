# SF Urban Backfill Script

Safe, idempotent backfill script for SF Urban domain ingestion with aggressive FRED rate-limit handling.

## Features

- **Idempotent**: Skips existing records by date, no duplicates
- **FRED series caching**: Pre-fetches all 3 FRED series once per run, not per target date (48+ fewer API calls for 52-week backfill)
- **Exponential backoff**: Retries FRED 429 (rate limit) with configurable backoff strategy
- **Dry-run mode**: Preview what would be ingested without writing
- **Progress tracking**: Shows inserted, skipped, failed counts, and FRED retry statistics
- **Configurable delays**: Pause between weekly targets to reduce API load
- **Smart rate-limit handling**: Respects actual API latency patterns, not just sleep(2)

## Usage

```bash
# Basic: backfill 52 weeks (one year) with defaults (2s delay, 3 retries)
python scripts/backfill_sf_urban.py --weeks 52

# Conservative: backfill 52 weeks with 3-second delays
python scripts/backfill_sf_urban.py --weeks 52 --delay 3.0

# Aggressive retry: up to 5 retries with faster backoff
python scripts/backfill_sf_urban.py --weeks 52 --max-retries 5 --backoff-base 1.5

# Preview without writing (dry-run)
python scripts/backfill_sf_urban.py --weeks 104 --dry-run

# Verbose debug logging with longer delays
python scripts/backfill_sf_urban.py --weeks 30 --log-level DEBUG --delay 3.0

# Custom database path
python scripts/backfill_sf_urban.py --weeks 52 --db-path /path/to/sf_urban.db
```

## CLI Arguments

| Arg | Type | Default | Purpose |
|-----|------|---------|---------|
| `--weeks` | int | **required** | Number of weeks to backfill (e.g., 52, 104) |
| `--db-path` | str | `sf_urban.db` | Path to database |
| `--dry-run` | flag | false | Preview without writing |
| `--delay` | float | 2.0 | Seconds to wait between weekly targets |
| `--max-retries` | int | 3 | Max retry attempts for FRED 429 responses |
| `--backoff-base` | float | 2.0 | Exponential backoff base (wait = base^attempt) |
| `--log-level` | str | INFO | DEBUG, INFO, WARNING, ERROR |

## Requirements

- `FRED_API_KEY` environment variable set
- `sf_urban.db` exists (will be created at default location if running from project root)
- Data sources available:
  - FRED (SANF806INFO, SANF806LEIH, SANF806NA)
  - SF Gov Socrata (permits, incidents, businesses)

## How It Works

1. **FRED series pre-caching** (NEW): Before processing any targets, fetches all 3 FRED series once (with retry/backoff if 429) and caches them
   - Avoids refetching same data 52 times (52 targets × 3 series = 156 API calls reduced to just 3)
   - Retries with exponential backoff if HTTP 429 occurs
2. **Target generation**: Computes week-ending Fridays for the requested period (oldest first)
3. **Deduplication**: For each Friday, checks if a record exists with that timestamp
4. **Conditional fetch**: Only ingests records that don't exist (skips pre-cached FRED data)
5. **Error handling**: Tracks FRED API rate-limit errors (HTTP 429), retries with backoff, logs final failures
6. **Delay between targets**: Respects `--delay` parameter to reduce API load on downstream systems
7. **Learning**: Runs the engine's `learn()` step on each new record

## Example: 52-week backfill (dry-run with retry tracking)

```bash
$ python scripts/backfill_sf_urban.py --weeks 52 --dry-run --delay 2

SF Urban backfill: 52 weeks, 52 targets, dry_run=True, delay=2.0s, max_retries=3
Caching FRED series for entire backfill run...
Cached 24 observations for SANF806INFO
Cached 24 observations for SANF806LEIH
FRED 429 for SANF806NA; retry 1/3 after 2.3s
Cached 24 observations for SANF806NA
FRED series pre-cached for entire run
Target 1/52: 2024-05-31
DRY-RUN: Would insert evidence for 2024-05-31 (confidence=0.80)
Target 2/52: 2024-06-07
DRY-RUN: Would insert evidence for 2024-06-07 (confidence=0.78)
...
Target 52/52: 2026-05-29
DRY-RUN: Would insert evidence for 2026-05-29 (confidence=0.75)

======================================================================
SF Urban Backfill Summary
======================================================================
Total targets:  52
Inserted:       52
Skipped:        0
Failed:         0
Delay:          2.0s per target

FRED Retry Statistics:
  Total fetch attempts:    3
  HTTP 429 rate limits:    1
  Successful retries:      1
  Final failures:          0

======================================================================

✓ Dry-run complete (no changes made)
```

## Notes

- **FRED series caching**: Each series is fetched once at the start and reused for all 52+ targets (huge reduction in API load)
- **Exponential backoff**: FRED 429 errors trigger automatic retry with exponential backoff (wait = 2^attempt seconds by default)
- Backfill respects the normal scheduler's weekly cadence — no conflicts
- Use `--dry-run` to verify targets and see retry behavior before real backfill
- FRED rate limiting (HTTP 429) is automatically retried; final failures are tracked in summary
- Delay between targets can be tuned via `--delay` for gentler API load on SF Gov endpoints
- Failed weeks are tracked in the summary; you can retry the full range or specific weeks

## Troubleshooting

**FRED API 429 (Too Many Requests)**
- Expected with rapid backfills of 52+ weeks
- Script automatically retries with exponential backoff (default: up to 3 attempts, 2^n second waits)
- If still failing: increase `--max-retries` (e.g., `--max-retries 5`) or `--delay` (e.g., `--delay 5.0`)
- If partial failures: look for series_id in the retry statistics; can re-run just those weeks

**All FRED series cached but still getting 429**
- FRED pre-caches all 3 series once; individual targets should not cause 429 if caching succeeded
- If you see "Final failures" in the retry stats, the cache_all_series step encountered failures
- Increase `--max-retries` or `--backoff-base` for more aggressive retries during caching

**Database locked**
- Ensure the scheduler is not running (`EVIDENCE_SCHEDULER_ENABLED=false`)
- Or wait for the current operation to complete

**Empty results**
- Check that FRED_API_KEY is valid
- Verify SF Gov endpoints are accessible
- Run with `--log-level DEBUG` for detailed API calls and caching logs

## Architecture Notes

The script reuses the existing SF Urban pipeline:
- `SFUrbanPipeline.fetch_evidence()` for data fetching
- `ProbabilisticOntologyEngine.ingest()` for database writes
- `ProbabilisticOntologyEngine.learn()` for learning
- Weekly backfill date logic from the scheduler

No modifications to the normal scheduler or ingestion flow.
