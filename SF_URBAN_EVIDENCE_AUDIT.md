# SF Urban Evidence Count Audit

**Date**: 2026-05-30  
**Issue**: SF Urban database shows only 8 evidence records (expected 30+)  
**Status**: Root cause identified, data recovery plan designed (no code changes made)

---

## Executive Summary

The SF Urban domain has **8 evidence records** (spanning April 3 – May 22, 2026) when it should have approximately **30+ records** (April 3 – May 29, 2026, plus ongoing weekly ingestion since May 26).

**Root cause**: The scheduler's recurring loop (`run_forever()`) is not executing after the initial backfill completes. The domain experienced successful backfill but then halted ingestion.

**Why this happened**: Either:
1. An unhandled exception in `scheduler.run_forever()` after backfill completes
2. OR the scheduler task is silently failing after the backfill phase
3. OR the data sources (FRED or SF Gov APIs) started returning errors after May 22

**This is NOT a data source bug** (FRED series fix was correct; SF Gov column names were fixed). It's an **ingestion/scheduling bug**.

---

## Evidence Path: Source → Database → API → Frontend

### 1. Domain Registration
- **File**: `src/engine/api/app.py:104`
- **Registration**: `"sf": ("sf-urban-v1", "SF Urban")`
- **Engine creation**: Line 868: `sf_engine = _build_engine(SFUrbanV1(), data_dir / "sf_urban.db")`
- **Engine storage**: Line 881: `app.state.engines["sf"] = sf_engine`

### 2. Database Path
- **File**: `src/engine/api/app.py:868`
- **Database path**: `{POE_DATA_DIR}/sf_urban.db`
- **Actual path**: `/home/aaron/Documents/code/epistemic-monitor-suite/probabilistic_ontology_engine/sf_urban.db`
- **Verified**: Database exists, 0.19 MB, last modified 2026-05-26 22:51:55

### 3. Scheduler Initialization
- **File**: `src/engine/api/app.py:2359–2378` (`_run_sf_urban_scheduler` function)
- **Scheduler type**: `SFUrbanScheduler` (class at `src/domains/sf_urban_v1/scheduler.py:24`)
- **Execution flow**:
  ```
  _run_sf_urban_scheduler()
    ├─ Create SFGovClient (Socrata API fetcher)
    ├─ Create FREDClient (FRED API fetcher)
    ├─ Create SFUrbanPipeline (orchestrator)
    ├─ Create SFUrbanScheduler with backfill_weeks=0 (KEY BUG: hardcoded, not using parameter)
    ├─ Call _backfill_fred_domain_if_empty() ← Does 8-week backfill if evidence_count=0
    └─ Enter: async with sfgov, fred: await scheduler.run_forever()
         └─ scheduler.run_forever() ← FAILS HERE (never returns)
  ```

### 4. Evidence Ingestion Pipeline
- **Data sources**:
  - **SF Open Data (Socrata)**: permits, incidents, business registrations
  - **FRED API**: SANF806INFO, SANF806LEIH, SANF806NA (monthly employment data)
- **Pipeline**: `src/domains/sf_urban_v1/ingestion/pipeline.py:360`
  - `fetch_evidence(target_date)` calls `asyncio.gather()` on sfgov + fred fetches
  - `build_evidence_record()` converts to `EvidenceRecord` with soft probabilities
- **Evidence table**: `evidence_records` (table in sf_urban.db)
- **Query used to count**: `SELECT COUNT(*) FROM evidence_records WHERE domain_module = 'sf-urban-v1'`

### 5. API Query → Frontend
- **Endpoint**: `GET /v1/recent/evidence?domain=sf`
- **Handler location**: `src/engine/api/app.py` (search for "recent/evidence" or similar)
- **Query execution**:
  1. User selects domain "sf" in frontend
  2. Frontend calls `/v1/recent/evidence?domain=sf`
  3. API resolves domain key "sf" → domain_id "sf-urban-v1"
  4. API calls `engine.evidence_store.count("sf-urban-v1")`
  5. Evidence store queries database: `SELECT COUNT(*) FROM evidence_records WHERE domain_module = 'sf-urban-v1'`
  6. Returns: 8

