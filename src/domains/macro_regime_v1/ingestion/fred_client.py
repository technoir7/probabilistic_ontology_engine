"""
FREDClient — fetches macroeconomic data from api.stlouisfed.org (FRED API v1).

API key must be supplied via the FRED_API_KEY environment variable (or loaded
from .env by the caller).

Series fetched
--------------
T10Y2Y        Market Yield on U.S. Treasury Securities at 10-Year minus 2-Year
              Constant Maturity (percentage points, daily business days).
              Used for: YieldCurveInverted

CPIAUCSL      Consumer Price Index for All Urban Consumers: All Items
              (seasonally adjusted, monthly, index 1982-84=100).
              Used for: InflationShock (12-month YoY % change)

WALCL         Assets: Total Assets: Total Assets (Less Eliminations from
              Consolidation): Wednesday Level (weekly, USD billions).
              Used for: LiquidityStress (13-week % change)

BAMLH0A0HYM2  ICE BofA US High Yield Index Option-Adjusted Spread (%, daily).
              Used for: CreditSpreadStress (52-week rolling z-score)

VIXCLS        CBOE Volatility Index: VIX (daily, business days).
              Used for: VolatilityShock (vs rolling 90-day 75th percentile)

DEXUSEU       U.S. Dollars to Euro Spot Exchange Rate (daily, higher = stronger USD).
              Used for: DollarStrength (52-week rolling z-score)

UNRATE        Unemployment Rate (seasonally adjusted, monthly, percent).
              Used for: EquityRiskOn (3-month change direction)

NASDAQCOM     NASDAQ Composite Index (daily business days, index value).
              Used for: AIRiskOn (13-week return z-score vs historical)

FRED API endpoint
-----------------
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id={series_id}
    &api_key={key}
    &observation_start={YYYY-MM-DD}
    &observation_end={YYYY-MM-DD}
    &sort_order=desc
    &limit={n}
    &file_type=json

Missing values in FRED are returned as the string ".".

Error handling
--------------
- Raises IOError on HTTP failures or empty responses.
- Missing ("." valued) observations are silently skipped.
- If fewer observations are returned than needed, raises IOError.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Canonical FRED series IDs for this domain
FRED_SERIES = {
    "yield_curve":     "T10Y2Y",
    "cpi":             "CPIAUCSL",
    "fed_balance":     "WALCL",
    "hy_spread":       "BAMLH0A0HYM2",
    "vix":             "VIXCLS",
    "usd_eur":         "DEXUSEU",
    "unemployment":    "UNRATE",
    "nasdaq":          "NASDAQCOM",
}

# Observation windows (in days) needed per series to compute derived signals.
# These are padded by ~20% to survive holidays / publication lag.
FETCH_LOOKBACK_DAYS: dict[str, int] = {
    "T10Y2Y":        35,    # 5 weeks of daily data for weekly median
    "CPIAUCSL":      430,   # 14 months for 12m YoY + safety
    "WALCL":         140,   # 20 weeks for 13w % change + safety
    "BAMLH0A0HYM2":  400,   # 52+ weeks of daily for z-score
    "VIXCLS":        120,   # 90-day rolling percentile + safety
    "DEXUSEU":       400,   # 52+ weeks for z-score
    "UNRATE":        450,   # 15 months (12m mean + 3m delta + safety)
    "NASDAQCOM":     730,   # 2+ years for stable 13w return z-score
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FREDObservation:
    """A single FRED observation (date, value) pair."""
    obs_date: date
    value: float
    series_id: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class FREDClient:
    """
    Asynchronous client for api.stlouisfed.org macroeconomic series.

    Parameters
    ----------
    api_key : str
        FRED open-data API key.  Register free at https://fred.stlouisfed.org/
    client : httpx.AsyncClient, optional
        Injected HTTP client for testing.  If provided, the caller owns it.
    timeout : float
        Request timeout in seconds.  Default 30.
    """

    def __init__(
        self,
        api_key: str,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY is required but not set")
        self._api_key = api_key
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "FREDClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_series(
        self,
        series_id: str,
        end_date: Optional[date] = None,
        start_date: Optional[date] = None,
        limit: int = 500,
    ) -> list[FREDObservation]:
        """
        Fetch observations for a single FRED series.

        Parameters
        ----------
        series_id : str
            FRED series identifier (e.g. "T10Y2Y").
        end_date : date, optional
            Observation end date.  Defaults to today.
        start_date : date, optional
            Observation start date.  If omitted, derived from
            FETCH_LOOKBACK_DAYS or defaults to 2 years back.
        limit : int
            Maximum observations to request.

        Returns
        -------
        list[FREDObservation]
            Observations sorted newest-first, with "." values excluded.

        Raises
        ------
        IOError
            On HTTP failure, empty response, or no valid observations.
        """
        if end_date is None:
            from datetime import datetime, timezone
            end_date = datetime.now(timezone.utc).date()

        if start_date is None:
            lookback = FETCH_LOOKBACK_DAYS.get(series_id, 400)
            start_date = end_date - timedelta(days=lookback)

        params: dict = {
            "series_id":          series_id,
            "api_key":            self._api_key,
            "file_type":          "json",
            "sort_order":         "desc",
            "limit":              limit,
            "observation_start":  start_date.isoformat(),
            "observation_end":    end_date.isoformat(),
        }

        try:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise IOError(
                f"FRED API HTTP {exc.response.status_code} for {series_id}"
            ) from exc
        except Exception as exc:
            raise IOError(
                f"FRED API request failed for {series_id}: {exc}"
            ) from exc

        raw_observations: list[dict] = body.get("observations", [])
        if not raw_observations:
            raise IOError(
                f"FRED returned empty observations array for {series_id} "
                f"({start_date} to {end_date})"
            )

        result: list[FREDObservation] = []
        for obs in raw_observations:
            raw_value = obs.get("value", ".")
            if raw_value == "." or raw_value is None:
                continue  # skip missing values
            try:
                value = float(raw_value)
            except (ValueError, TypeError):
                continue
            try:
                obs_date = date.fromisoformat(str(obs.get("date", ""))[:10])
            except ValueError:
                continue
            result.append(FREDObservation(
                obs_date=obs_date,
                value=value,
                series_id=series_id,
            ))

        if not result:
            raise IOError(
                f"FRED returned no valid (non-missing) observations for {series_id} "
                f"({start_date} to {end_date}). "
                f"All {len(raw_observations)} rows were missing (\".\")."
            )

        # Ensure newest-first ordering
        result.sort(key=lambda o: o.obs_date, reverse=True)
        logger.debug(
            "FRED %s: %d observations fetched (newest: %s, oldest: %s)",
            series_id, len(result),
            result[0].obs_date, result[-1].obs_date,
        )
        return result

    async def fetch_all_series(
        self,
        end_date: Optional[date] = None,
    ) -> dict[str, list[FREDObservation]]:
        """
        Fetch all domain series concurrently for the target week.

        Returns a dict mapping series_id → list of FREDObservation,
        newest-first.  Series that fail are logged and returned as empty
        lists to allow partial snapshot construction.
        """
        import asyncio

        from datetime import datetime, timezone
        if end_date is None:
            end_date = datetime.now(timezone.utc).date()

        series_ids = list(FRED_SERIES.values())

        async def _safe_fetch(sid: str) -> tuple[str, list[FREDObservation]]:
            try:
                obs = await self.fetch_series(sid, end_date=end_date)
                return sid, obs
            except IOError as exc:
                logger.warning("FRED fetch failed for %s: %s", sid, exc)
                return sid, []

        results = await asyncio.gather(*[_safe_fetch(sid) for sid in series_ids])
        return dict(results)
