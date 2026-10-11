"""
Adapter for the art domain, which lives in the separate art-market-domain
package (pinned in pyproject.toml) and has its own ingest API.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

ART_PACKAGE = "art_prestige_regime_v1"


def import_art_module(submodule: str = "") -> Any:
    """Import the art package (or one of its modules), falling back to a sibling checkout."""
    module_name = f"{ART_PACKAGE}.{submodule}" if submodule else ART_PACKAGE
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != ART_PACKAGE:
            raise
        sibling_src = Path(__file__).resolve().parents[4] / "art-market-domain" / "src"
        if sibling_src.exists():
            sys.path.insert(0, str(sibling_src))
            return importlib.import_module(module_name)
        raise


def build_art_domain() -> Any:
    return import_art_module().ArtPrestigeRegimeV1()


class _ArtSource:
    async def fetch_evidence(self, target_date: date):
        ingest_module = import_art_module("ingest")
        domain_module = import_art_module("domain")
        observations = await ingest_module.fetch_observations(target_date)
        record = domain_module.build_evidence_record(observations)
        record.timestamp = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
        return record


@asynccontextmanager
async def open_source(_env: Mapping[str, str]) -> AsyncIterator[_ArtSource]:
    yield _ArtSource()
