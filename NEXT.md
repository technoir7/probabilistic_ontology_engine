# Next Steps

Priority order. Each item has enough context for a cold session to pick up without reconstructing history.

---

## 1. API integration tests  ← TOP PRIORITY

### What this is

The FastAPI routes in `src/engine/api/app.py` are now implemented and smoke-tested manually with `TestClient`, but no automated regression tests exist. Without them, route regressions will be invisible.

### Tests to write

`tests/integration/test_api.py` using FastAPI's `TestClient` with `EVIDENCE_SCHEDULER_ENABLED=false`:

```python
@pytest.fixture
def client():
    import os; os.environ["EVIDENCE_SCHEDULER_ENABLED"] = "false"
    from fastapi.testclient import TestClient
    from src.engine.api.app import app
    with TestClient(app) as c:
        yield c
```

Priority test cases:

1. **Schema compliance** — each route returns 200 with all required fields present and of the correct type. Verify against the TypeScript interface field list.

2. **`GET /v1/population/status?domain=ng/zc/zs`** — `active_candidates == 3` (initial), `dominant_hypothesis.candidate_id` is a valid UUID string, `engine_status == 'online'`.

3. **`GET /v1/population/candidates?domain=ng`** — exactly one candidate has `status == 'dominant'`, all `score_normalized` values in [0.05, 0.95], candidates sorted best-first.

4. **`POST /v1/inference/query` with `target_variable='price_up'`** — fuzzy resolution works for all three domains (`ng`→`PriceUp`, `zc`→`CornPriceUp`, `zs`→`SoyPriceUp`), `target_probability` is float in [0, 1], all variable names appear in `nodes`.

5. **Fuzzy resolution edge cases** — `'Price_Up'`, `'PRICE_UP'`, `'priceup'` all resolve; `'nonexistent'` returns 422.

6. **`GET /v1/population/lineage/{id}?domain=ng`** — events list non-empty; last event has `event_type == 'current'`.

7. **`GET /v1/evidence/recent?domain=ng`** — returns `EvidenceOut` with `records` list (may be empty if fresh db).

8. **Unknown domain** — `GET /v1/population/status?domain=xx` → 404.

9. **Score trajectory regression** — ingest 10 synthetic records from `test_domain_v1` generator, call `engine.learn(batch)` 3×, then `GET /v1/population/candidates` shows all `score_normalized` values distinct.

### Persistence gap (still open)

`ParameterStore` is in-memory. A process restart clears CPT counts. `PopulationStore` persists scores and candidate metadata but not the parameters. For a robust deployment, serialize CPTData count dicts to a SQLite table:

```sql
cpt_parameters (
    candidate_id TEXT,
    variable_name TEXT,
    counts_json   TEXT,          -- JSON-serialized CPTData.counts dict
    PRIMARY KEY (candidate_id, variable_name)
)
```

Round-trip: `json.dumps({str(k): dict(v) for k, v in cpt.counts.items()})` → DB → reconstruct counts on load. The `digest()` method already produces a stable hash for validation. Implement in `ParameterStore` with `save_to_db(conn, candidate_id)` and `load_from_db(conn, candidate_id)` methods. Call from engine lifespan (save on shutdown, load on startup).

---

## 2. Streaming evidence support

### Problem

`engine.learn(batch)` is synchronous and blocks. The schedulers (`natural_gas_v1/scheduler.py`, `corn_v1/scheduler.py`) currently call `engine.ingest(record)` which only stores evidence — the learning cycle is not triggered automatically. A human or cron must separately call `engine.learn()`.

### What to build

`src/engine/services/streaming.py` — an async loop that:
1. Consumes from an `asyncio.Queue`
2. Accumulates records until `batch_size` reached or `flush_interval_seconds` elapsed (whichever comes first)
3. Calls `engine.learn(batch)` on flush
4. Publishes the resulting `ModelSnapshot` to a subscriber channel

Wire the existing scheduler `run_once()` methods to push `EvidenceRecord` objects into the queue rather than calling `engine.ingest()` directly.

### Design considerations

