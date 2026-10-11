"""
Evidence source for geopolitics-v1: GDELT + FRED.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.fred_client import FREDClient
from .ingestion.gdelt_client import GDELTClient
from .ingestion.pipeline import GeopoliticsPipeline


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    gdelt = GDELTClient()
    fred = FREDClient(api_key=env["FRED_API_KEY"])
    async with gdelt, fred:
        yield GeopoliticsPipeline(gdelt, fred)
