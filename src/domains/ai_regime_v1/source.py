"""
Evidence source for ai-regime-v1: yfinance + FRED + SEC EDGAR.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.edgar_client import EDGARClient
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import AIRegimePipeline
from .ingestion.yfinance_client import AIYFinanceClient


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    fred = FREDClient(api_key=env["FRED_API_KEY"])
    yf_client = AIYFinanceClient()
    edgar = EDGARClient()
    async with fred, edgar, yf_client:
        yield AIRegimePipeline(yf_client, fred, edgar)
