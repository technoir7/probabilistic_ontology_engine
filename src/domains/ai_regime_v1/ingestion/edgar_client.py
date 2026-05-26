"""
EDGARClient — SEC EDGAR 10-Q capex data for hyperscaler companies.

Fetches capital expenditure data from the SEC EDGAR XBRL Company Facts API.
No API key required.  EDGAR enforces a soft rate limit of ~10 req/s;
responses are cached in-memory for 6 hours to be polite to the service
and because this is a weekly-cadence domain.

Companies tracked (hyperscalers driving AI infrastructure)
----------------------------------------------------------
    MSFT  (Microsoft Corp)        CIK: 0000789019
    GOOGL (Alphabet Inc.)         CIK: 0001652044
    AMZN  (Amazon.com, Inc.)      CIK: 0001018724
    META  (Meta Platforms, Inc.)  CIK: 0001326801

XBRL concept
------------
    us-gaap / PaymentsToAcquirePropertyPlantAndEquipment

    This is the standard GAAP cash-flow-statement line for capital
    expenditures (payments to acquire property, plant and equipment).
    All four companies use this concept.  It covers data-centre hardware,
    networking, land, and buildings — the primary AI-infrastructure spend.

    Note: some companies also capitalise AI-related intangibles separately;
    this metric captures the physical infrastructure spend only.

YoY capex growth computation
-----------------------------
    1. Fetch company facts JSON for each CIK.
    2. Extract all 10-Q entries for PaymentsToAcquirePropertyPlantAndEquipment.
    3. For each company, find the most recent (fiscal_year, fiscal_period)
       pair with a valid value.
    4. Find the same fiscal_period from the prior fiscal_year.
    5. YoY growth (%) = (current_ytd / prior_ytd − 1) × 100.
       Note: 10-Q cash-flow values are cumulative year-to-date, so
       comparing the same fiscal period across years is apples-to-apples.
    6. Average across all four companies that have valid data.

Caching
-------
    In-memory dict keyed by CIK.  Each entry stores (fetched_at, data).
    TTL defaults to 6 hours.  Expired entries are re-fetched on next call.

Missing data handling
---------------------
    If a company's EDGAR fetch fails or returns insufficient history,
    that company is excluded from the average.  The overall HCA signal
    degrades in confidence proportional to the fraction of companies
    with missing data.

EDGAR API
---------
    GET https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit-zero-padded}.json
    User-Agent header required by SEC (see https://www.sec.gov/os/accessing-edgar-data).
    Requests are serialised (sequential) to avoid hammering the service.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Company registry
# ---------------------------------------------------------------------------

HYPERSCALERS: dict[str, str] = {
    "MSFT":  "0000789019",
    "GOOGL": "0001652044",
    "AMZN":  "0001018724",
    "META":  "0001326801",
}

# GAAP concept for capital expenditures (PP&E purchases)
_CAPEX_CONCEPT = "PaymentsToAcquirePropertyPlantAndEquipment"

_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"

# Quarterly fiscal periods reported in 10-Q filings
_QUARTERLY_FPS = {"Q1", "Q2", "Q3"}

# User-Agent required by SEC EDGAR fair-access policy
_USER_AGENT = "ProbabilisticOntologyEngine contact@example.com"

# Cache TTL in seconds (6 hours)
_CACHE_TTL_SECONDS = 6 * 3600

# Minimum fraction of companies that must have data for confident signal
_MIN_COMPANIES_FOR_FULL_CONFIDENCE = 3

# Delay between sequential EDGAR requests (seconds)
_REQUEST_DELAY_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CompanyCapexResult:
    """YoY capex result for a single company."""
    ticker: str
    cik: str
    fiscal_year: int
    fiscal_period: str          # "Q1" | "Q2" | "Q3"
    current_ytd_usd: float      # YTD capex for most recent period
    prior_year_ytd_usd: float   # Same period one year ago
    yoy_growth_pct: float       # (current / prior − 1) × 100
    filing_end_date: date       # calendar end date of the most recent period


@dataclass
class HyperscalerCapexSnapshot:
    """
    Aggregated capex result across all hyperscalers.

    companies : dict[str, CompanyCapexResult]
        Per-company results (only companies with valid data).
    avg_yoy_growth_pct : Optional[float]
        Average YoY capex growth across companies with valid data.
        None if no company has usable data.
    companies_with_data : int
        How many of the 4 companies contributed to the average.
    confidence : float
        1.0 if all 4 companies have data; degrades linearly to 0.25
        if only 1 company has data; 0.0 if none have data.
    """
    companies: dict[str, CompanyCapexResult] = field(default_factory=dict)
    avg_yoy_growth_pct: Optional[float] = None
    companies_with_data: int = 0
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# In-memory cache entry
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    fetched_at: float               # time.monotonic() timestamp
    data: Optional[dict[str, Any]]  # raw EDGAR JSON or None on fetch failure


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class EDGARClient:
    """
    Asynchronous SEC EDGAR XBRL company-facts client.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        Injected HTTP client for testing.
    timeout : float
        Request timeout in seconds.  Default 45 (EDGAR can be slow).
    cache_ttl_seconds : int
        In-memory cache TTL.  Default 6 hours.
    """

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 45.0,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": _USER_AGENT},
        )
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl_seconds

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "EDGARClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_hyperscaler_capex(
        self,
        as_of: Optional[date] = None,
    ) -> HyperscalerCapexSnapshot:
        """
        Fetch and aggregate YoY capex growth for all 4 hyperscalers.

        Parameters
        ----------
        as_of : date, optional
            Only consider filings with end dates on or before this date.
            Defaults to today.  Useful for backfill.

        Returns
        -------
        HyperscalerCapexSnapshot
            Aggregated result with per-company details.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc).date()

        results: dict[str, CompanyCapexResult] = {}
        errors: list[str] = []

        for ticker, cik in HYPERSCALERS.items():
            try:
                result = await self._fetch_company_capex(ticker, cik, as_of)
                if result is not None:
                    results[ticker] = result
                else:
                    errors.append(f"{ticker}: no comparable period found")
            except Exception as exc:
                logger.warning(
                    "EDGAR capex fetch failed for %s (CIK %s): %s",
                    ticker, cik, exc,
                )
                errors.append(f"{ticker}: {exc}")
            # Polite delay between sequential EDGAR requests
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        if errors:
            logger.debug("EDGAR: missing companies: %s", "; ".join(errors))

        n = len(results)
        avg_yoy: Optional[float] = None
        if n > 0:
            avg_yoy = sum(r.yoy_growth_pct for r in results.values()) / n

        # Confidence: 1.0 with 4 companies, 0.0 with 0
        confidence = n / len(HYPERSCALERS)

        return HyperscalerCapexSnapshot(
            companies=results,
            avg_yoy_growth_pct=avg_yoy,
            companies_with_data=n,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_company_capex(
        self,
        ticker: str,
        cik: str,
        as_of: date,
    ) -> Optional[CompanyCapexResult]:
        """
        Fetch capex YoY growth for a single company.

        Returns None if insufficient data is available for YoY comparison.
        """
        facts = await self._get_company_facts(cik)
        if facts is None:
            return None

        entries = _extract_capex_entries(facts, cik, ticker)
        if not entries:
            logger.debug(
                "No %s entries for %s (CIK %s)",
                _CAPEX_CONCEPT, ticker, cik,
            )
            return None

        return _compute_yoy_growth(ticker, cik, entries, as_of)

    async def _get_company_facts(self, cik: str) -> Optional[dict[str, Any]]:
        """
        Return cached company facts, fetching from EDGAR if stale.
        """
        entry = self._cache.get(cik)
        now = time.monotonic()

        if entry is not None and (now - entry.fetched_at) < self._cache_ttl:
            return entry.data  # cache hit (may be None on persistent failure)

        # Cache miss or expired — fetch
        url = f"{_BASE_URL}/CIK{cik}.json"
        try:
            logger.debug("EDGAR fetch: %s", url)
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            self._cache[cik] = _CacheEntry(fetched_at=now, data=data)
            return data
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "EDGAR HTTP %d for CIK %s",
                exc.response.status_code, cik,
            )
            self._cache[cik] = _CacheEntry(fetched_at=now, data=None)
            return None
        except Exception as exc:
            logger.warning("EDGAR fetch error for CIK %s: %s", cik, exc)
            self._cache[cik] = _CacheEntry(fetched_at=now, data=None)
            return None

    def clear_cache(self) -> None:
        """Clear the in-memory cache (useful for testing)."""
        self._cache.clear()


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — fully testable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _CapexEntry:
    """Parsed capex entry from EDGAR XBRL facts."""
    fiscal_year: int
    fiscal_period: str   # "Q1" | "Q2" | "Q3"
    end_date: date
    start_date: date
    value_usd: float