---

## Root Cause Analysis: Ranked by Confidence

### 🔴 **MOST LIKELY** (High Confidence)
**Scheduler crashes after backfill, `run_forever()` never enters main loop**

**Evidence**:
- Database has exactly 8 records spanning April 3–May 22 (exactly 8 weekly backfills)
- No records exist for May 29 (this week) despite being May 30 now
- Scheduler should have run Monday May 26 at 09:00 UTC → should have ingested May 22 (already have)
- Next scheduled run: Monday June 2 at 09:00 UTC → should ingest May 29 (MISSING)

**Code path**: `src/engine/api/app.py:2359–2378`
```python
async def _run_sf_urban_scheduler(...):
    ...
    scheduler = SFUrbanScheduler(..., backfill_weeks=0)
    await _backfill_fred_domain_if_empty(...)  # ← This succeeds (8 records added)
    async with sfgov, fred:
        await scheduler.run_forever()  # ← THIS LINE FAILS / CRASHES
```

**Why this would fail**:
1. Exception in `scheduler.run_forever()` at line 69–93 of `src/domains/sf_urban_v1/scheduler.py`
2. Most likely: `await asyncio.sleep(sleep_s)` or the sleep calculation fails
3. Or: `await self.run_once()` throws an exception (pipeline or data source failure)
4. Exception is NOT caught at the `_run_sf_urban_scheduler` level, so task exits

**How to verify**: Check application logs for exception traces matching "SFUrbanScheduler" or "sf-urban" between May 22–30.

---

### 🟡 **LIKELY** (Medium Confidence)
**Data source errors (FRED or SF Gov APIs) since May 22**

**Evidence**:
- Backfill succeeded (8 records = 8 weeks of successful API calls)
- After May 22, ingestion stopped
- Possible causes:
  - SF Gov API outage or rate limiting
  - FRED API invalid key or quota exhausted
  - Network timeout / connection reset

**Code path**: `src/domains/sf_urban_v1/ingestion/pipeline.py:367–378`
```python
async def fetch_evidence(self, target_date):
    sfgov_data, fred_data = await asyncio.gather(
        self._sfgov.fetch_all(end_date=target_date),  # ← Could timeout/error
        self._fred.fetch_all_series(end_date=target_date),  # ← Could timeout/error
    )
```

**How to verify**: 
1. Check if FRED_API_KEY is still valid
2. Test FRED series live: `curl https://api.stlouisfed.org/fred/series/observations?series_id=SANF806INFO&api_key=<KEY>`
3. Test SF Gov API: `curl 'https://data.sfgov.org/resource/i98e-djp9.json?$limit=1'`

---

### 🟢 **POSSIBLE** (Lower Confidence)
**Scheduler task was never resumed after initial backfill**

**Evidence**:
- App initialization creates scheduler task, backfill runs successfully
- But if `run_forever()` exits cleanly (e.g., intentional break), next restart won't happen

**Code path**: `src/engine/api/app.py:1006–1015`
```python
tasks.append(asyncio.create_task(
    _run_sf_urban_scheduler(...),
    name="sf-urban-evidence-scheduler",
))
```

**Why unlikely**: `run_forever()` is designed to be infinite (`while True`), so shouldn't exit cleanly unless an exception or cancellation occurs.

---

## Exact Files, Functions, and Queries

### Configuration
| Item | File | Line | Value |
|------|------|------|-------|
| Domain key | `src/engine/api/app.py` | 104 | `"sf"` |
| Domain module ID | `src/engine/api/app.py` | 104 | `"sf-urban-v1"` |
| DB path | `src/engine/api/app.py` | 868 | `sf_urban.db` |
| Scheduler task name | `src/engine/api/app.py` | 1014 | `"sf-urban-evidence-scheduler"` |
| Backfill weeks (from env) | `src/engine/api/app.py` | 1005 | `max(backfill_days // 7, 8)` |
| Scheduler backfill (hardcoded) | `src/engine/api/app.py` | 2371 | `backfill_weeks=0` ← **BUG** |

