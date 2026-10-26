"""runtime.ingestion: dedup, unchanged-state skip, and store+learn atomicity."""
from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest

from src.domains.sovereign_debt_v1.domain import SovereignDebtV1, get_variables
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.model.errors import EvidenceUnavailable
from src.engine.runtime.ingestion import ingest_and_learn, learn_new_records, rebuild
from tests.fakes import fake_record

DOMAIN_ID = "sovereign-debt-v1"


def _engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:")
    engine.register_domain(SovereignDebtV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def _same_observations_every_week(target: date):
    record = fake_record(get_variables().values(), date(2026, 1, 4), seed="same")
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
        return fake_record(get_variables().values(), target, seed="x")

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
    report = fake_record(get_variables().values(), target, seed="report").model_copy(
        update={"evidence_id": uuid4(), "source_ref": "report:x"}
    )
    engine.ingest(report)

    async def fetch(day):
        return fake_record(get_variables().values(), day, seed="fetched")

    assert asyncio.run(ingest_and_learn(engine, DOMAIN_ID, fetch, target)) == 1
    assert asyncio.run(ingest_and_learn(engine, DOMAIN_ID, fetch, target)) == 0


def test_learn_new_records_learns_unseen_records_oldest_first(monkeypatch):
    engine = _engine()
    records = [fake_record(get_variables().values(), date(2026, 3, d), seed=d) for d in (15, 1, 8)]
    learned_order = []
    real_learn = engine.learn
    monkeypatch.setattr(engine, "learn", lambda batch, domain: (learned_order.extend(r.timestamp.day for r in batch), real_learn(batch, domain))[1])

    assert learn_new_records(engine, DOMAIN_ID, records[:2]) == 2
    assert learn_new_records(engine, DOMAIN_ID, records) == 1  # only the 8th is new
    assert learned_order == [1, 15, 8]
    assert engine.evidence_store.count(DOMAIN_ID) == 3


def test_rebuild_forgets_the_domain_and_relearns_what_it_fetches():
    engine = _engine()
    stale = fake_record(get_variables().values(), date(2025, 1, 5), seed="stale")
    engine.ingest(stale)
    engine.learn([stale], DOMAIN_ID)
    failing_day = date(2026, 3, 15)

    async def fetch(day):
        if day == failing_day:
            raise EvidenceUnavailable("no input")
        return fake_record(get_variables().values(), day, seed="fetched")

    targets = [date(2026, 3, 1), date(2026, 3, 8), failing_day]
    result = asyncio.run(rebuild(engine, DOMAIN_ID, fetch, targets, pause_s=0, sleep=_no_sleep))

    assert result.learned == 2
    assert result.missed == [failing_day]
    stored = engine.evidence_store.load_all(DOMAIN_ID)
    assert [r.timestamp.day for r in stored] == [1, 8]  # the stale record is gone
    assert engine.get_population(DOMAIN_ID).dominant().evidence_count == 2


async def _no_sleep(_s):
    return None


def test_a_rebuild_retries_a_failed_fetch_and_reports_what_it_still_missed():
    """An upstream error is often momentary, so a failed target is tried once
    more; one with no data to give is not retried. Whatever is still missing
    is reported, so a history with holes in it is never mistaken for whole."""
    engine = _engine()
    flaky, down, empty = date(2026, 3, 8), date(2026, 3, 15), date(2026, 3, 22)
    calls: dict[date, int] = {}

    async def fetch(day):
        calls[day] = calls.get(day, 0) + 1
        if day == flaky and calls[day] == 1:
            raise IOError("FRED API HTTP 500")
        if day == down:
            raise IOError("FRED API HTTP 500")
        if day == empty:
            raise EvidenceUnavailable("no input")
        return fake_record(get_variables().values(), day, seed="fetched")

    targets = [date(2026, 3, 1), flaky, down, empty]
    result = asyncio.run(rebuild(engine, DOMAIN_ID, fetch, targets, pause_s=0, sleep=_no_sleep))

    assert result.learned == 2
    assert result.missed == [down, empty]
    assert calls == {date(2026, 3, 1): 1, flaky: 2, down: 2, empty: 1}


def test_a_rebuild_that_fetches_nothing_keeps_the_domain():
    """If every fetch fails there is nothing to replace the domain with, so
    it is kept rather than reset to empty."""
    import pytest
    engine = _engine()
    kept = fake_record(get_variables().values(), date(2025, 1, 5), seed="kept")
    engine.ingest(kept)
    engine.learn([kept], DOMAIN_ID)

    async def fetch(day):
        raise EvidenceUnavailable("upstream down")

    with pytest.raises(RuntimeError, match="nothing fetched"):
        asyncio.run(rebuild(engine, DOMAIN_ID, fetch, [date(2026, 3, 1)], pause_s=0, sleep=_no_sleep))
    assert engine.evidence_store.count(DOMAIN_ID) == 1


def test_a_rebuild_whose_fetches_mostly_fail_keeps_the_domain():
    """A source that is down, or cannot reach that far back, fails most of
    the window. Relearning from the few days it gave would throw away a
    longer history, so the domain is kept."""
    engine = _engine()
    kept = fake_record(get_variables().values(), date(2025, 1, 5), seed="kept")
    engine.ingest(kept)
    engine.learn([kept], DOMAIN_ID)
    recent = date(2026, 3, 22)

    async def fetch(day):
        if day == recent:
            return fake_record(get_variables().values(), day, seed="fetched")
        raise IOError("only the last week is served")

    targets = [date(2026, 3, 1), date(2026, 3, 8), date(2026, 3, 15), recent]
    with pytest.raises(RuntimeError, match="3 of 4 fetches failed"):
        asyncio.run(rebuild(engine, DOMAIN_ID, fetch, targets, pause_s=0, sleep=_no_sleep))
    assert [r.timestamp.date() for r in engine.evidence_store.load_all(DOMAIN_ID)] == [date(2025, 1, 5)]
