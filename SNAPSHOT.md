# Codebase Snapshot — 2026-05-26

Current handoff snapshot for `probabilistic_ontology_engine`. This is a state document, not marketing copy.

---

## Status

- Backend: FastAPI + Pydantic v2 probabilistic ontology engine.
- Frontend: Next.js dashboard in sibling `epistemic-monitor`, wired to live backend APIs.
- Current test status: **183/183 passing** with `.venv/bin/python -m pytest tests/ -v`.
- Flagship domain: **macro_regime_v1** (`mr`) using FRED macro-financial series.
- Backfill state:
  - NG: 365-day backfill completed.
  - MR: 730-day backfill completed.
  - ZC/ZS: blocked on invalid `NASS_API_KEY`; get a new key from `https://quickstats.nass.usda.gov`.
- FRED access: working when ProtonVPN is active. FRED currently blocks the normal IP path; keep the VPN up for MR ingestion/backfills.

---

## Domains

### `macro_regime_v1` — **current flagship**

Path: `src/domains/macro_regime_v1/`

Purpose: stress-test ontology evolution under macro-financial regime shifts, heterogeneous frequencies, noisy evidence, and competing causal narratives.

Cadence: weekly. The scheduler uses prior-week data and runs weekly because WALCL is weekly, CPI/UNRATE are monthly, and daily market series are better treated as weekly regime signals than as daily ontology shocks.

Data source: FRED API via `FRED_API_KEY`.

Important runtime note: FRED API calls currently require ProtonVPN to be active because the non-VPN IP path is blocked.

Variables, all Boolean:
- `YieldCurveInverted` from `T10Y2Y`
- `InflationShock` from `CPIAUCSL`
- `LiquidityStress` from `WALCL`
- `CreditSpreadStress` from `BAMLH0A0HYM2`
- `VolatilityShock` from `VIXCLS`
- `DollarStrength` from `DEXUSEU`
- `EquityRiskOn` from `UNRATE`
- `AIRiskOn` from `NASDAQCOM`

Seed candidates:
- `T_monetary`: inflation-driven tightening chain
- `T_credit`: credit-market-led regime
- `T_ai_boom`: AI/productivity narrative dominant
- `T_recession`: recessionary tightening cascade
- `T_null`: volatility-only baseline

Implementation files:
- `domain.py`: stable variable IDs, 8 variables, 5 seed candidates.
- `ingestion/fred_client.py`: async FRED observations client.
- `ingestion/pipeline.py`: derives weekly evidence and soft probabilities.
- `scheduler.py`: weekly macro regime scheduler and backfill support.

### `natural_gas_v1`

Path: `src/domains/natural_gas_v1/`

Variables: `TempAnom`, `HeatingDem`, `StorageDraw`, `PriceUp`.

Data sources:
- NOAA `api.weather.gov` for temperature observations.
- EIA API for weekly storage and Henry Hub price.

Cadence: daily. NG behaves meaningfully at daily cadence and was not moved to weekly.

Backfill state: 365 days completed.

### `corn_v1`

Path: `src/domains/corn_v1/`

Variables: `PlantingDelayed`, `DroughtIndex`, `YieldForecastDown`, `CornPriceUp`.

Data sources:
- USDA NASS QuickStats for planting, condition, yield.
- Yahoo Finance `ZC=F` for front-month futures.

Cadence: weekly. Agriculture was moved away from daily oversampling after evidence-geometry diagnostics showed daily records compress strongly into weekly states with very low entropy.

Current blocker: `NASS_API_KEY` is invalid. Get a new key from `https://quickstats.nass.usda.gov`, then run ZC backfill.

### `soybean_v1`

Path: `src/domains/soybean_v1/`

Variables: `PlantingDelayed`, `DroughtIndex`, `YieldForecastDown`, `SoyPriceUp`.

Data sources:
- USDA NASS QuickStats for planting, condition, yield.
- Yahoo Finance `ZS=F` for front-month futures.

Cadence: weekly. Same oversampling rationale as corn.

Current blocker: `NASS_API_KEY` is invalid. Get a new key from `https://quickstats.nass.usda.gov`, then run ZS backfill.

### `test_domain_v1`

Synthetic test domain for Level 1-3 learning, edge existence, population management, lineage, and paradigm-shift behavior.

---

## Engine State

### Stable variable identity

`src/engine/variable_identity.py` provides deterministic UUID generation:

```python
stable_variable_id(domain_module_id, variable_name)
```

Variable IDs are derived from domain name + variable name. This fixes the old restart/import mismatch where persisted evidence UUIDs did not match freshly imported domain variable UUIDs.

Compatibility:
- `EvidenceStore.migrate_variable_ids_by_position()` rewrites legacy records when assignment order and shape match current variables.
- Learning and evidence diagnostics also normalize legacy evidence when possible.
- `GET /v1/debug/evidence-geometry` reports `variable_id_match_ratio`, mismatch counts, and fallback usage.

