"""
AIRegimeFREDClient — FRED data for IP investment, productivity and GDP.

This module re-exports the base FREDClient and FREDObservation from
macro_regime_v1 (they are domain-agnostic utilities) and defines the
ai-regime-specific FRED series constants.

FRED series used
----------------
Y033RC1Q027SBEA  (quarterly, SA)
    Business Fixed Investment: Intellectual Property Products
    (billions of chained 2017 dollars)
    Used for: IPInvestmentRising
    Signal: 4-quarter growth rate vs historical median

PRS85006092  (quarterly, SA)
    Nonfarm Business Sector: Real Output Per Hour of All Persons
    (index 2012=100)
    Used for: LaborProductivityImproving
    Signal: year-over-year % change

A191RL1Q225SBEA  (quarterly, SA)
    Real Gross Domestic Product, Percent Change from Preceding Period
    (already an annualised growth rate, percent)
    Used for: BroadEconomicLift
    Signal: latest reading vs 2.5% threshold

The FREDClient.fetch_series() method is used directly with these series
IDs.  No domain-specific client wrapping is needed; the pipeline calls
fetch_series() once per series.

Missing / stale data handling
------------------------------
All three series publish quarterly.  The pipeline fetches 5+ years of
history to ensure enough data for IQR/median computations.  If fewer
observations are returned than required, the signal falls back to 0.0
(P = 0.50, maximum uncertainty).
"""
from __future__ import annotations

# Re-export the base client and observation type for convenience
from ...macro_regime_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
)

# ---------------------------------------------------------------------------
# AI regime FRED series constants
# ---------------------------------------------------------------------------

AI_FRED_SERIES: dict[str, str] = {
    "ip_investment":   "Y033RC1Q027SBEA",   # IP fixed investment (quarterly)
    "labor_prod":      "PRS85006092",        # Labor productivity (quarterly)
    "gdp_growth":      "A191RL1Q225SBEA",    # Real GDP growth rate (quarterly)
}

# Observation windows (calendar days) needed per series.
# Padded ~30% for quarterly series (publication lag, gaps).
AI_FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "Y033RC1Q027SBEA":   2200,   # ~6 years for robust median/IQR
    "PRS85006092":       2200,   # ~6 years for YoY + distribution
    "A191RL1Q225SBEA":   2200,   # ~6 years for distribution
}

# Minimum observations required before computing a signal
AI_MIN_OBS: dict[str, int] = {
    "Y033RC1Q027SBEA":  8,    # 8 quarters (2 years) for 4q growth + comparison
    "PRS85006092":      8,    # 8 quarters for YoY + distribution
    "A191RL1Q225SBEA":  4,    # 4 quarters minimum (GDP is already a growth rate)
}

__all__ = [
    "FREDClient",
    "FREDObservation",
    "AI_FRED_SERIES",
    "AI_FETCH_LOOKBACK_DAYS",
    "AI_MIN_OBS",
]