- `LearningService.accumulate` and `engine.learn` are CPU-bound, not I/O-bound. Wrap in `asyncio.run_in_executor` with a `ProcessPoolExecutor` to avoid blocking the event loop. A `ThreadPoolExecutor` avoids the GIL concern only if pgmpy releases the GIL during inference, which is not guaranteed.
- `EvidenceStore.append_batch` is already designed for batch writes; no changes needed there.
- Partial batches should flush after `flush_interval_seconds` to prevent stale inference in low-volume periods (e.g. corn domain weekends when no Nasdaq data arrives).
- The natural gas domain produces 1 record/day; the corn domain produces 1 record/day. Both are very low volume. Streaming infrastructure is more valuable once market tick data or multiple domains are running simultaneously.

### Tests to write

`tests/integration/test_streaming.py`:
- Feed 200 records one at a time through the queue
- Assert that after all records flush, dominant candidate matches expected structure
- Assert that no more than `ceil(200 / batch_size)` learning cycles ran
- Assert that flush fires on `flush_interval_seconds` even with a partial batch

---

## 3. Larger population sizes beyond MVP

### Current state

`max_population_size=10` is the default. Tests use 5–10. The bottleneck at larger sizes will be:

1. **`introduce_variants` inner loop**: `existing_sigs = {c.edge_structure_signature() for c in active + new_candidates}` is O(n × |edges|) per attempt. At 100 candidates this is measurable.

2. **`prune_low_scorers` ranking**: `sorted(active, key=_avg_score)` is O(n log n). Each `_avg_score` call iterates all edges including disabled ones.

3. **`InferenceService.query` with `WEIGHTED_AVERAGE`**: Queries every active candidate. At 100 candidates × pgmpy VE inference per query, this becomes slow (~0.5s per query at 20 variables).

4. **`clone_candidate` in ParameterStore**: Deep-copies all CPTData on variant introduction. At 100 candidates introducing 90 variants per cycle, the copy overhead accumulates.

### What to do before scaling

- Profile at `max_population_size=50` with `test_domain_v1` to identify actual bottleneck (expected: `introduce_variants` duplicate-checking or `prune_low_scorers` BIC computation)
- Cache `edge_structure_signature()` on the candidate object; invalidate on edge enable/disable
- Consider sampling-based inference (pgmpy `BeliefPropagation`) for large populations instead of exact VE
- `introduce_variants` parent selection uses raw `log_score` sorted descending; at large populations, restrict to top 5 by BIC-corrected score to avoid high-evidence-count but poor-fit candidates dominating variant generation

### No test changes needed for the change itself

Existing tests parameterize `max_population_size`. Running L3-05 with `max_pop=50` stresses the size-bounding behavior. Add a large-population smoke test in `tests/integration/` once the API layer exists.

---

## Deferred items

- **ARCHIVED candidate status**: `CandidateStatus.ARCHIVED` exists in the enum but is never set. The intent (per SPEC) is that candidates pruned more than N cycles ago are archived and eligible for garbage collection. Not needed until population sizes grow large enough to require memory management.

- **TemplateRules for admissible edges**: `_derive_admissible_edges` returns all (a, b) pairs — it admits edges in both directions and between any two variables. Real domains have known forbidden directions (e.g., price cannot cause planting delay). TemplateRules would encode these constraints and reduce the variant search space.

- **Proper `explore_exploit` integration**: `ExploreExploitService._empirical_mi` is a stub (always returns 0.0). The MI computation needs variable names mapped from UUIDs, which requires passing the variable name index. Once implemented, `propose()` results should feed into `introduce_variants` as high-priority candidates.

- **Persistence of ParameterStore**: Required before the dashboard can survive process restarts. CPTData count dicts need to be serialized to a SQLite table. Simplest schema: `(candidate_id TEXT, variable_name TEXT, counts_json TEXT)`. The `digest()` method already produces a stable hash; round-tripping counts through JSON is the remaining work.

- **PostgreSQL migration**: The SQLite WAL schema is written to be compatible but not tested against PostgreSQL. A migration file needs to be created, and `TEXT` columns storing JSON should become `JSONB` in PostgreSQL for indexability.

- **market_risk_v1 domain**: Only a placeholder `__init__.py` exists. Lower priority now that two production domains (natural gas and corn) are wired with real data.

---

## Completed

### ✓ FastAPI routes — all priority endpoints

`src/engine/api/app.py` — complete rewrite implementing all frontend-required routes.