### Learning

`LearningService` supports:
- hard observations
- missing observations
- soft evidence through `MissingnessType.SOFT_OBSERVED`
- log-likelihood scoring
- compatibility normalization for legacy evidence IDs

The core learning logic has not been redesigned.

### Edge and population evolution

`EdgeExistenceService` still updates edge existence using BIC-style with-vs-without-parent comparisons.

`PopulationManager`:
- scores active candidates
- prunes low scorers
- introduces add/remove variants
- tracks dominant candidate changes
- persists domain-level paradigm shift events

Known design limitation: parent candidate selection for variants still uses raw `log_score`, while some ranking uses BIC-corrected average score.

### Explore/exploit MI

`ExploreExploitService._empirical_mi` is now implemented. It is no longer a stub returning `0.0`.

Behavior covered by tests:
- empty/single/constant cases return zero
- independent variables return near zero
- perfectly correlated Booleans return positive MI, including 1 bit for 50/50 split
- symmetry
- missing records skipped
- soft observations handled by MAP value
- multi-valued variables supported

Integration into variant proposal remains limited; the service is implemented and tested, but not yet a major driver of ontology evolution.

### Persistence

SQLite stores:
- `evidence_records`
- `ontology_populations`
- `ontology_candidates`
- score history
- `paradigm_shifts`
- parameter tables for CPT counts

Important limitation: `ParameterStore` persistence is tied to learn/update cycles. It is not a continuously flushed WAL-style parameter stream.

---

## API State

FastAPI app: `src/engine/api/app.py`.

Domain keys:
- `mr` → `macro-regime-v1`
- `ng` → `natural-gas-v1`
- `zc` → `corn-v1`
- `zs` → `soybean-v1`

Core endpoints:
- `GET /health`
- `GET /runtime`
- `GET /v1/population/status?domain=`
- `GET /v1/population/candidates?domain=`
- `POST /v1/inference/query`
- `GET /v1/population/lineage/{candidate_id}?domain=`
- `GET /v1/population/shifts?domain=`
- `GET /v1/evidence/recent?domain=`
- `POST /v1/ingest/trigger?domain=`
- `POST /v1/ingest/backfill?domain=&days=`
- `GET /v1/debug/entropy?domain=`
- `GET /v1/debug/evidence-geometry?domain=`
- `GET /v1/debug/learning?domain=`
- `GET /v1/debug/structure?domain=`

Recent fixes:
- Cross-domain lineage fallback works. A candidate UUID can be resolved even if the requested/default domain is wrong.
- Domain-level paradigm shifts are persisted in `paradigm_shifts`.
- `GET /v1/population/shifts?domain=` returns chronological shift events.

---

## Frontend State

Frontend repo: sibling `epistemic-monitor`.

Current dashboard state:
- MR tab added as the first tab.
- `RegimeStatePanel` added for macro-regime state.
- `ParadigmShiftTimeline` wired to live `GET /v1/population/shifts?domain=` endpoint.
- Tooltips are working.
- Cross-domain candidate/lineage interactions use backend fallback behavior.
- Title changed to `PROBABILISTIC ONTOLOGY ENGINE`.
- Subtitle changed to `EPISTEMIC STATE MONITOR`.

Known limitation:
- Lineage timeline is still sparse because persisted shift history only accumulates going forward from the event-log implementation unless historical shifts are reconstructed.

---

## Environment

Required or useful variables:

```bash
EIA_API_KEY=...       # required for NG
FRED_API_KEY=...      # required for MR
NASS_API_KEY=...      # currently invalid; replace before ZC/ZS backfill
POE_DATA_DIR=.        # optional data directory
EVIDENCE_SCHEDULER_ENABLED=true|false
```

FRED note: keep ProtonVPN active when running MR ingestion/backfills. The FRED API works through VPN; without it, requests may fail due to IP blocking.

---

## Known Limitations

- `NASS_API_KEY` is invalid; ZC/ZS backfills are blocked until a new QuickStats key is issued.
- TemplateRules are not implemented. `_derive_admissible_edges` still admits broad all-pairs candidate edges.
- API regression coverage in a single `tests/integration/test_api.py` file is still not written, though many endpoint-specific integration tests exist.
- `ParameterStore` saves on learn/update cycles only.
- Inference aggregation still uses raw `log_score` weighting in places rather than the same BIC-corrected ranking used by population management.
- MR shift history is limited by backfill window and by when the shift event log began.
- Consider a 1095-day MR backfill to cover the 2022 tightening cycle more fully.

---

## Current Test Result

Current expected result:

```bash
.venv/bin/python -m pytest tests/ -v
# 183 passed
```

Warnings remain mostly from datetime deprecations and dependencies; they are non-fatal.
