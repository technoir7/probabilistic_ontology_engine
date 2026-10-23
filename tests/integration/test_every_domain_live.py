"""
Live: every domain fetches its latest period from its real sources, the
way the scheduler does, and every variable comes back with a value.

A source that changes its format rarely fails loudly; it returns nothing
for one series, and the pipeline records that variable as MISSING. Mocked
tests cannot see that, so this asks the real services.

    uv run pytest -m live tests/integration/test_every_domain_live.py

Needs the API keys in .env (FRED_API_KEY, EIA_API_KEY); a domain whose
keys are absent is skipped, by name.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest
from dotenv import dotenv_values

from src.engine.runtime.registry import REGISTRY
from src.engine.schemas import MissingnessType

pytestmark = pytest.mark.live


@pytest.mark.parametrize("reg", REGISTRY, ids=[r.key for r in REGISTRY])
def test_latest_period_has_every_variable(reg):
    # conftest turns .env loading off for every test; a live test needs the keys.
    environ = {**os.environ, **{k: v for k, v in dotenv_values().items() if v is not None}}
    absent = [name for name in reg.required_env if not environ.get(name)]
    if absent:
        pytest.skip(f"{', '.join(absent)} not set")
    target = reg.cadence.default_target(date.today())

    async def fetch():
        async with reg.open_source(environ) as source:
            return await source.fetch_evidence(target)

    record = asyncio.run(fetch())
    candidate = reg.build_domain().initial_candidates()[0]
    names = {v.variable_id: v.name for v in candidate.variables if v.lag_of is None}
    missing = {names[a.variable_id] for a in record.observed_assignments
               if a.missingness == MissingnessType.MISSING}
    assert {a.variable_id for a in record.observed_assignments} == set(names), "variables differ from the domain's"
    lacking = sorted(fed_variables(reg.key, set(names.values()), target) & missing)
    assert not lacking, f"{reg.key} for {target}: no value for {lacking}"


def fed_variables(key: str, variables: set[str], target: date) -> set[str]:
    """The variables a domain's feeds should fill for TARGET: all of them,
    except art, whose feeds measure three (the rest come from hand-labelled
    reports) and two of those only in the month museums report."""
    if key != "art":
        return variables
    from src.domains.art_prestige_regime_v1.ingestion.pipeline import MEASURES, NewsShare, reported_fiscal_years
    reporting = reported_fiscal_years(target) is not None
    return {name for name, m in MEASURES.items() if isinstance(m, NewsShare) or reporting}
