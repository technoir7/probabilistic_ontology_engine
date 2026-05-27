# Codebase Snapshot - 2026-05-27

Current handoff snapshot for `probabilistic_ontology_engine`. This is a state document, not marketing copy.

---

## Status

- Backend: FastAPI + Pydantic v2 probabilistic ontology engine.
- Frontend: Next.js dashboard in sibling `epistemic-monitor`, wired to live backend APIs.
- Current test status: **370 passed** (6 live tests deselected) with `.venv/bin/python -m pytest tests/ -v`.
- Live tests run separately: `.venv/bin/python -m pytest tests/ -v -m live`.
- Primary use: epistemic analysis for macro-financial regime interpretation, not prediction.
- Active dashboard domains: MR, NG, AI, SD, CC, ER, LM, CR, GP, SF (10 total).
- Corn (`zc`) and soybean (`zs`) domains have been removed and replaced by SD, CC, ER, LM.

---

## Domains

### `macro_regime_v1` — key `mr`

Path: `src/domains/macro_regime_v1/`

Purpose: weekly macro-financial regime ontology. Flagship domain for engine development.

Cadence: weekly. WALCL is weekly; CPI/UNRATE are monthly; daily market series treated as weekly regime signals.

Data: FRED API (`FRED_API_KEY`).

Variables: `YieldCurveInverted`, `InflationShock`, `LiquidityStress`, `CreditSpreadStress`, `VolatilityShock`, `DollarStrength`, `EquityRiskOn`, `AIRiskOn`.

FRED series: `T10Y2Y`, `CPIAUCSL`, `WALCL`, `BAMLH0A0HYM2`, `VIXCLS`, `DEXUSEU`, `UNRATE`, `NASDAQCOM`.

Seed candidates: `T_monetary`, `T_credit`, `T_ai_boom`, `T_recession`, `T_null`.

Backfill: 730-day MR backfill completed. A 1095-day backfill would capture the full 2022 tightening cycle.

---

### `natural_gas_v1` — key `ng`

Path: `src/domains/natural_gas_v1/`

Cadence: daily. NG behaves meaningfully at daily cadence.

Data: NOAA `api.weather.gov` for temperature; EIA API (`EIA_API_KEY`) for weekly storage and Henry Hub price.

Variables: `TempAnom`, `HeatingDem`, `StorageDraw`, `PriceUp`.

Backfill: 365-day backfill completed.

---

### `ai_regime_v1` — key `ai`

Path: `src/domains/ai_regime_v1/`

Cadence: weekly.

Data:
- SEC EDGAR (`data.sec.gov/api/xbrl/companyfacts`) for hyperscaler capex — no API key required, but User-Agent header required.
- yfinance: `^SOX` (Philadelphia Semiconductor Index), `QQQ`, `RSP`, `^VIX`.
- FRED: `Y033RC1Q027SBEA` (IP investment, quarterly), `PRS85006092` (labor productivity, quarterly), `A191RL1Q225SBEA` (real GDP growth, quarterly).

Variables: `SemiconductorMomentum`, `MarketConcentrationExtreme`, `HyperscalerCapexAccelerating`, `TechValuationDetached`, `IPInvestmentRising`, `LaborProductivityImproving`, `BroadEconomicLift`, `AIRiskPremiumCompressed`.

Seed candidates: `InfrastructureBuildout`, `BubbleDetachment`, `WinnerTakeAll`, `ProductivityRegime`, `Null`.

---

### `sovereign_debt_v1` — key `sd`

Path: `src/domains/sovereign_debt_v1/`

Cadence: weekly.

Data: FRED (`DGS10`, `BAMLH0A0HYM2`, `DEXUSEU`, `WALCL`, `DTWEXBGS`, `GFDEBTN`, `M2SL`).

Variables: `USYieldSpiking`, `SpreadWidening`, `DollarStrengthening`, `FedBalanceSheetShrinking`, `EMStressElevated`, `FiscalDominanceRisk`, `CreditDefaultRisk`, `GlobalLiquidityContracting`.

Seed candidates: `USFiscalStress`, `DollarDominanceErosion`, `EMContagion`, `GlobalLiquidityCrunch`, `Null`.

---

### `credit_cycle_v1` — key `cc`

Path: `src/domains/credit_cycle_v1/`

Cadence: weekly.

Data: FRED (`BAMLH0A0HYM2`, `DRTSCILM`, `TOTCI`, `BAMLC0A0CM`, `DGS5`).

Variables: `HYSpreadElevated`, `LeveragedLoanStress`, `CorporateDefaultRisk`, `CreditImpulseNegative`, `BankLendingTightening`, `InvestmentGradeSpread`, `HighYieldIssuanceFalling`, `RefinancingStress`.

