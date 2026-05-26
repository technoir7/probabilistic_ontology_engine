# Probabilistic Ontology Engine

Backend for the Epistemic State Monitor. The engine maintains a population of competing probabilistic ontology structures, learns from evidence, tracks edge existence uncertainty, and records paradigm shifts when the dominant explanatory structure changes.

## Current Flagship Domain

The flagship domain is now **macro_regime_v1** (`mr`): a weekly macro-financial regime ontology sourced from FRED.

It tracks eight Boolean variables:
- `YieldCurveInverted`
- `InflationShock`
- `LiquidityStress`
- `CreditSpreadStress`
- `VolatilityShock`
- `DollarStrength`
- `EquityRiskOn`
- `AIRiskOn`

FRED series used:
- `T10Y2Y`
- `CPIAUCSL`
- `WALCL`
- `BAMLH0A0HYM2`
- `VIXCLS`
- `DEXUSEU`
- `UNRATE`
- `NASDAQCOM`

Macro regime evidence is weekly. A 730-day MR backfill has been run. Consider 1095 days if you want to capture the full 2022 tightening cycle.

**FRED access note:** FRED currently works via ProtonVPN. Keep the VPN active when running MR ingestion or backfills; the normal IP path is blocked.

## Other Domains

- `ng` / `natural-gas-v1`: daily natural gas domain using NOAA + EIA. A 365-day backfill has been run.
- `zc` / `corn-v1`: weekly corn domain using USDA NASS + Yahoo Finance `ZC=F`.
- `zs` / `soybean-v1`: weekly soybean domain using USDA NASS + Yahoo Finance `ZS=F`.
- `test-domain-v1`: synthetic domain for learning and population tests.

Agriculture is weekly because evidence-geometry diagnostics showed daily corn/soy records were heavily oversampled and low-entropy.

Current blocker: `NASS_API_KEY` is invalid. Get a new key from `https://quickstats.nass.usda.gov` before running ZC/ZS backfills.

## Architecture

The engine has three belief levels:

```text
Level 3 — Structure:  population of candidate DAGs; dominant hypothesis and shifts
Level 2 — Edges:      edge existence probabilities updated from evidence
Level 1 — Parameters: CPT counts learned from hard, missing, and soft evidence
```

Core services:
- `LearningService`: CPT updates, missing evidence, soft evidence, likelihood scoring.
- `EdgeExistenceService`: BIC-style edge existence updates and pruning.
- `PopulationManager`: candidate scoring, pruning, mutation, and paradigm-shift tracking.
- `InferenceService`: pgmpy-backed inference.
- `ExploreExploitService`: empirical mutual information is implemented and tested.

Variable identity is deterministic through `stable_variable_id(domain_module_id, variable_name)`, preserving evidence continuity across restarts.

## API

Primary routes:
- `GET /v1/population/status?domain=mr|ng|zc|zs`
- `GET /v1/population/candidates?domain=...`
- `POST /v1/inference/query`
- `GET /v1/population/lineage/{candidate_id}?domain=...`
- `GET /v1/population/shifts?domain=...`
- `GET /v1/evidence/recent?domain=...`
- `POST /v1/ingest/trigger?domain=...`
- `POST /v1/ingest/backfill?domain=...&days=...`
- `GET /v1/debug/evidence-geometry?domain=...`
- `GET /v1/debug/learning?domain=...`
- `GET /v1/debug/structure?domain=...`

Paradigm shifts are persisted in the `paradigm_shifts` table and exposed through `/v1/population/shifts`.

## Frontend

The sibling `epistemic-monitor` frontend is wired to this API. Current UI state:
- MR tab is first.
- `RegimeStatePanel` is live.
- `ParadigmShiftTimeline` reads the live shifts endpoint.
- Tooltips are working.
- Header title is `PROBABILISTIC ONTOLOGY ENGINE`.
- Subtitle is `EPISTEMIC STATE MONITOR`.

## Running

```bash
cd probabilistic_ontology_engine
source .venv/bin/activate
uvicorn src.engine.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Environment:

```bash
EIA_API_KEY=...
FRED_API_KEY=...
NASS_API_KEY=...      # replace current invalid key before ag backfills
EVIDENCE_SCHEDULER_ENABLED=true
POE_DATA_DIR=.
```

For MR ingestion/backfills, ProtonVPN must be active.

## Tests

Current expected result:

```bash
.venv/bin/python -m pytest tests/ -v
# 183 passed
```

See `SNAPSHOT.md` for the detailed current-state handoff and `NEXT.md` for the active priority queue.