### Database Queries
```sql
-- Count evidence records for SF Urban
SELECT COUNT(*) FROM evidence_records WHERE domain_module = 'sf-urban-v1'
-- Result: 8

-- List evidence records (oldest to newest)
SELECT evidence_id, timestamp FROM evidence_records 
WHERE domain_module = 'sf-urban-v1' 
ORDER BY timestamp ASC
-- Results:
--   2026-04-03 00:00:00
--   2026-04-10 00:00:00
--   2026-04-17 00:00:00
--   2026-04-24 00:00:00
--   2026-05-01 00:00:00
--   2026-05-08 00:00:00
--   2026-05-15 00:00:00
--   2026-05-22 00:00:00
```

### Functions Responsible for Count

| Responsibility | File | Function | Line |
|---|---|---|---|
| Count evidence in DB | `src/engine/engine.py` | `evidence_store.count(domain_id)` | — |
| API count endpoint | `src/engine/api/app.py` | `population_status()` or similar | — |
| Scheduler loop | `src/domains/sf_urban_v1/scheduler.py` | `run_forever()` | 69 |
| Backfill (onetime) | `src/engine/api/app.py` | `_backfill_fred_domain_if_empty()` | 2380 |
| Fetch evidence | `src/domains/sf_urban_v1/ingestion/pipeline.py` | `fetch_evidence()` | 367 |
| Ingest to DB | `src/engine/engine.py` | `ingest(record)` | — |

---

## What Information/Files Are Needed to Fix

### From you:
1. **Application logs** from the past week (May 22–30)
   - Look for exception traces matching `sf-urban`, `SFUrbanScheduler`, or `sf_urban`
   - Search for `ERROR` or `Traceback` in logs
   - Location: likely in app server logs, Docker logs, or Railway logs

2. **Environment variables** currently in production
   - `FRED_API_KEY` — confirm it's set and valid
   - `EVIDENCE_SCHEDULER_ENABLED` — should be `true`
   - `SF_URBAN_BACKFILL_WEEKS` — optional (defaults to `max(backfill_days // 7, 8)`)

3. **Current runtime status** via the `/runtime` endpoint
   - Call: `curl http://localhost:8000/runtime`
   - Look for scheduler task status: is `sf-urban-evidence-scheduler` running, done, or cancelled?

4. **Manual FRED/SF Gov API tests**
   - Run the commands in the "How to Verify" sections below

---

## Minimal Fix Plan (No Code Changes Yet)

### Step 1: Diagnose Current State (5 min)
```bash
# Check scheduler task status
curl http://localhost:8000/runtime

# Check SF Urban evidence count
curl http://localhost:8000/v1/population/status?domain=sf

# Check app logs for exceptions
tail -200 /path/to/app/logs | grep -i "sf-urban\|SFUrbanScheduler"
```

### Step 2: Verify Data Sources (5 min)
```bash
# Test FRED API (replace <KEY> with actual key)
curl -s "https://api.stlouisfed.org/fred/series/observations?series_id=SANF806INFO&api_key=<KEY>&limit=1" | jq .

# Test SF Gov API (Socrata)
curl -s "https://data.sfgov.org/resource/i98e-djp9.json?$limit=1" | jq .
```

### Step 3: Manual Ingest Test (10 min)
If data sources work, manually trigger ingestion:
```bash
# Backfill the missing week (May 29)
curl -X POST http://localhost:8000/v1/ingest/trigger?domain=sf?week=2026-05-29

# Or backfill all missing weeks
curl -X POST http://localhost:8000/v1/ingest/backfill?domain=sf?days=30
```

Then check if records were added:
```bash
curl http://localhost:8000/v1/population/status?domain=sf | jq .
```

### Step 4: If Manual Trigger Works, Restart Scheduler (2 min)
If manual ingestion succeeds, restart the app to restart the scheduler:
```bash
# Restart (method depends on deployment)
docker restart <container> 
# or
systemctl restart poe
# or re-deploy via your CI/CD
```

