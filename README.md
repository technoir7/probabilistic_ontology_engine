# Probabilistic Ontology Engine

Backend for the Epistemic State Monitor: a probabilistic ontology engine for macro-financial regime analysis. The project is framed as an epistemic analysis tool, not a prediction engine. It maintains competing probabilistic ontology structures, learns from evidence, tracks edge uncertainty, and records paradigm shifts when the dominant explanatory structure changes.

## Current Flagship Domain

The flagship domain is **macro_regime_v1** (`mr`): a weekly macro-financial regime ontology sourced from FRED.

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

Macro regime evidence is weekly. A 730-day MR backfill has been run. A 1095-day backfill is the next useful expansion if you want to capture the full 2022 tightening cycle.

## Active Domains

- `mr` / `macro-regime-v1`: flagship weekly macro-financial regime domain using FRED.
- `ng` / `natural-gas-v1`: daily natural gas domain using NOAA + EIA. A 365-day backfill has been run.
- `zc` / `corn-v1`: partial weekly corn domain using USDA NASS + Yahoo Finance `ZC=F`.
- `zs` / `soybean-v1`: partial weekly soybean domain using USDA NASS + Yahoo Finance `ZS=F`.
- `test-domain-v1`: synthetic domain for learning and population tests.

Agriculture is weekly because evidence-geometry diagnostics showed daily corn/soy records were heavily oversampled and low-entropy.

ZC/ZS are partial because NASS access is blocked on the current non-VPN IP path. The key is valid; rerun ZC/ZS backfills with ProtonVPN Switzerland active.

## Narrative Export Workflow

The dashboard supports offline LLM interpretation without sending data to an LLM service from the app:

1. Open the dashboard and select `MR`, `NG`, `ZC`, or `ZS`.
2. Click `[ EXPORT SNAPSHOT ]`.
3. The browser downloads a `.txt` file containing an interpretation prompt plus structured JSON.
4. Paste that text into an LLM session for narrative interpretation.

The backend endpoint is:

```text
GET /v1/export/narrative-snapshot?domain=mr|ng|zc|zs
```

The exported regime state uses BN inference posteriors, not soft priors.

## Architecture

The engine has three belief levels:

```text
Level 3 - Structure:  population of candidate DAGs; dominant hypothesis and shifts
Level 2 - Edges:      edge existence probabilities updated from evidence
Level 1 - Parameters: CPT counts learned from hard, missing, and soft evidence
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
- `GET /v1/export/narrative-snapshot?domain=...`
- `GET /v1/debug/evidence-geometry?domain=...`
- `GET /v1/debug/learning?domain=...`
- `GET /v1/debug/structure?domain=...`

Paradigm shifts are persisted in the `paradigm_shifts` table and exposed through `/v1/population/shifts`. The frontend timeline reads this live endpoint.

## Frontend

The sibling `epistemic-monitor` frontend is wired to this API. Current UI state:
- MR tab is first.
- `RegimeStatePanel` is live.
- `[ EXPORT SNAPSHOT ]` is available on MR, NG, ZC, and ZS tabs.
- Export downloads prompt + JSON as a `.txt` file for offline LLM interpretation.
- `ParadigmShiftTimeline` reads the live shifts endpoint.
- Paradigm shift timeline height fix is applied.
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
NASS_API_KEY=...
EVIDENCE_SCHEDULER_ENABLED=true
POE_DATA_DIR=.
```

VPN requirement: ProtonVPN Switzerland must be active for both FRED and NASS API access. The current issue is provider/IP blocking, not invalid keys.

## Tests

Current expected result:

```bash
.venv/bin/python -m pytest tests/ -v
# 204 passed
```

See `SNAPSHOT.md` for the detailed current-state handoff and `NEXT.md` for the active priority queue.
