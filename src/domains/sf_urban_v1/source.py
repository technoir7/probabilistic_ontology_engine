"""
Evidence source for sf-urban-v1: SF Open Data + FRED.

open_source opens this domain's clients once and yields its pipeline; callers
use ``await source.fetch_evidence(target_date)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.fred_client import FREDClient
from .ingestion.pipeline import SFUrbanPipeline
from .ingestion.sfgov_client import SFGovClient


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator:
    sfgov = SFGovClient()
    fred = FREDClient(api_key=env["FRED_API_KEY"])
    async with sfgov, fred:
        yield SFUrbanPipeline(sfgov, fred)