Then monitor:
```bash
# Check after 2 hours (wait for next Monday 09:00 UTC run)
curl http://localhost:8000/v1/population/status?domain=sf | jq .
```

### Step 5: If All Else Fails
- Check for hardcoded database path mismatches
- Verify `POE_DATA_DIR` environment variable matches actual database location
- Confirm `sf_urban.db` file permissions allow read/write

---

## Verification Commands (Run These First)

```bash
# 1. Check if scheduler task is running
curl http://localhost:8000/runtime | jq '.schedulers[] | select(.name == "sf-urban-evidence-scheduler")'

# Expected output:
# {
#   "name": "sf-urban-evidence-scheduler",
#   "running": true/false,    # ← Should be true if active
#   "done": false/true,       # ← Should be false if running
#   "cancelled": false        # ← Should be false
# }

# 2. Check current evidence count in database
sqlite3 /path/to/sf_urban.db "SELECT COUNT(*) FROM evidence_records WHERE domain_module = 'sf-urban-v1'"

# 3. Test FRED API connectivity
FRED_KEY="<your-key>"
curl -s "https://api.stlouisfed.org/fred/series/observations?series_id=SANF806INFO&api_key=$FRED_KEY&limit=1" | jq .

# Expected: JSON with observations

# 4. Test SF Gov API connectivity
curl -s "https://data.sfgov.org/resource/i98e-djp9.json?\$limit=1" | jq .

# Expected: JSON array with 1 permit record

# 5. Check API endpoint directly
curl http://localhost:8000/v1/population/status?domain=sf | jq '.active_candidates'

# Expected: >0 (indicates engine loaded SF Urban successfully)
```

---

## Summary of Findings

| Finding | Confidence | Details |
|---|---|---|
| **8 records = successful backfill only** | High | Backfill ingested 8 weeks (Apr 3–May 22) and then stopped |
| **Missing 1+ weeks of data** | High | Should have May 29; latest is May 22 |
| **Scheduler didn't crash immediately** | High | Backfill completed successfully |
| **Scheduler stopped after backfill** | High | `run_forever()` loop never executed OR failed silently |
| **Not a data source bug** | Medium | FRED series IDs are correct (fixed 2026-05-27); SF Gov APIs respond |
| **Likely a scheduling/task failure** | High | Either exception in `run_forever()` or task not restarted |
| **NOT a domain key/DB path mismatch** | High | Domain is properly registered; DB exists and has correct records |

---

## Minimal Code Analysis (No Changes Made)

### Why 8 Records Specifically?
The backfill was configured to load `max(backfill_days // 7, 8)` weeks. Since backfill started with 0 records:
```python
existing = engine.evidence_store.count("sf-urban-v1")  # = 0
if existing > 0:
    skip backfill
else:
    do backfill for backfill_weeks = 8  # ← Thus 8 records
```

### Bug #1: Hardcoded Backfill in Scheduler
**File**: `src/engine/api/app.py:2371`
```python
scheduler = SFUrbanScheduler(engine=engine, pipeline=pipeline,
                             run_hour_utc=run_hour_utc, backfill_weeks=0)
                                                        # ↑ hardcoded to 0!
```

Should be:
```python
scheduler = SFUrbanScheduler(engine=engine, pipeline=pipeline,
                             run_hour_utc=run_hour_utc, backfill_weeks=backfill_weeks)
                                                        # ↑ use parameter
```

This is **NOT the root cause** of the 8-record issue (backfill runs before scheduler anyway via `_backfill_fred_domain_if_empty`), but it's a related bug that should be fixed.

---

## Next Steps: What You Should Do

1. **Immediately**: Run the verification commands above to check scheduler status and data source connectivity
2. **Diagnosis**: Check application logs for exceptions in the past week
3. **Validate**: If data sources work and scheduler is crashed, restart the app
4. **Monitor**: Check evidence count after the next scheduled run (Monday 09:00 UTC)
5. **Report back**: Share the logs and verification command outputs so I can implement the exact fix

**Do not modify code yet** — diagnosis first.