def _extract_capex_entries(
    facts: dict[str, Any],
    cik: str,
    ticker: str,
) -> list[_CapexEntry]:
    """
    Extract all valid 10-Q capex entries from EDGAR company facts JSON.

    Returns entries sorted by (fiscal_year, fiscal_period), newest first.
    Only 10-Q filings and quarterly fiscal periods (Q1/Q2/Q3) are included.
    """
    try:
        usgaap = facts.get("facts", {}).get("us-gaap", {})
        concept = usgaap.get(_CAPEX_CONCEPT, {})
        units = concept.get("units", {})
        usd_entries = units.get("USD", [])
    except (AttributeError, TypeError) as exc:
        logger.debug(
            "Could not parse EDGAR facts for %s (%s): %s",
            ticker, cik, exc,
        )
        return []

    parsed: list[_CapexEntry] = []
    for raw in usd_entries:
        # Only 10-Q forms; only quarterly periods
        if raw.get("form") != "10-Q":
            continue
        fp = raw.get("fp", "")
        if fp not in _QUARTERLY_FPS:
            continue
        # Must have a positive value
        try:
            val = float(raw["val"])
        except (KeyError, TypeError, ValueError):
            continue
        if val <= 0:
            continue
        # Parse fiscal year
        try:
            fy = int(raw["fy"])
        except (KeyError, TypeError, ValueError):
            continue
        # Parse dates
        try:
            end_date = date.fromisoformat(str(raw["end"])[:10])
            start_date = date.fromisoformat(str(raw["start"])[:10])
        except (KeyError, ValueError):
            continue

        parsed.append(_CapexEntry(
            fiscal_year=fy,
            fiscal_period=fp,
            end_date=end_date,
            start_date=start_date,
            value_usd=val,
        ))

    if not parsed:
        return []

    # Deduplicate: keep the last-filed entry per (fy, fp) pair
    best: dict[tuple[int, str], _CapexEntry] = {}
    for entry in parsed:
        key = (entry.fiscal_year, entry.fiscal_period)
        # Prefer larger values on duplicates (some amended filings restated)
        existing = best.get(key)
        if existing is None or entry.end_date >= existing.end_date:
            best[key] = entry

    # Sort newest first
    result = sorted(
        best.values(),
        key=lambda e: (e.fiscal_year, e.fiscal_period),
        reverse=True,
    )
    return result


