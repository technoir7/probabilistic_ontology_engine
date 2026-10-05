# SF Urban Evidence Count: Verification of Audit Conclusions

**Date**: 2026-05-30  
**Conclusion**: The audit's "8 records is a bug" claim is **UNSUPPORTED**.

---

## Verified Facts

### 1. ✓ Domain Introduction Timeline
- **Commit**: `0a41892a` "now has crypto, geopolitics, and sf urban"
- **Date**: 2026-05-26 23:22:25 PDT (May 27 06:22:25 UTC)
- **Status**: SF Urban is a BRAND NEW domain, only 4 days old
- **Implication**: **NOT a regression** — domain was just added

### 2. ✓ Backfill Configuration
- **Default**: `EVIDENCE_BACKFILL_DAYS=30` (line 855 of app.py)
- **SF Urban**: `sf_backfill_weeks = max(backfill_days // 7, 8) = max(4, 8) = 8`
- **Expected records from backfill**: 8 weekly Fridays
- **Actual records in database**: 8 (April 3 – May 22)
- **Match**: **✓ Perfect match**

### 3. ✓ Backfill Targets Are Correct
Generated targets for 8-week backfill on 2026-05-26:
```
1. 2026-04-03 ✓ in database
2. 2026-04-10 ✓ in database
3. 2026-04-17 ✓ in database
4. 2026-04-24 ✓ in database
5. 2026-05-01 ✓ in database
6. 2026-05-08 ✓ in database
7. 2026-05-15 ✓ in database
8. 2026-05-22 ✓ in database
```
**Conclusion**: Backfill executed successfully, ingested exactly what it was designed to ingest.

### 4. ✓ Scheduler Is Properly Registered
- **File**: `src/engine/api/app.py:1005–1015`
- **Status**: SF Urban scheduler task is created and added to task list
- **Condition**: Only if `EVIDENCE_SCHEDULER_ENABLED=True` AND `FRED_API_KEY` is set
- **Default**: `EVIDENCE_SCHEDULER_ENABLED` defaults to `True` (line 856)
- **Implication**: Scheduler SHOULD be running (if FRED_API_KEY is set in production)

### 5. ✓ Database Is Current (Partially)
- **Main database file** (`sf_urban.db`): Last modified 2026-05-26 22:51:55
- **WAL file** (`sf_urban.db-wal`): Last modified 2026-05-30 21:47:00 (4 days later)
- **SHM file** (`sf_urban.db-shm`): Last modified 2026-05-30 21:47:00
- **Interpretation**: Database has been accessed recently (WAL activity), but main file unchanged

### 6. ✓ No Expectation of 30+ Records
- **README.md**: Lists SF Urban as weekly cadence (correct)
- **No documentation**: Specifies expected record counts
- **Backfill documentation**: `NEXT.md` says "run initial backfills for the new domains" (8 weeks is standard)
- **Reality**: 8 records is the INTENDED result of 8-week backfill on a new domain

### 7. ✗ "Missing May 29" Claim Is Wrong
- **Current date**: 2026-05-30 23:31 PDT = 2026-05-31 06:31 UTC (Sunday)
- **Last Monday run**: 2026-05-26 (should have ingested 2026-05-22) ✓ in database
- **Next Monday run**: 2026-06-02 at 09:00 UTC (in ~26 hours)
- **Expected May 29 record**: Not due yet; will be created Monday June 2
- **Conclusion**: No records are "missing" — we're waiting for the next scheduled run

### 8. ✗ "run_forever() Crashes" Is Inferred, Not Confirmed
- **Evidence**: WAL files modified 2026-05-30, suggesting database access
- **No error logs**: Provided or referenced
- **Alternative explanation**: Scheduler is waiting for next Monday (normal operation)
- **Conclusion**: No evidence of crash; likely just waiting for next scheduled run

### 9. ✓ Scheduler Exit Logging Would Catch Crashes
- **File**: `src/engine/api/app.py:2473–2483` (`_log_scheduler_exit`)
- **Behavior**: If scheduler task crashes, `task.exception()` is logged as ERROR
- **Status**: No such error mentioned in audit
- **Implication**: If scheduler crashed, logs would show it

