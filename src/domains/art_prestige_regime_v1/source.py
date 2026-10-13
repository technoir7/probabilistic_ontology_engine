"""
Evidence source for art_prestige_regime_v1: GDELT news coverage and the Art
Institute of Chicago's acquisitions. No API keys.

open_source opens the clients once and yields the pipeline; callers use
``await source.fetch_evidence(month_end)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from ..sources.gdelt import GDELTClient
from .ingestion.aic_client import AICClient
from .ingestion.pipeline import ArtPipeline


@asynccontextmanager
async def open_source(_env: Mapping[str, str]) -> AsyncIterator[ArtPipeline]:
    async with GDELTClient() as gdelt, AICClient() as aic:
        yield ArtPipeline(gdelt, aic)
