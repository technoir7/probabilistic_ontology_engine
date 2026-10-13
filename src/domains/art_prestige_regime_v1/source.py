"""
Evidence source for art_prestige_regime_v1: Wikipedia pageviews and the Art
Institute of Chicago's acquisitions. No API keys.

open_source opens the clients once and yields the pipeline; callers use
``await source.fetch_evidence(month_end)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.aic_client import AICClient
from .ingestion.pipeline import ArtPipeline
from .ingestion.wikipedia_client import WikipediaClient


@asynccontextmanager
async def open_source(_env: Mapping[str, str]) -> AsyncIterator[ArtPipeline]:
    async with WikipediaClient() as wikipedia, AICClient() as aic:
        yield ArtPipeline(wikipedia, aic)
