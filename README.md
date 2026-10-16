# Probabilistic Ontology Engine

Backend for the Epistemic State Monitor: a probabilistic ontology engine for macro-financial and geopolitical regime analysis. The project is framed as an epistemic analysis tool, not a prediction engine. It maintains competing probabilistic ontology structures, learns from evidence, tracks edge uncertainty, and records paradigm shifts when the dominant explanatory structure changes.

## Active Domains

Eleven domains are live and registered in the API:

| Key | Module ID | Cadence | Data Sources |
|-----|-----------|---------|-------------|
| `mr` | `macro-regime-v1` | Weekly | FRED |
| `ng` | `natural-gas-v1` | Daily | NOAA + EIA |
| `ai` | `ai-regime-v1` | Weekly | SEC EDGAR + yfinance + FRED |
| `sd` | `sovereign-debt-v1` | Weekly | FRED |
| `cc` | `credit-cycle-v1` | Weekly | FRED |
| `er` | `energy-regime-v1` | Weekly | yfinance + FRED |
| `lm` | `labor-market-v1` | Weekly | FRED |
| `cr` | `crypto-regime-v1` | Weekly | CoinGecko + yfinance + FRED |
| `gp` | `geopolitics-v1` | Weekly | GDELT + FRED |
| `sf` | `sf-urban-v1` | Weekly | SF Open Data + FRED |
| `art` | `art_prestige_regime_v1` | Monthly | GDELT news coverage, Art Institute of Chicago acquisitions, hand-labelled reports |

Most domains track eight Boolean variables across five seed candidate DAGs. The art domain tracks 25 Boolean variables across five seed candidate DAGs.

## Domain Variables

**`macro-regime-v1`**: `YieldCurveInverted`, `InflationShock`, `LiquidityStress`, `CreditSpreadStress`, `VolatilityShock`, `DollarStrength`, `EquityRiskOn`, `AIRiskOn`
— FRED series: `T10Y2Y`, `CPIAUCSL`, `WALCL`, `BAMLH0A0HYM2`, `VIXCLS`, `DEXUSEU`, `UNRATE`, `NASDAQCOM`

**`natural-gas-v1`**: `TempAnom`, `HeatingDem`, `StorageDraw`, `PriceUp`
— NOAA weather API + EIA storage/price

**`ai-regime-v1`**: `SemiconductorMomentum`, `MarketConcentrationExtreme`, `HyperscalerCapexAccelerating`, `TechValuationDetached`, `IPInvestmentRising`, `LaborProductivityImproving`, `BroadEconomicLift`, `AIRiskPremiumCompressed`
— SEC EDGAR capex; yfinance `^SOX`, `QQQ`, `RSP`, `^VIX`; FRED quarterly IP/productivity/GDP

**`sovereign-debt-v1`**: `USYieldSpiking`, `SpreadWidening`, `DollarStrengthening`, `FedBalanceSheetShrinking`, `EMStressElevated`, `FiscalDominanceRisk`, `CreditDefaultRisk`, `GlobalLiquidityContracting`
— FRED: `DGS10`, `BAMLH0A0HYM2`, `DEXUSEU`, `WALCL`, `DTWEXBGS`, `GFDEBTN`, `M2SL`

**`credit-cycle-v1`**: `HYSpreadElevated`, `LeveragedLoanStress`, `CorporateDefaultRisk`, `CreditImpulseNegative`, `BankLendingTightening`, `InvestmentGradeSpread`, `HighYieldIssuanceFalling`, `RefinancingStress`
— FRED: `BAMLH0A0HYM2`, `DRTSCILM`, `TOTCI`, `BAMLC0A0CM`, `DGS5`

**`energy-regime-v1`**: `OilPriceSurge`, `NatGasPriceSurge`, `EnergyEquityMomentum`, `OPECSupplyConstraint`, `RenewablesDisplacement`, `EnergyInflationPersistent`, `GeopoliticalRiskElevated`, `DemandDestructionRisk`
— yfinance: `CL=F`, `NG=F`, `XLE`, `ICLN`

**`labor-market-v1`**: `UnemploymentRising`, `WageInflationPersistent`, `JobOpeningsFalling`, `LayoffCycleBeginning`, `LaborProductivityWeak`, `ParticipationRateFalling`, `RealWageGrowthPositive`, `TightLaborMarket`
— FRED: `UNRATE`, `CES0500000003`, `JTSJOL`, `ICSA`, `PRS85006092`, `CIVPART`, `CPIAUCSL`

**`crypto-regime-v1`**: `BTCMomentumPositive`, `AltcoinSeasonActive`, `OnChainActivityElevated`, `StablecoinFlowPositive`, `CryptoVolatilityShock`, `RiskAssetCorrelation`, `NarrativeMomentum`, `DollarDebasementNarrative`
— CoinGecko (no key); yfinance `BTC-USD`, `QQQ`, `GLD`

**`geopolitics-v1`**: `ConflictIntensityElevated`, `TradeDisruptionRisk`, `SanctionsPressureElevated`, `DiplomaticTensionHigh`, `SupplyChainStress`, `CurrencyWarSignal`, `EnergyWeaponizationRisk`, `GlobalTradeVolumeWeak`
— GDELT (no key); FRED: `DCOILWTICO`, `PPIACO`, `DTWEXBGS`, `INDPRO`