def _compute_yoy_growth(
    ticker: str,
    cik: str,
    entries: list[_CapexEntry],
    as_of: date,
) -> Optional[CompanyCapexResult]:
    """
    Compute YoY capex growth from sorted (newest-first) _CapexEntry list.

    Finds the most recent period with an end_date ≤ as_of, then looks for
    the same fiscal_period from the prior fiscal_year.

    Returns None if the required comparison period is not available.
    """
    # Find most recent entry with end_date <= as_of
    current: Optional[_CapexEntry] = None
    for entry in entries:
        if entry.end_date <= as_of:
            current = entry
            break

    if current is None:
        logger.debug(
            "%s: no capex entry with end_date <= %s", ticker, as_of
        )
        return None

    # Find same fiscal_period from prior fiscal_year
    target_fy = current.fiscal_year - 1
    prior: Optional[_CapexEntry] = None
    for entry in entries:
        if (
            entry.fiscal_year == target_fy
            and entry.fiscal_period == current.fiscal_period
        ):
            prior = entry
            break

    if prior is None:
        logger.debug(
            "%s: no prior-year capex for FY%d %s",
            ticker, target_fy, current.fiscal_period,
        )
        return None

    if prior.value_usd <= 0:
        logger.debug(
            "%s: prior-year capex is zero or negative", ticker
        )
        return None

    yoy_pct = (current.value_usd / prior.value_usd - 1.0) * 100.0

    logger.info(
        "EDGAR %s: FY%d %s capex = $%.0fM (vs $%.0fM prior) → YoY %.1f%%",
        ticker,
        current.fiscal_year,
        current.fiscal_period,
        current.value_usd / 1e6,
        prior.value_usd / 1e6,
        yoy_pct,
    )

    return CompanyCapexResult(
        ticker=ticker,
        cik=cik,
        fiscal_year=current.fiscal_year,
        fiscal_period=current.fiscal_period,
        current_ytd_usd=current.value_usd,
        prior_year_ytd_usd=prior.value_usd,
        yoy_growth_pct=yoy_pct,
        filing_end_date=current.end_date,
    )
