"""
FREDClient — credit-cycle-v1 FRED series fetcher.

Series fetched
--------------
BAMLH0A0HYM2  ICE BofA US High Yield OAS (daily, %)
              Used for: HYSpreadElevated (z-score), CorporateDefaultRisk (level),
                        HighYieldIssuanceFalling (3-month momentum)

DRTSCILM      Net % of Domestic Banks Tightening C&I Loan Standards (quarterly)
              Used for: LeveragedLoanStress (z-score), BankLendingTightening (z-score)

TOTCI         Commercial and Industrial Loans, All Commercial Banks (weekly, billions)
              Used for: CreditImpulseNegative (3-month growth rate)

BAMLC0A0CM    ICE BofA US Corporate Index OAS — Investment Grade (daily, %)
              Used for: InvestmentGradeSpread (z-score)

DGS5          5-Year Treasury Constant Maturity Rate (daily, %)
              Used for: RefinancingStress (composite with BAMLH0A0HYM2)

The client itself is shared (domains/sources/fred.py); this module only says
which series credit-cycle-v1 reads.
"""
from __future__ import annotations

from ...sources.fred import FREDClient as _SharedFREDClient
from ...sources.fred import FREDObservation, FredHTTPError

__all__ = ["FRED_SERIES", "FETCH_LOOKBACK_DAYS", "FREDClient", "FREDObservation", "FredHTTPError"]

FRED_SERIES: dict[str, str] = {
    "hy_spread":    "BAMLH0A0HYM2",
    "bank_lending": "DRTSCILM",
    "total_credit": "TOTCI",
    "ig_spread":    "BAMLC0A0CM",
    "dgs5":         "DGS5",
}

FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "BAMLH0A0HYM2": 400,   # 52+ weeks daily for z-score and level
    "DRTSCILM":     1500,  # ~4 years quarterly for z-score
    "TOTCI":        180,   # 6 months for 3m growth rate
    "BAMLC0A0CM":   400,   # 52+ weeks daily for z-score
    "DGS5":         400,   # 52+ weeks daily for composite
}


class FREDClient(_SharedFREDClient):
    SERIES = FRED_SERIES
    LOOKBACK_DAYS = FETCH_LOOKBACK_DAYS
    DEFAULT_LOOKBACK_DAYS = 400