**`sf-urban-v1`**: `TechHiringAccelerating`, `OfficeVacancyFalling`, `RetailClosureElevated`, `PermitActivityRising`, `CrimeIndexElevated`, `StartupFormationRising`, `FootTrafficRecovering`, `PopulationFlowPositive`
— SF Open Data: permits (`i98e-djp9`), crime (`wg3w-h783`), businesses (`g8m3-pdis`); FRED: `SANF806INFO`, `SANF806LEIH`, `SANF806NA` (SF-Oakland-Fremont MSA, monthly SA)

**`art_prestige_regime_v1`**: 25 art prestige regime variables (institutional, market, cultural) and five seed hypotheses, in `src/domains/art_prestige_regime_v1`.
— Fetched monthly where a series measures the variable (see `ingestion/pipeline.py` `MEASURES`); hand-labelled reports in `report_files/` cover the rest under the rules in `reports.py`. Unmeasured variables are MISSING.

## Architecture

The engine has three belief levels:

```
Level 3 - Structure:  population of candidate DAGs; dominant hypothesis and paradigm shifts
Level 2 - Edges:      edge existence probabilities updated from evidence
Level 1 - Parameters: CPT counts learned from hard, missing, and soft evidence
```

Core services:
- `LearningService`: CPT updates, soft evidence (`SOFT_OBSERVED`), likelihood scoring.
- `EdgeExistenceService`: BIC-style edge existence updates and pruning.
- `PopulationManager`: candidate scoring, pruning, mutation, paradigm-shift tracking.
- `InferenceService`: pgmpy-backed Bayesian inference.
- `ExploreExploitService`: empirical mutual information — implemented and tested, not yet used by the learning loop (REFACTOR_SPEC D3).

Variable identity is deterministic via `stable_variable_id(domain_module_id, variable_name)`, preserving evidence continuity across restarts.

Code layout (layers import downward only; enforced by `uv run lint-imports`):

```
api/        HTTP routers, response models, view logic
runtime/    domain registry, settings, ingest/backfill/scheduler
engine.py   the facade over services + stores
services/   learning, edge existence, population, inference (pure)
stores/     SQLite repositories, migrations/*.sql, one transaction per learning cycle
model/      CPTs, the candidate score, cadence, domain contract, errors
domains/    one package per domain + sources/ (shared FRED/yfinance clients, helpers)
```

Adding a domain: give its package a `DomainModule` (`domain.py`) and a
`source.open_source(env)`, then add one `DomainRegistration` in
`src/engine/runtime/registry.py`. Nothing else names domains.

## API

All routes accept a `?domain=` query parameter using the domain key (e.g., `mr`, `sf`, `art`):

```
GET  /v1/population/status
GET  /v1/population/candidates
POST /v1/inference/query
GET  /v1/population/lineage/{candidate_id}
GET  /v1/population/shifts
GET  /v1/evidence/recent
POST /v1/ingest/trigger
POST /v1/ingest/backfill?days=N             # needs Authorization: Bearer $POE_ADMIN_TOKEN
POST /v1/ingest/art/manual?path=...          # learn new report files; needs Authorization: Bearer $POE_ADMIN_TOKEN
POST /v1/ingest/art/rebuild?months=36        # forget art, relearn fetched months + reports (~3 min); admin token
GET  /v1/export/narrative-snapshot
GET  /v1/report/{domain}                     # read cached report (no LLM call)
POST /v1/report/{domain}/refresh             # regenerate if snapshot changed (Fireworks)
GET  /v1/debug/entropy
GET  /v1/debug/evidence-geometry
GET  /v1/debug/learning
GET  /v1/debug/structure
```

## Narrative Export Workflow

```
1. Open the dashboard, select any domain tab.
2. Click [ EXPORT SNAPSHOT ].
3. Browser downloads prompt + JSON state as a .txt file.
4. Paste into an LLM session for offline epistemic interpretation.
```

Exported regime state uses BN inference posteriors, not soft priors.

## Running

```bash
cd probabilistic_ontology_engine
uv sync            # creates .venv from uv.lock
uv run uvicorn src.engine.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Environment (`.env`):

```bash
FRED_API_KEY=...                    # required for MR, AI, SD, CC, ER, LM, CR, GP, SF
EIA_API_KEY=...                     # required for NG
FIREWORKS_API_KEY=...               # required for POST /v1/report/{domain}/refresh
EVIDENCE_SCHEDULER_ENABLED=true
POE_DATA_DIR=/data                  # Railway: persistent volume mount; default "." loses reports on redeploy
POE_ADMIN_TOKEN=...                 # enables backfill and the art routes; unset = those routes return 503
POE_CORS_ORIGINS=https://x.vercel.app,http://localhost:3000   # default "*"; read before .env loads, so set it in the real environment
```

No key required for SF Open Data, CoinGecko public endpoints, or GDELT. SEC EDGAR requires only a valid `User-Agent` header.

## Tests

```bash
# Standard suite (live tests excluded automatically; real HTTP is blocked):
uv run pytest

# Live tests only (hit real external APIs):
uv run pytest -m live

# Regenerate golden snapshots after an intentional behaviour change,
# then review the snapshot diff before committing:
POE_UPDATE_GOLDEN=1 uv run pytest tests/golden
```

`tests/golden/` pins engine, API, domain and calendar behaviour as committed
JSON snapshots; see `REFACTOR_SPEC.md` §7 Phase 0.

See `SNAPSHOT.md` for the full current-state handoff and `NEXT.md` for the active priority queue.