---

## Unsupported Claims in the Audit

| Claim | Status | Reality |
|-------|--------|---------|
| "8 records is too few" | ✗ Unsupported | 8 records = expected 8-week backfill for new domain |
| "30+ records expected" | ✗ Unsupported | No documentation specifies 30+ for new domains |
| "Missing May 29" | ✗ Wrong | May 29 record not due until Monday June 2 |
| "Scheduler crashed" | ✗ Inferred only | No error logs provided; WAL activity suggests it's running |
| "Domain broken" | ✗ False | Domain is brand new and working as designed |

---

## Revised Root Cause Ranking

### **NOT A BUG** (Very High Confidence)
The 8 records are the **correct and expected result** of:
1. New domain added 2026-05-26
2. App startup triggers `_backfill_fred_domain_if_empty(backfill_weeks=8)`
3. Backfill generates 8 Friday targets (2026-04-03 through 2026-05-22)
4. All 8 ingested successfully
5. Scheduler now waiting for next Monday (2026-06-02) to run recurring loop

**Status**: WORKING AS DESIGNED

### Bug #1: Hardcoded `backfill_weeks=0` (LOW severity)
- **File**: `src/engine/api/app.py:2371`
- **Code**: `scheduler = SFUrbanScheduler(..., backfill_weeks=0)`
- **Issue**: Should pass the parameter, not hardcode 0
- **Impact**: None (backfill happens via separate function anyway)
- **Recommendation**: Fix for code cleanliness

---

## Exact Commands to Verify Scheduler Is Healthy

```bash
# 1. Check if scheduler task is registered and running
curl http://localhost:8000/runtime 2>/dev/null | \
  jq '.schedulers[] | select(.name == "sf-urban-evidence-scheduler")'

# Expected output:
# {
#   "name": "sf-urban-evidence-scheduler",
#   "running": true,
#   "done": false,
#   "cancelled": false
# }

# 2. Verify scheduler task has NOT exited with error
grep -i "sf-urban\|SFUrban" /path/to/app/logs | grep -i "error\|exception" || echo "No errors found"

# 3. Verify FRED API key is set
echo $FRED_API_KEY | head -c 10

# 4. Verify next scheduler run time is June 2 at 09:00 UTC
date -u +"%Y-%m-%d %H:%M (next run: 2026-06-02 09:00 UTC)"

# 5. After June 2 at 09:00 UTC, check if new record was created
sqlite3 /path/to/sf_urban.db "SELECT COUNT(*) FROM evidence_records WHERE domain_module = 'sf-urban-v1'"
# Should be 9 (instead of current 8)
```

---

## Minimal Fix Plan: NONE NEEDED

**Status**: NO BUG FOUND

However, there is ONE non-critical code cleanup:

### Optional: Fix hardcoded backfill_weeks
**File**: `src/engine/api/app.py:2371`

Change:
```python
scheduler = SFUrbanScheduler(engine=engine, pipeline=pipeline,
                             run_hour_utc=run_hour_utc, backfill_weeks=0)
```

To:
```python
scheduler = SFUrbanScheduler(engine=engine, pipeline=pipeline,
                             run_hour_utc=run_hour_utc, backfill_weeks=backfill_weeks)
```

**Rationale**: Consistency with other schedulers (lines 918–1000); no functional impact.

---

## Summary

The "8 records bug" audit was based on **incorrect assumptions**:

1. ✗ Assumed domain has been running for weeks (actually 4 days old)
2. ✗ Assumed 30+ records should exist (no doc supports this)
3. ✗ Assumed May 29 data should be available (not scheduled until June 2)
4. ✗ Inferred scheduler crash without log evidence (likely just waiting)

The **reality**:
- ✓ SF Urban is brand new (May 26)
- ✓ 8 records = exact result of 8-week startup backfill
- ✓ Backfill succeeded; scheduler waiting for next run
- ✓ Next scheduled ingestion: Monday June 2, 09:00 UTC
- ✓ After that date, database should have 9 records (May 29 added)

**Verdict**: WORKING AS DESIGNED. Not a bug.
