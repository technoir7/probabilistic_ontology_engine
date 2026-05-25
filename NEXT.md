# Next Steps

Priority order. Each item has enough context for a cold session to pick up without reconstructing history.

---

## 1. Dashboard frontend integration  ← TOP PRIORITY

### What this is

A read interface that shows the current population state for each registered domain, the dominant candidate graph structure, paradigm shift history, and candidate score trajectories over time. Not a configuration UI; read-only initially.

Two production domains now exist that generate real daily evidence: `natural_gas_v1` (NOAA + EIA) and `corn_v1` (USDA NASS + USDA FAS + Nasdaq ZC1). The dashboard has real data to display.

### FastAPI routes to write first (`src/engine/api/`)

The API layer is a hard prerequisite for any frontend. Write these in order of dependency:

```
GET  /domains                                → list registered domains and their status
GET  /domains/{domain_id}/population         → OntologyPopulation summary dict
GET  /domains/{domain_id}/candidates         → all candidates (active + pruned), sorted by score
GET  /domains/{domain_id}/candidates/{cand}  → single candidate with full edge list + existence probs
GET  /domains/{domain_id}/dominant           → dominant candidate + its active edge structure + scores
GET  /domains/{domain_id}/scores             → candidate_scores time series from PopulationStore
GET  /domains/{domain_id}/edges              → all edges across active candidates with existence probs
POST /domains/{domain_id}/query              → InferenceQuery body → posterior dict + explanation
POST /domains/{domain_id}/ingest             → list[EvidenceRecord] bodies → ingests, returns count
POST /domains/{domain_id}/learn              → run one learning cycle → ModelSnapshot
POST /domains/register                       → register a new domain module
```

Create `src/engine/api/routes.py` with an `APIRouter` and `src/engine/api/app.py` with the FastAPI app and lifespan management.

### Engine integration gap to resolve first

Currently `ProbabilisticOntologyEngine` holds all state in-process with an in-memory `ParameterStore`. Two problems:

1. **Restart loses parameters**: A process restart clears all CPT counts. The `PopulationStore` persists scores and candidate metadata, but parameters are gone. For a useful dashboard, `ParameterStore` must be persisted. Options: serialize CPTData count dicts to a dedicated SQLite table as JSON blobs, or write/load a pickle file per candidate keyed by `candidate_id`. The SQLite approach is cleaner and keeps everything in one database.

2. **Singleton engine**: The FastAPI app needs one shared engine instance. Use FastAPI's `lifespan` context manager to create the engine on startup and shut it down cleanly on exit. Inject it via dependency injection rather than a bare global.

Resolve parameter persistence before writing routes — the routes are not useful without it.

### What the dashboard should show

Priority order within the dashboard itself:

**Score trajectory view** (highest value): A time series showing each candidate's BIC-adjusted average score per learning cycle, with pruning events (red X) and variant introductions (green circle) annotated on the timeline. Data source: `candidate_scores` table in `PopulationStore`, which already records per-batch log-likelihood increments. This view makes paradigm shifts visible as the crossover point where one candidate's score line overtakes another's.

**Dominant graph view**: The current dominant candidate's active edge structure rendered as a directed graph (D3.js or Vega-Lite force layout). Edges are colored by `existence_probability` (green = high, gray = uncertain, red = near-pruning threshold). Node labels are variable names.

**Population table**: All active candidates sorted by BIC-adjusted score, showing: generation, parent lineage, edge count, evidence_count, log_score, `_avg_score`, and status.

**Paradigm shift log**: Timestamped list of dominant candidate changes, with the old and new dominant structures side-by-side.

### Frontend stack

Recommend minimal dependencies:

- **Backend**: FastAPI (already in stack) serving JSON. No additional framework.
- **Graph visualization**: D3.js force layout or Dagre-D3 for the DAG display (handles hierarchical layouts better than force for DAGs).
- **Time series**: Vega-Lite or Chart.js for score trajectories.
- **Deployment**: Static HTML + vanilla JS loaded from FastAPI's `/static` route. No build step needed for MVP.

Avoid Observable Framework or React for the first pass — they add tooling complexity that slows iteration. Plain HTML + CDN-hosted D3 and Vega-Lite is deployable without a build pipeline.

### Tests to write

`tests/integration/test_api.py` using FastAPI's `TestClient`:
- Each route returns 200 with correct schema
- `/domains/{id}/population` includes `structure_entropy`, `paradigm_shift_count`, `dominant_candidate`
- `/domains/{id}/query` returns posteriors for all target variables
- `/domains/{id}/learn` increments `evidence_count` on all candidates
- Regression: after calling `/learn` N times, dominant candidate matches expected structure

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