Seed candidates: `MonetaryTightening`, `DefaultCycle`, `LiquidityWithdrawal`, `CreditNormalization`, `Null`.

---

### `energy_regime_v1` — key `er`

Path: `src/domains/energy_regime_v1/`

Cadence: weekly.

Data: yfinance (`CL=F`, `NG=F`, `XLE`, `ICLN`) + FRED.

Variables: `OilPriceSurge`, `NatGasPriceSurge`, `EnergyEquityMomentum`, `OPECSupplyConstraint`, `RenewablesDisplacement`, `EnergyInflationPersistent`, `GeopoliticalRiskElevated`, `DemandDestructionRisk`.

Seed candidates: `SupplyShock`, `DemandDriven`, `GeopoliticalPremium`, `RenewablesTransition`, `Null`.

---

### `labor_market_v1` — key `lm`

Path: `src/domains/labor_market_v1/`

Cadence: weekly.

Data: FRED (`UNRATE`, `CES0500000003`, `JTSJOL`, `ICSA`, `PRS85006092`, `CIVPART`, `CPIAUCSL`).

Variables: `UnemploymentRising`, `WageInflationPersistent`, `JobOpeningsFalling`, `LayoffCycleBeginning`, `LaborProductivityWeak`, `ParticipationRateFalling`, `RealWageGrowthPositive`, `TightLaborMarket`.

Seed candidates: `LaborTightening`, `LayoffCycle`, `StructuralShift`, `WagePriceSpiral`, `Null`.

---

### `crypto_regime_v1` — key `cr`

Path: `src/domains/crypto_regime_v1/`

Cadence: weekly.

Data: CoinGecko (`/coins/bitcoin/market_chart`, `/coins/ethereum/market_chart`, `/global` for BTC dominance) + yfinance (`BTC-USD`, `QQQ`, `GLD`) + FRED. No API key required for CoinGecko public endpoints.

Variables: `BTCMomentumPositive`, `AltcoinSeasonActive`, `OnChainActivityElevated`, `StablecoinFlowPositive`, `CryptoVolatilityShock`, `RiskAssetCorrelation`, `NarrativeMomentum`, `DollarDebasementNarrative`.

Seed candidates: `LiquidityOverflow`, `DigitalGold`, `SpeculativeMania`, `UtilityAdoption`, `Null`.

---

### `geopolitics_v1` — key `gp`

Path: `src/domains/geopolitics_v1/`

Cadence: weekly.

Data: GDELT (`api.gdeltproject.org/api/v2/doc/doc`) + FRED (`DCOILWTICO`, `PPIACO`, `DTWEXBGS`, `INDPRO`). No API key required for GDELT.

Variables: `ConflictIntensityElevated`, `TradeDisruptionRisk`, `SanctionsPressureElevated`, `DiplomaticTensionHigh`, `SupplyChainStress`, `CurrencyWarSignal`, `EnergyWeaponizationRisk`, `GlobalTradeVolumeWeak`.

Seed candidates: `GreatPowerCompetition`, `ResourceConflict`, `Deglobalization`, `RegionalInstability`, `Null`.

---

### `sf_urban_v1` — key `sf`

Path: `src/domains/sf_urban_v1/`

Cadence: weekly.

Data:
- FRED (monthly, seasonally adjusted, SF-Oakland-Fremont MSA): `SANF806INFO` (information sector employment), `SANF806LEIH` (leisure and hospitality), `SANF806NA` (total nonfarm). Previous series IDs (`SMU0641820*`) were invalid and returned HTTP 400; replaced 2026-05-27.
- SF Open Data (Socrata): building permits (`i98e-djp9.json`), police incidents (`wg3w-h783.json`), business registrations (`g8m3-pdis.json`). The business registrations endpoint was broken by wrong column names (`lic_start_dt` / `lic_end_dt` do not exist); corrected to `location_start_date` / `location_end_date` with ISO datetime filter syntax.

Variables: `TechHiringAccelerating`, `OfficeVacancyFalling`, `RetailClosureElevated`, `PermitActivityRising`, `CrimeIndexElevated`, `StartupFormationRising`, `FootTrafficRecovering`, `PopulationFlowPositive`.

Seed candidates: `TechRebound`, `StructuralDecline`, `BifurcatedRecovery`, `BottomFormation`, `Null`.

---

### `test_domain_v1`

Synthetic test domain for Level 1–3 learning, edge existence, population management, lineage, and paradigm-shift behavior.

---

## Engine State

### Stable variable identity

`src/engine/variable_identity.py` provides deterministic UUID generation:

```python
stable_variable_id(domain_module_id, variable_name)
```

