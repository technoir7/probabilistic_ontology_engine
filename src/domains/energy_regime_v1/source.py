"""
Evidence source for energy-regime-v1: FRED + yfinance.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import EnergyRegimePipeline
from .ingestion.yfinance_client import EnergyYFinanceClient


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    fred = FREDClient(api_key=env["FRED_API_KEY"])
    yf_client = EnergyYFinanceClient()
    async with fred, yf_client:
        yield EnergyRegimePipeline(fred, yf_client)
