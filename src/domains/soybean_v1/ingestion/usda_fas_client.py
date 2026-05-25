"""
USDAFASClient — fetches weekly U.S. soybean export inspection volume from the
USDA Foreign Agricultural Service (FAS) Global Agricultural Trade System
(GATS).

API
---
    GET https://apps.fas.usda.gov/gats/ExpressQuery1.aspx
        ?formatType=json
        &commodity=SOYBEANS  # USDA FAS commodity code for soybeans
        &unit=MT             # metric tons
        &tradeType=E         # exports
        &period=W            # weekly
        &year=<YYYY>
        &numPeriods=<N>      # most-recent N weeks, newest first

No API key required.

Response format
---------------
    {"datalist": [
        {"yearperiod": "2025 W20", "value": "1250000"},
        {"yearperiod": "2025 W19", "value": "1100000"},
        ...
    ]}

Derived variable
----------------
    ExportDemandHigh = current_week_mt > rolling_4wk_avg_mt

    where rolling_4wk_avg_mt is the average of the four most recent
    completed weeks preceding the current week.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL        = "https://apps.fas.usda.gov/gats/ExpressQuery1.aspx"
_SOYBEAN_CODE    = "SOYBEANS"   # USDA FAS commodity code for soybeans
_WEEKS_NEEDED    = 5            # 1 current + 4 for rolling average


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SoybeanFASSnapshot:
    target_date: date
    current_week_exports_mt: float   # most recent week's export tonnage
    rolling_4wk_avg_mt: float        # 4-week rolling average (preceding weeks)
    export_demand_high: bool          # True if current_week > rolling avg


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class USDAFASClient:
    """
    Asynchronous client for USDA FAS weekly soybean export data.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        Injected HTTP client.  If provided, the caller owns it (not closed
        on exit).  Pass an AsyncMock here in tests.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "USDAFASClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_snapshot(self, target_date: date) -> SoybeanFASSnapshot:
        """
        Fetch the most recent _WEEKS_NEEDED weeks of soybean export inspection
        data and return a SoybeanFASSnapshot.

        Raises IOError if the API returns unusable data.
        """
        rows = await self._fetch_export_rows(target_date.year)
        return self.build_snapshot(target_date, rows)

    # ------------------------------------------------------------------
    # Pure snapshot builder (no I/O — testable synchronously)
    # ------------------------------------------------------------------

    @staticmethod
    def build_snapshot(target_date: date, rows: list[dict]) -> SoybeanFASSnapshot:
        """
        Map raw FAS API rows to a SoybeanFASSnapshot.  Static and synchronous
        so it can be unit-tested without network calls.

        Rows must be ordered newest-first and represent weekly tonnage.
        Raises IOError if fewer than 2 rows are present (cannot compute avg).
        """
        if len(rows) < 2:
            raise IOError(
                f"FAS API returned {len(rows)} row(s); need at least 2 "
                "to compute the 4-week rolling average."
            )

        values = _extract_values(rows)
        if len(values) < 2:
            raise IOError("FAS data rows have insufficient numeric values")

        current = values[0]
        prior   = values[1:]
        rolling_avg = sum(prior) / len(prior)

        return SoybeanFASSnapshot(
            target_date=target_date,
            current_week_exports_mt=current,
            rolling_4wk_avg_mt=rolling_avg,
            export_demand_high=current > rolling_avg,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_export_rows(self, year: int) -> list[dict]:
        """
        Fetch WEEKS_NEEDED weeks of soybean export data.
        Returns newest-first list of row dicts.
        Raises IOError on HTTP or parse failure.
        """
        params = {
            "formatType": "json",
            "commodity": _SOYBEAN_CODE,
            "unit": "MT",
            "tradeType": "E",
            "period": "W",
            "year": str(year),
            "numPeriods": str(_WEEKS_NEEDED),
        }
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise IOError(
                f"FAS API HTTP {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise IOError(f"FAS API request failed: {exc}") from exc

        rows = body.get("datalist", [])
        if not rows:
            raise IOError("FAS API returned empty datalist")
        return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_values(rows: list[dict]) -> list[float]:
    """Parse numeric 'value' fields from FAS rows, skipping non-numeric."""
    out: list[float] = []
    for row in rows:
        raw = str(row.get("value", "")).strip().replace(",", "")
        try:
            out.append(float(raw))
        except ValueError:
            logger.warning("Skipping non-numeric FAS row value: %r", raw)
    return out