Variable IDs are derived from domain name + variable name, preserving evidence continuity across restarts.

Compatibility:
- `EvidenceStore.migrate_variable_ids_by_position()` rewrites legacy records when assignment order and shape match current variables.
- `GET /v1/debug/evidence-geometry` reports `variable_id_match_ratio`, mismatch counts, and fallback usage.

### Learning

`LearningService` supports hard observations, missing observations, and soft evidence via `MissingnessType.SOFT_OBSERVED`. Log-likelihood scoring and compatibility normalization for legacy evidence IDs are implemented.

### Edge and population evolution

`EdgeExistenceService` updates edge existence with BIC-style with-vs-without-parent comparisons.

`PopulationManager`: scores active candidates, prunes low scorers, introduces add/remove variants, tracks dominant candidate changes, persists domain-level paradigm shift events.

Known design limitation: parent candidate selection for variants still uses raw `log_score`; some ranking uses BIC-corrected average score.

### Explore/exploit MI

`ExploreExploitService._empirical_mi` is implemented. Behavior is covered by tests.

Integration into variant proposal remains limited; the service is implemented and tested, but not yet a major driver of ontology evolution.

### Persistence

SQLite stores: `evidence_records`, `ontology_populations`, `ontology_candidates`, score history, `paradigm_shifts`, parameter tables for CPT counts.

`ParameterStore` persistence is tied to learn/update cycles, not continuously flushed.

---

## API State

FastAPI app: `src/engine/api/app.py`.

Domain keys:
- `mr` → `macro-regime-v1`
- `ng` → `natural-gas-v1`
- `ai` → `ai-regime-v1`
- `sd` → `sovereign-debt-v1`
- `cc` → `credit-cycle-v1`
- `er` → `energy-regime-v1`
- `lm` → `labor-market-v1`
- `cr` → `crypto-regime-v1`
- `gp` → `geopolitics-v1`
- `sf` → `sf-urban-v1`

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
- `GET /v1/export/narrative-snapshot?domain=`
- `GET /v1/debug/entropy?domain=`
- `GET /v1/debug/evidence-geometry?domain=`
- `GET /v1/debug/learning?domain=`
- `GET /v1/debug/structure?domain=`

---

## Frontend State

Frontend repo: sibling `epistemic-monitor`.

Current dashboard state:
- All 10 domain tabs are active: MR, NG, AI, SD, CC, ER, LM, CR, GP, SF.
- `RegimeStatePanel` for macro-regime state.
- `[ EXPORT SNAPSHOT ]` on all domain tabs.
- Export downloads a `.txt` file containing an interpretation prompt plus JSON for offline LLM analysis.
- `ParadigmShiftTimeline` wired to live `GET /v1/population/shifts?domain=` endpoint.
- Title: `PROBABILISTIC ONTOLOGY ENGINE`. Subtitle: `EPISTEMIC STATE MONITOR`.

Known frontend limitation: lineage/shift history is sparse until longer backfills accumulate more transitions.

---

## Environment

Required variables:

```bash
FRED_API_KEY=...     # required for MR, AI, SD, CC, ER, LM, CR, GP, SF
EIA_API_KEY=...      # required for NG
POE_DATA_DIR=.       # optional data directory
EVIDENCE_SCHEDULER_ENABLED=true|false
```

No API key required: SF Open Data (Socrata), CoinGecko (public endpoints), GDELT.

SEC EDGAR requires a `User-Agent` header identifying the application; no API key.

---

## Live Tests

Live integration tests (hitting real external APIs) are marked `@pytest.mark.live` and excluded from the standard run:

```bash
# Standard run (live tests excluded automatically):
.venv/bin/python -m pytest tests/ -v

# Live tests only:
.venv/bin/python -m pytest tests/ -v -m live
```

Current live test coverage: `tests/integration/test_sf_urban_live.py` (6 tests — FRED series SANF806INFO/SANF806LEIH/SANF806NA + SF Gov permits/crime/businesses).

---

## Known Limitations

- `TemplateRules` not implemented in `_derive_admissible_edges` — still admits broad all-pairs candidate edges.
- No consolidated API regression file (`tests/integration/test_api.py` not written).
- `ParameterStore` saves on learn/update cycles only.
- Inference aggregation uses raw `log_score` in places rather than BIC-corrected ranking.
- Shift history is limited by backfill window and by when the shift event log began.
- Inline LLM interpretation is not built into the dashboard; offline export workflow is the current path.

---

## Current Test Result

```bash
.venv/bin/python -m pytest tests/ -v
# 370 passed, 6 deselected (live)
```

Warnings are non-fatal datetime deprecations from dependencies.
