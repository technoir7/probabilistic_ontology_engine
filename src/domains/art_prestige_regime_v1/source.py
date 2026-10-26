"""
Evidence source for art_prestige_regime_v1: the Guardian and NYT archives
(keys required), the Art Basel & UBS figures committed in
report_figures.csv, and two museums' open APIs (no keys).

open_source opens the clients once and yields the pipeline; callers use
``await source.fetch_evidence(month_end)`` and close it by leaving the block.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Mapping

from .ingestion.aic_client import AICClient
from .ingestion.cma_client import CMAClient
from .ingestion.guardian_client import GuardianClient
from .ingestion.nyt_client import NYTClient
from .ingestion.pipeline import ArtPipeline


@asynccontextmanager
async def open_source(env: Mapping[str, str]) -> AsyncIterator[ArtPipeline]:
    guardian, nyt = GuardianClient(env["GUARDIAN_API_KEY"]), NYTClient(env["NYT_API_KEY"])
    async with guardian, nyt, AICClient() as aic, CMAClient() as cma:
        yield ArtPipeline({"guardian": guardian, "nyt": nyt}, aic, cma)
