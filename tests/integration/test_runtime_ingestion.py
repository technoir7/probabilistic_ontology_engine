"""runtime.ingestion: dedup, unchanged-state skip, and store+learn atomicity."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.domains.sovereign_debt_v1.domain import SovereignDebtV1, get_variables
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.runtime.ingestion import ingest_and_learn
from tests.fakes import soft_record

DOMAIN_ID = "sovereign-debt-v1"


def _engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:")
    engine.register_domain(SovereignDebtV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def _same_observations_every_week(target: date):
    record = soft_record(get_variables().values(), date(2026, 1, 4), seed="same")
    return record.model_copy(update={"timestamp": record.timestamp.replace(day=target.day, month=target.month)})


def test_an_unchanged_weekly_state_is_skipped_when_asked():
    engine = _engine()

    async def fetch(target):
        return _same_observations_every_week(target)

    async def run():
        first = await ingest_and_learn(engine, DOMAIN_ID, fetch, date(2026, 3, 1), skip_unchanged_state=True)
        second = await ingest_and_learn(engine, DOMAIN_ID, fetch, date(2026, 3, 8), skip_unchanged_state=True)
        third = await ingest_and_learn(engine, DOMAIN_ID, fetch, date(2026, 3, 15), skip_unchanged_state=False)
        return first, second, third

    assert asyncio.run(run()) == (1, 0, 1)


def test_a_failed_learn_does_not_keep_the_record(monkeypatch):
    engine = _engine()

    async def fetch(target):
        return soft_record(get_variables().values(), target, seed="x")

    def broken_learn(*_args, **_kwargs):
        raise RuntimeError("learn exploded")

    monkeypatch.setattr(engine, "learn", broken_learn)
    with pytest.raises(RuntimeError):
        asyncio.run(ingest_and_learn(engine, DOMAIN_ID, fetch, date(2026, 3, 1)))
    assert engine.evidence_store.count(DOMAIN_ID) == 0
