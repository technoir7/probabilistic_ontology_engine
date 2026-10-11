"""
Evidence source for natural-gas-v1: NOAA weather + EIA storage/price.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.eia_client import EIAClient
from .ingestion.noaa_client import NOAAClient
from .ingestion.pipeline import NaturalGasPipeline


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    noaa = NOAAClient()
    eia = EIAClient(api_key=env["EIA_API_KEY"])
    async with noaa, eia:
        yield NaturalGasPipeline(noaa, eia)
