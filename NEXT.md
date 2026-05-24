# Next Steps

Priority order. Each item has enough context for a cold session to pick up without reconstructing history.

---

## 1. NOAA and EIA data ingestion for natural gas domain

### What this is

The first real-world domain: natural gas prices. Evidence will come from two public data sources:
- **NOAA** (National Oceanic and Atmospheric Administration) — weather station data, specifically Heating Degree Days (HDD) and Cooling Degree Days (CDD) as proxies for seasonal heating/cooling demand
- **EIA** (Energy Information Administration) — U.S. natural gas storage levels (`EIA-912`), production data (`EIA-914`), and Henry Hub spot prices (`EIA-NG`)

### Variables to define

At minimum (all BOOLEAN or ORDINAL depending on design choice):
- `storage_draw` — weekly storage change (draw vs. build)
- `hdd_above_normal` — heating degree days above 30-year normal
- `cdd_above_normal` — cooling degree days above 30-year normal
- `price_spike` — Henry Hub weekly price change above threshold
- `production_surge` — production week-over-week change above threshold
- `lng_export_high` — LNG export volume above rolling median

The initial T* candidate for this domain should encode the known causal direction: weather → storage draw → price. The T_alt candidate should encode the alternative where production shocks matter more than weather.

### Data ingestion pipeline to build

**NOAA**:
- API: `https://www.ncdc.noaa.gov/cdo-web/api/v2/data`
- Requires free API token from https://www.ncdc.noaa.gov/cdo-web/token
- Relevant dataset: `GHCND` (Global Historical Climatology Network Daily) or the pre-computed HDD/CDD series
- Weekly aggregation needed; raw data is daily
- Variables to pull: `HDD` (heating degree days), `CDD` (cooling degree days), stationId for relevant hubs (Chicago, New York, Houston)

