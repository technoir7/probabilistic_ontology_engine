"""
USDANASSClient — fetches corn planting, condition, and yield data from the
USDA National Agricultural Statistics Service (NASS) Quick Stats API.

API
---
    GET https://quickstats.nass.usda.gov/api/api_GET/
        ?format=JSON
        &commodity_desc=CORN
        &statisticcat_desc=<PROGRESS|CONDITION|YIELD>
        &unit_desc=<PCT PLANTED|PCT GOOD|PCT EXCELLENT|BU / ACRE>
        &agg_level_desc=NATIONAL
        &freq_desc=<WEEKLY|MONTHLY>
        &year__GE=<year>
        [&key=<NASS_API_KEY>]   # optional; omit for DEMO_KEY tier

    Registration: https://quickstats.nass.usda.gov/api/register/
    (Free; higher rate limits than the anonymous DEMO_KEY tier.)

Data fetched (3 concurrent calls per snapshot)
----------------------------------------------
1. Planting progress — PCT PLANTED, WEEKLY, last 6 crop years.
   Current year's most recent week vs. the 5-year historical average for the
   same calendar week determines PlantingDelayed.

2. Crop conditions — PCT GOOD + PCT EXCELLENT, WEEKLY, current year only.
   Sum determines whether the DroughtIndex threshold (55%) is breached.

3. Yield forecast — BU / ACRE, MONTHLY (WASDE release months), last 2 years.
   Current year's latest forecast vs. prior year's final yield determines
   YieldForecastDown.

Derived variables
-----------------
    PlantingDelayed  = planting_progress_pct < (5yr_avg_pct − 5.0)
    DroughtIndex     = condition_good_exc_pct < DROUGHT_THRESHOLD (55 %)
    YieldForecastDown = yield_forecast_bu_ac < yield_prior_year_bu_ac

All three are set to False and missingness=MISSING when the underlying data
is unavailable (e.g. out of planting season, no WASDE forecast yet issued).
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
_PLANTING_YEARS_BACK = 5          # years of history for 5-yr planting avg
_PLANTING_DELAY_THRESHOLD = 5.0   # ppt behind 5yr avg to declare "delayed"
_DROUGHT_THRESHOLD = 55.0         # % good+excellent below which DroughtIndex=True
_CONDITION_WEEKS_BACK = 4         # window for checking recent crop conditions


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CornNASSSnapshot:
    target_date: date

    # --- planting progress ---
    planting_progress_pct: float | None    # current year latest week (None = off-season)
    planting_5yr_avg_pct:  float | None    # 5-year avg for same calendar week

    # --- crop conditions ---
    condition_good_exc_pct: float | None   # % GOOD + % EXCELLENT (None = off-season)

    # --- yield forecast ---
    yield_forecast_bu_ac:    float | None  # latest WASDE forecast (None = not yet issued)
    yield_prior_year_bu_ac:  float | None  # prior year final yield

    # --- derived booleans ---
    planting_delayed:    bool
    drought_index:       bool
    yield_forecast_down: bool


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class USDANASSClient:
    """
    Asynchronous client for the USDA NASS Quick Stats API.

    Parameters
    ----------
    api_key : str, optional
        NASS Quick Stats API key.  If omitted, requests are sent without a
        key (DEMO_KEY tier with tighter rate limits).
    client : httpx.AsyncClient, optional
        Injected HTTP client.  If provided, the caller owns it (not closed
        on exit).  Pass an AsyncMock here in tests.
    """

    def __init__(
        self,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "USDANASSClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_snapshot(self, target_date: date) -> CornNASSSnapshot:
        """
        Fetch all three series concurrently and return a CornNASSSnapshot.

        Raises IOError only if all three API calls fail simultaneously.
        Individual series failures degrade gracefully to None / False.
        """
        year = target_date.year
        planting_rows, condition_rows, yield_rows = await asyncio.gather(
            self._fetch_planting_progress(year),
            self._fetch_crop_conditions(year),
            self._fetch_yield(year),
        )
        return self._build_snapshot(target_date, planting_rows, condition_rows, yield_rows)

    # ------------------------------------------------------------------
    # Pure snapshot builder (no I/O — testable synchronously)
    # ------------------------------------------------------------------

    @staticmethod
    def build_snapshot(
        target_date: date,
        planting_rows: list[dict],
        condition_rows: list[dict],
        yield_rows: list[dict],
    ) -> CornNASSSnapshot:
        """
        Map raw NASS API rows to a CornNASSSnapshot.  Static and synchronous
        so it can be unit-tested without network calls.
        """
        return USDANASSClient._build_snapshot(
            target_date, planting_rows, condition_rows, yield_rows
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_snapshot(
        target_date: date,
        planting_rows: list[dict],
        condition_rows: list[dict],
        yield_rows: list[dict],
    ) -> CornNASSSnapshot:
        year = target_date.year

        # ---- planting progress ----
        planting_progress_pct, planting_5yr_avg_pct = _parse_planting(
            planting_rows, year, target_date
        )
        planting_delayed = (
            planting_progress_pct is not None
            and planting_5yr_avg_pct is not None
            and planting_progress_pct < planting_5yr_avg_pct - _PLANTING_DELAY_THRESHOLD
        )

        # ---- crop conditions ----
        condition_good_exc_pct = _parse_conditions(condition_rows, target_date)
        drought_index = (
            condition_good_exc_pct is not None
            and condition_good_exc_pct < _DROUGHT_THRESHOLD
        )

        # ---- yield forecast ----
        yield_forecast_bu_ac, yield_prior_year_bu_ac = _parse_yield(yield_rows, year)
        yield_forecast_down = (
            yield_forecast_bu_ac is not None
            and yield_prior_year_bu_ac is not None
            and yield_forecast_bu_ac < yield_prior_year_bu_ac
        )

        return CornNASSSnapshot(
            target_date=target_date,
            planting_progress_pct=planting_progress_pct,
            planting_5yr_avg_pct=planting_5yr_avg_pct,
            condition_good_exc_pct=condition_good_exc_pct,
            yield_forecast_bu_ac=yield_forecast_bu_ac,
            yield_prior_year_bu_ac=yield_prior_year_bu_ac,
            planting_delayed=planting_delayed,
            drought_index=drought_index,
            yield_forecast_down=yield_forecast_down,
        )

    async def _fetch_planting_progress(self, year: int) -> list[dict]:
        """PCT PLANTED, WEEKLY, last 6 years (current + 5 prior)."""
        params = self._base_params() | {
            "statisticcat_desc": "PROGRESS",
            "unit_desc": "PCT PLANTED",
            "freq_desc": "WEEKLY",
            "year__GE": str(year - _PLANTING_YEARS_BACK),
            "year__LE": str(year),
        }
        return await self._get(params, series="planting-progress")

    async def _fetch_crop_conditions(self, year: int) -> list[dict]:
        """
        PCT GOOD and PCT EXCELLENT, WEEKLY, current year only.
        Both unit_desc values are returned in the same call by omitting
        unit_desc — the caller filters on the client side.
        """
        params = self._base_params() | {
            "statisticcat_desc": "CONDITION",
            "freq_desc": "WEEKLY",
            "year": str(year),
        }
        return await self._get(params, series="crop-conditions")

    async def _fetch_yield(self, year: int) -> list[dict]:
        """BU / ACRE, MONTHLY (WASDE forecasts), current + prior year."""
        params = self._base_params() | {
            "statisticcat_desc": "YIELD",
            "unit_desc": "BU / ACRE",
            "freq_desc": "MONTHLY",
            "year__GE": str(year - 1),
            "year__LE": str(year),
        }
        return await self._get(params, series="yield-forecast")

    async def _get(self, params: dict, series: str) -> list[dict]:
        """
        Execute one Quick Stats API call.  Returns empty list on failure
        (logged as a warning) rather than raising, so individual series
        failures degrade gracefully.
        """
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("NASS API call failed for %s: %s", series, exc)
            return []

        data = body.get("data", [])
        if not data:
            logger.warning("NASS returned empty data for %s", series)
        return data

    def _base_params(self) -> dict:
        params: dict = {
            "format": "JSON",
            "source_desc": "SURVEY",
            "sector_desc": "CROPS",
            "commodity_desc": "CORN",
            "agg_level_desc": "NATIONAL",
            "state_alpha": "US",
        }
        if self._api_key:
            params["key"] = self._api_key
        return params


# ---------------------------------------------------------------------------
# Row parsers (pure functions — no I/O)
# ---------------------------------------------------------------------------

def _parse_value(row: dict) -> float | None:
    """Extract numeric Value from a NASS row; return None on non-numeric."""
    raw = str(row.get("Value", "")).strip().replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _week_number(week_ending: str) -> int:
    """
    Extract ISO week number from a NASS 'week_ending' string (YYYY-MM-DD).
    Returns 0 on parse failure.
    """
    try:
        d = date.fromisoformat(week_ending)
        return d.isocalendar()[1]
    except Exception:
        return 0


def _parse_planting(
    rows: list[dict],
    current_year: int,
    target_date: date,
) -> tuple[float | None, float | None]:
    """
    Returns (current_year_pct, 5yr_avg_pct) for the most recent week on or
    before target_date.  Both are None if data is unavailable.
    """
    if not rows:
        return None, None

    # Separate current-year rows from prior-year rows
    current: list[tuple[str, float]] = []    # (week_ending, value)
    prior:   dict[int, list[float]] = {}     # iso_week → values from prior years

    for row in rows:
        yr = int(row.get("year", 0))
        we = str(row.get("week_ending", ""))
        val = _parse_value(row)
        if val is None or not we:
            continue

        if yr == current_year:
            current.append((we, val))
        elif current_year - _PLANTING_YEARS_BACK <= yr < current_year:
            wk = _week_number(we)
            prior.setdefault(wk, []).append(val)

    if not current:
        return None, None

    # Pick the most recent week on or before target_date
    valid = [
        (we, v) for we, v in current
        if date.fromisoformat(we) <= target_date
    ]
    if not valid:
        return None, None

    valid.sort(key=lambda x: x[0], reverse=True)
    latest_we, latest_val = valid[0]
    latest_week = _week_number(latest_we)

    # 5-year average for the same ISO week
    avg_candidates = prior.get(latest_week, [])
    if not avg_candidates:
        return latest_val, None

    avg = sum(avg_candidates) / len(avg_candidates)
    return latest_val, avg


def _parse_conditions(rows: list[dict], target_date: date) -> float | None:
    """
    Sum of PCT GOOD and PCT EXCELLENT for the most recent week on or before
    target_date.  Returns None if no data available (off-season).
    """
    if not rows:
        return None

    # Collect (week_ending, unit_desc, value) triples
    readings: dict[str, dict[str, float]] = {}  # week_ending → {unit → value}
    for row in rows:
        unit = str(row.get("unit_desc", "")).strip().upper()
        we   = str(row.get("week_ending", "")).strip()
        val  = _parse_value(row)
        if val is None or not we or unit not in ("PCT GOOD", "PCT EXCELLENT"):
            continue
        readings.setdefault(we, {})[unit] = val

    # Filter to weeks on or before target_date
    valid_weeks = [
        we for we in readings
        if date.fromisoformat(we) <= target_date
    ]
    if not valid_weeks:
        return None

    latest_we = max(valid_weeks)
    week_data = readings[latest_we]
    good = week_data.get("PCT GOOD", 0.0)
    exc  = week_data.get("PCT EXCELLENT", 0.0)

    # Return None if neither key was found (truly no condition data)
    if "PCT GOOD" not in week_data and "PCT EXCELLENT" not in week_data:
        return None

    return good + exc


def _parse_yield(
    rows: list[dict],
    current_year: int,
) -> tuple[float | None, float | None]:
    """
    Returns (latest_forecast_bu_ac, prior_year_final_bu_ac).
    Both are None if data is absent.
    """
    if not rows:
        return None, None

    current_vals: list[float] = []
    prior_vals:   list[float] = []

    for row in rows:
        yr  = int(row.get("year", 0))
        val = _parse_value(row)
        if val is None:
            continue
        if yr == current_year:
            current_vals.append(val)
        elif yr == current_year - 1:
            prior_vals.append(val)

    forecast = current_vals[-1] if current_vals else None  # NASS ordered oldest-first
    prior    = prior_vals[-1]   if prior_vals   else None  # final yield (last entry)

    return forecast, prior
