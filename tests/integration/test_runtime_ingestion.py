"""runtime.ingestion: dedup, unchanged-state skip, and store+learn atomicity."""
from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest

from src.domains.sovereign_debt_v1.domain import SovereignDebtV1, get_variables
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.runtime.ingestion import ingest_and_learn, learn_new_records
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


def test_a_record_from_another_source_on_the_same_day_does_not_block_ingest():
    """Art has fetched monthly records and hand-supplied reports; a report dated
    on a month end must not make the month's fetched record look already stored."""
    engine = _engine()
    target = date(2026, 3, 1)
    report = soft_record(get_variables().values(), target, seed="report").model_copy(
        update={"evidence_id": uuid4(), "source_ref": "report:x"}
    )
    engine.ingest(report)

    async def fetch(day):
        return soft_record(get_variables().values(), day, seed="fetched")

    assert asyncio.run(ingest_and_learn(engine, DOMAIN_ID, fetch, target)) == 1
    assert asyncio.run(ingest_and_learn(engine, DOMAIN_ID, fetch, target)) == 0


def test_learn_new_records_learns_unseen_records_oldest_first(monkeypatch):
    engine = _engine()
    records = [soft_record(get_variables().values(), date(2026, 3, d), seed=d) for d in (15, 1, 8)]
    learned_order = []
    real_learn = engine.learn
    monkeypatch.setattr(engine, "learn", lambda batch, domain: (learned_order.extend(r.timestamp.day for r in batch), real_learn(batch, domain))[1])

    assert learn_new_records(engine, DOMAIN_ID, records[:2]) == 2
    assert learn_new_records(engine, DOMAIN_ID, records) == 1  # only the 8th is new
    assert learned_order == [1, 15, 8]
    assert engine.evidence_store.count(DOMAIN_ID) == 3