**EIA**:
- API: `https://api.eia.gov/v2/` (requires free API key from https://www.eia.gov/opendata/)
- Storage: series `NG.NW2_EPG0_SWO_R48_BCF.W` — weekly net change in working gas storage
- Price: series `NG.RNGWHHD.W` — Henry Hub Natural Gas Spot Price (weekly)
- Production: series `NG.N9070US2.M` — dry gas production (monthly; needs interpolation or monthly aggregation)

### What to build

Create `src/domains/natural_gas_v1/`:
- `domain.py` — canonical variable defs (module-level UUIDs), initial candidates, CPT definitions from historical priors, domain module class
- `ingestion/noaa_client.py` — requests-based client for NOAA CDO API, returns weekly HDD/CDD by region
- `ingestion/eia_client.py` — requests-based client for EIA API v2, returns weekly storage draws and prices
- `ingestion/pipeline.py` — combines NOAA + EIA into `EvidenceRecord` lists with correct variable UUIDs

### Key design decision needed

Whether variables are BOOLEAN (binary threshold encoding) or ORDINAL (multi-level). BOOLEAN is simpler to start (the current engine only has Dirichlet/CPT for discrete support). ORDINAL would require discretizing HDD/CDD into quantile bins (e.g., low/medium/high). BOOLEAN with domain-expert-chosen thresholds is recommended for first pass.

### Test to write

`tests/integration/test_natural_gas_ingestion.py`:
- Load a known historical week from EIA/NOAA fixtures (saved JSON responses, not live API)
- Assert `EvidenceRecord` has the expected variable IDs and values
- Assert a 10-record batch produces a non-trivial `update_score` on the correct domain

Use fixture files rather than live API calls to keep tests deterministic and fast.

---

## 2. Corn domain module

### What this is

Second real-world domain: corn futures prices. Structurally similar to natural gas but with different causal drivers:
- USDA WASDE reports (monthly) → supply/demand outlook
- Drought Monitor → CONUS drought coverage → yield expectations
- Ethanol blend rates → demand-side pressure
- Brazilian/Argentine crop conditions (Southern Hemisphere offset) → global supply

### Variables to define

- `wasde_bullish` — USDA monthly supply/demand revision (bullish = supply cut or demand raise)
- `drought_severe` — CONUS drought coverage above threshold in Corn Belt (IA, IL, IN, MN)
- `ethanol_grind_high` — weekly ethanol production above seasonal average
- `basis_wide` — cash-futures basis above rolling median (proxy for local demand pressure)
- `price_up` — Dec corn futures week-over-week change above 2%

### Data sources

- **USDA ERS WASDE**: https://www.usda.gov/oce/commodity/wasde/ (monthly PDF; consider scraping or using pre-parsed JSON archives)
- **USDA Drought Monitor**: https://droughtmonitor.unl.edu/DmData/DataDownload/ComprehensiveStatistics.aspx (CSV with weekly state-level drought percentages)
- **CME corn futures**: continuous front-month series via Quandl/EODHD or Yahoo Finance (yfinance)
- **EIA Weekly Petroleum**: ethanol production in `EIA-WPSDB` dataset

### What to build

`src/domains/corn_v1/`:
- `domain.py` — same pattern as `test_domain_v1/domain.py` and `natural_gas_v1/domain.py`
- `ingestion/usda_client.py`
- `ingestion/drought_monitor_client.py`
- `ingestion/corn_pipeline.py`

### Dependency on item 1

Build after natural gas ingestion pipeline. The ingestion client pattern established in item 1 (API key config, fixture-based testing, weekly aggregation logic) should be reused here.

---

## 3. Dashboard frontend integration

### What this is

A read interface that shows the current population state, dominant candidate structure, paradigm shift history, and candidate score trajectories. Not a configuration UI; read-only initially.

### FastAPI routes to write first (src/engine/api/)

This is a prerequisite for any frontend. The routes that matter:

```
GET  /domains                              → list registered domains
GET  /domains/{domain_id}/population       → OntologyPopulation summary dict
GET  /domains/{domain_id}/candidates       → list of all candidates (active + pruned)
GET  /domains/{domain_id}/dominant         → dominant candidate + its edge structure
GET  /domains/{domain_id}/scores           → candidate_scores time series from PopulationStore
POST /domains/{domain_id}/query            → InferenceQuery body → posterior dict
POST /domains/{domain_id}/ingest           → list of EvidenceRecord bodies
POST /domains/{domain_id}/learn            → run one learning cycle, return ModelSnapshot
```

Create `src/engine/api/routes.py` with an `APIRouter`, register it in an `src/engine/api/app.py` that creates the FastAPI app.

### Engine integration gap to resolve

Currently `ProbabilisticOntologyEngine` holds all state in-process. For FastAPI, the engine instance needs to be a global singleton or managed via FastAPI's `lifespan` context. The `ParameterStore` is in-memory only — a process restart loses parameters. For the dashboard to be stateful across restarts, `ParameterStore` must be persisted to disk (SQLite or pickle). This is a prerequisite for the API to be useful in production.

### Frontend stack (if building from scratch)

Recommend keeping it minimal:
- **Observable Framework** or plain HTML + Vega-Lite for the graph visualizations (Bayesian network DAG display)
- **D3.js** for the score trajectory time series (candidate_scores table)
- Static export of the dominant graph as DOT or JSON for the graph renderer

The score trajectory view is the most valuable: a time series showing each candidate's BIC-adjusted average score per batch, with pruning events and variant introductions annotated.

---

## 4. Streaming evidence support

### Problem

`engine.learn(batch)` is synchronous and blocks. The current design expects the caller to assemble a batch and call learn explicitly. This does not fit a real-time data stream where evidence arrives continuously.

### What to build

`src/engine/services/streaming.py` — an async loop that:
1. Consumes from a buffer (asyncio queue or Redis stream)
2. Accumulates records until a configurable `batch_size` is reached or a `flush_interval_seconds` elapsed
3. Calls `engine.learn(batch)` on the flush
4. Publishes the resulting `ModelSnapshot` to a subscriber channel

The simplest implementation uses `asyncio.Queue` for in-process streaming. A Redis Streams version (`XADD` / `XREAD`) would be needed for distributed operation.

### Design considerations

- `EvidenceStore.append_batch` is already designed for batch writes; this does not need to change
- `LearningService.accumulate` and the full `engine.learn` cycle are CPU-bound (not I/O-bound), so async wrapping requires `asyncio.run_in_executor` to avoid blocking the event loop
- Partial batches (fewer than `batch_size` records) should be flushed after `flush_interval_seconds` to prevent stale inference in low-volume periods

### Test to write

`tests/integration/test_streaming.py`:
- Feed 200 records one at a time through the streaming interface
- Assert that after all records are flushed, the dominant candidate matches the expected structure
- Assert that no more than `ceil(200 / batch_size)` learning cycles ran

---

## 5. Larger population sizes beyond MVP

### Current state

`max_population_size=10` is the default. Tests use 5–10. The `_make_variant` loop tries `slots * 10` times; with many admissible edges this is cheap. The bottleneck at larger sizes will be:

1. **`introduce_variants` inner loop**: `existing_sigs = {c.edge_structure_signature() for c in active + new_candidates}` is O(n * |edges|) per attempt. At 100 candidates this becomes measurable.

2. **`prune_low_scorers` ranking**: `sorted(active, key=_avg_score)` is O(n log n) in the number of active candidates. Each `_avg_score` call iterates all edges in the candidate including disabled ones. At 100+ candidates with 10+ edges each, this is still fast but worth profiling.

3. **`InferenceService.query` with `WEIGHTED_AVERAGE`**: Queries every active candidate. At 100 candidates × pgmpy VE inference per query, this becomes slow (~0.5s per query at 20 variables).

4. **ParameterStore memory**: At 100 candidates × 10 variables × 4 parent configs × 2 values × 8 bytes = negligible. But `clone_candidate` deep-copies counts — at 100 candidates introducing 90 variants per cycle, the copy overhead accumulates.

### What to do before scaling

- Profile at `max_population_size=50` with `test_domain_v1` to identify the actual bottleneck (likely `introduce_variants` duplicate-checking or `prune_low_scorers` BIC computation)
- Cache `edge_structure_signature()` on the candidate object (invalidate on edge enable/disable)
- Consider sampling-based inference (pgmpy `BeliefPropagation` with approximate inference) for large populations to avoid O(n) VE calls per query
- The `introduce_variants` "top survivors" parent selection currently uses raw `log_score` sorted descending. At large populations, consider selecting only from the top 5 by BIC-corrected score to avoid parents with lots of evidence but poor fit dominating variant generation

### No test changes needed

Existing tests use `max_population_size` as a parameter in `make_engine_components`. Running L3-05 with `max_pop=50` would stress the size-bounding behavior. Add a large-population smoke test in `tests/integration/` once the API layer exists.

---

## Deferred items (not in current priority order)

- **ARCHIVED candidate status**: `CandidateStatus.ARCHIVED` exists in the enum but is never set. The intent (per SPEC) is that candidates pruned more than N cycles ago are archived rather than just pruned, freeing them for garbage collection. Not needed until population sizes grow large enough to require memory management.

- **TemplateRules for admissible edges**: Currently `_derive_admissible_edges` returns all (a, b) pairs. The SPEC has a TemplateRule concept that would restrict which edges are even considered. Needed for real domains where causal direction is known (e.g., price cannot cause weather).

- **Proper `explore_exploit` integration**: `ExploreExploitService._empirical_mi` is a stub (always returns 0.0). The MI computation needs variable names mapped from UUIDs, which requires passing the variable name index to the function. Then `propose()` results should feed into `introduce_variants` as high-priority candidates rather than random admissible edge selection.

- **Persistence of ParameterStore**: For restartable operation, CPTData count dicts need to be serialized to SQLite (BLOB or a dedicated table) or written to disk as a pickle file keyed by candidate_id.

- **PostgreSQL migration**: The SQLite WAL schema is written to be compatible but not tested against PostgreSQL. A migration file needs to be created and the `TEXT` columns that store JSON should become `JSONB` in PostgreSQL for indexability.
