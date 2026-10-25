# The domains and their variables

Every domain except art reads each variable from a measured number, as low,
middle or high: how far the number lies from the line the variable's name
describes, cut at half a unit of its own scale either side (REFACTOR_SPEC
D25). Art's variables are yes/no, mostly from testimony, and kept as
probabilities.

**`macro-regime-v1`**: `YieldCurveInverted`, `InflationShock`, `LiquidityStress`, `CreditSpreadStress`, `VolatilityShock`, `DollarStrength`, `EquityRiskOn`, `AIRiskOn`
— FRED series: `T10Y2Y`, `CPIAUCSL`, `WALCL`, `BAMLH0A0HYM2`, `VIXCLS`, `DEXUSEU`, `UNRATE`, `NASDAQCOM`

**`natural-gas-v1`**: `TempAnom`, `HeatingDem`, `StorageDraw`, `PriceUp`
— NOAA NCEI daily climate summaries (high and low at five airports, about four days late, so gas runs five days behind) + EIA storage/price

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

**`art_prestige_regime_v1`**: 25 art prestige regime variables (institutional, market, cultural), in `src/domains/art_prestige_regime_v1`.
— Fetched monthly where a series measures the variable (see `ingestion/pipeline.py` `MEASURES`); hand-labelled reports in `report_files/` cover the rest under the rules in `reports.py`. Unmeasured variables are MISSING.


Every domain's candidates also hold each signal's value last period (`X_prev`), as inputs only (REFACTOR_SPEC D19, D24). No domain gives hypotheses: the engine starts each with none and forms its own (D24).
