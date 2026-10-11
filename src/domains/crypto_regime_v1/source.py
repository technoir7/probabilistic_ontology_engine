"""
Evidence source for crypto-regime-v1: CoinGecko + yfinance + FRED.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.coingecko_client import CoinGeckoClient
from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import CryptoRegimePipeline
from .ingestion.yfinance_client import CryptoYFinanceClient


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    cg = CoinGeckoClient()
    yf_client = CryptoYFinanceClient()
    fred = FREDClient(api_key=env["FRED_API_KEY"])
    async with cg, yf_client, fred:
        yield CryptoRegimePipeline(cg, yf_client, fred)