- `GET /health` — liveness probe
- `GET /runtime` — scheduler task status list
- `GET /v1/population/status?domain=ng|zc|zs` → `PopStatusOut` matching TypeScript `PopulationStatus`
- `GET /v1/population/candidates?domain=ng|zc|zs` → `CandidatesOut` matching TypeScript `CandidatesResponse`
- `POST /v1/inference/query` body `{domain, target_variable, ...}` → `InferenceOut` matching TypeScript `InferenceResponse`. Fuzzy variable matching handles `target_variable: 'price_up'` resolving to domain-specific variable names (`PriceUp`, `CornPriceUp`, `SoyPriceUp`).
- `GET /v1/population/lineage/{candidate_id}?domain=` → `LineageOut`
- `GET /v1/evidence/recent?domain=` → `EvidenceOut`

Architecture: three shared `ProbabilisticOntologyEngine` instances (ng, zc, zs) built at lifespan startup and stored in `app.state.engines`. Schedulers receive these shared engines — no separate engine instances created inside scheduler coroutines. CORS middleware added.

Two new `EvidenceStore` methods added: `load_recent(domain_module_id, limit)` and `latest_timestamp(domain_module_id)`.

All 57 existing tests pass unchanged.

---

### ✓ NOAA and EIA data ingestion for natural gas domain

`src/domains/natural_gas_v1/` — fully implemented and tested.

- `noaa_client.py`: 5 CONUS weather stations via `api.weather.gov`, hourly observations aggregated to daily CONUS mean, HDD and temperature anomaly derived against monthly normals. Station confidence scaling: `max(0.4, stations_used / 5)`. No API key required.
- `eia_client.py`: NASS weekly storage series `NG.NW2_EPG0_SWO_R48_BCF.W` and daily Henry Hub price `NG.RNGWHHD.D` via `api.eia.gov/v2`. Requires `EIA_API_KEY`.
- `pipeline.py`: static `build_evidence_record` maps 4 Boolean variables.
- `scheduler.py`: daily loop at 07:00 UTC, 30-day backfill on startup.
- 10 integration tests (TEST-NG-01..10), all passing.

### ✓ Corn domain module

`src/domains/corn_v1/` — fully implemented and tested.

- `usda_nass_client.py`: USDA NASS Quick Stats API — planting progress, crop conditions (GOOD+EXCELLENT %), yield forecasts. 3 concurrent internal calls per snapshot. 5-year planting average computed from raw historical rows (same ISO week). Seasonal missingness: off-season NASS data returns `None` fields → downstream pipeline produces `MissingnessType.MISSING` assignments with `confidence=0.0`.
- `usda_fas_client.py`: USDA FAS GATS — weekly corn export inspection volume (metric tons). 4-week rolling average baseline. No API key required.
- `nasdaq_client.py`: Nasdaq Data Link CME/ZC1 — front-month corn futures settlement price (cents/bushel). 20-day rolling average baseline. Requires `NASDAQ_API_KEY`.
- `pipeline.py`: static `build_evidence_record` maps 5 Boolean variables. NASS-derived assignments carry `MISSING`/`confidence=0.0` when off-season.
- `scheduler.py`: daily loop at 08:00 UTC, 30-day backfill on startup.
- 16 integration tests (TEST-ZC-01..16), all passing.

### ✓ Soybean domain module

`src/domains/soybean_v1/` — fully implemented and tested.

- `usda_nass_client.py`: USDA NASS Quick Stats API — same three series as corn but with `commodity_desc='SOYBEANS'`. Returns `SoybeanNASSSnapshot`. Identical derived-boolean logic and seasonal missingness semantics.
- `usda_fas_client.py`: USDA FAS GATS — weekly soybean export inspection volume. Commodity code `'SOYBEANS'`. Same rolling-average logic as corn client.
- `nasdaq_client.py`: Nasdaq Data Link CHRIS/CME_S1 — front-month soybean futures settlement price (cents/bushel). 20-day rolling average baseline. Requires `NASDAQ_API_KEY`.
- `pipeline.py`: static `build_evidence_record` maps 5 Boolean variables (PlantingDelayed, DroughtIndex, YieldForecastDown, ExportDemandHigh, SoyPriceUp). NASS-derived assignments carry `MISSING`/`confidence=0.0` when off-season.
- `scheduler.py`: daily loop at **09:00 UTC** (one hour after corn to stagger API calls). 30-day backfill on startup.
- 16 integration tests (TEST-ZS-01..16), all passing.
- Total test suite: **57/57 passing**.
