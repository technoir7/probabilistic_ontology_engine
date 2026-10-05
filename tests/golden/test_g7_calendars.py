"""
G7 — calendar golden (REFACTOR_SPEC §7 Phase 0.3).

Records which target dates each entry point asks for, on each day of one week:

* ``api_trigger``     POST /v1/ingest/trigger
* ``api_backfill``    POST /v1/ingest/backfill?days=14
* ``startup_backfill`` the app's backfill-if-empty functions (2 weeks / 14 days)
* ``scheduler``       the date a weekly scheduler targets when it runs that day
* ``scheduler_backfill`` each pipeline module's own backfill-date helper

Today these disagree (B8: Sunday via the API, Friday via schedulers, daily for
mr/ai via the API). Phase 4.2 replaces them with one Cadence (Sunday, D12);
that commit regenerates this snapshot and the diff is the behaviour change.
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from tests.fakes import domain_keys, freeze_clock, patch_evidence_fetch

from .snapshot import assert_matches_snapshot

WEEK = [date(2026, 3, 2) + timedelta(days=i) for i in range(7)]  # Monday..Sunday

# Where each weekly domain keeps its own `_last_friday` / `_weekly_backfill_dates`
# copies (macro keeps the backfill helper in its scheduler module).
PIPELINE_MODULES = {
    "mr": "src.domains.macro_regime_v1.ingestion.pipeline",
    "ai": "src.domains.ai_regime_v1.ingestion.pipeline",
    "sd": "src.domains.sovereign_debt_v1.ingestion.pipeline",
    "cc": "src.domains.credit_cycle_v1.ingestion.pipeline",
    "er": "src.domains.energy_regime_v1.ingestion.pipeline",
    "lm": "src.domains.labor_market_v1.ingestion.pipeline",
    "cr": "src.domains.crypto_regime_v1.ingestion.pipeline",
    "gp": "src.domains.geopolitics_v1.ingestion.pipeline",
    "sf": "src.domains.sf_urban_v1.ingestion.pipeline",
}


class _Recorded(Exception):
    """Raised by the fake fetch so nothing is ingested; only the date matters."""


def _noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)


def _iso(dates) -> list[str]:
    return [d.isoformat() for d in dates]


def test_g7_api_calendars_match_golden(monkeypatch):
    calls: list[tuple[str, date]] = []

    async def recording_fetch(domain_key: str, target_date: date):
        calls.append((domain_key, target_date))
        raise _Recorded

    patch_evidence_fetch(monkeypatch, recording_fetch)
    out: dict = {}
    with TestClient(api_app.app) as client:
        for day in WEEK:
            freeze_clock(monkeypatch, _noon(day))
            per_day = out.setdefault(f"{day.isoformat()} {day.strftime('%a')}", {})
            for key in domain_keys():
                calls.clear()
                client.post(f"/v1/ingest/trigger?domain={key}")
                client.post(f"/v1/ingest/backfill?domain={key}&days=14")
                per_day[key] = {
                    "api_trigger": _iso(d for _, d in calls[:1]),
                    "api_backfill": _iso(d for _, d in calls[1:]),
                }
    assert_matches_snapshot("g7_calendars_api", out)


def test_g7_startup_and_scheduler_calendars_match_golden(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    recorded: list[date] = []

    class RecordingPipeline:
        async def fetch_evidence(self, target_date: date):
            recorded.append(target_date)
            raise _Recorded

    async def recording_fetch(domain_key: str, target_date: date):
        recorded.append(target_date)
        raise _Recorded

    patch_evidence_fetch(monkeypatch, recording_fetch)
    empty_engine = SimpleNamespace(evidence_store=SimpleNamespace(count=lambda _domain_id: 0))

    async def startup_targets(key: str) -> list[date]:
        recorded.clear()
        lock = asyncio.Lock()
        domain_id, display = api_app._DOMAIN_MAP[key]
        common = dict(engine=empty_engine, domain_id=domain_id, display_name=display, lock=lock)
        if key == "ng":
            await api_app._backfill_if_empty(domain_key=key, backfill_days=14, **common)
        elif key == "mr":
            await api_app._backfill_macro_if_empty(pipeline=RecordingPipeline(), backfill_weeks=2, **common)
        elif key == "ai":
            await api_app._backfill_ai_if_empty(pipeline=RecordingPipeline(), backfill_weeks=2, **common)
        elif key == "art":
            return []  # art has no startup backfill
        else:
            await api_app._backfill_fred_domain_if_empty(pipeline=RecordingPipeline(), backfill_weeks=2, **common)
        return list(recorded)

    out: dict = {}
    for day in WEEK:
        freeze_clock(monkeypatch, _noon(day))
        per_day = out.setdefault(f"{day.isoformat()} {day.strftime('%a')}", {})
        for key in domain_keys():
            entry = {"startup_backfill": _iso(asyncio.run(startup_targets(key)))}
            if key in PIPELINE_MODULES:
                module = importlib.import_module(PIPELINE_MODULES[key])
                backfill_module = (
                    importlib.import_module("src.domains.macro_regime_v1.scheduler")
                    if key == "mr" else module
                )
                entry["scheduler"] = module._last_friday(day).isoformat()
                entry["scheduler_backfill"] = _iso(backfill_module._weekly_backfill_dates(2, day))
            per_day[key] = entry
    assert_matches_snapshot("g7_calendars_startup_scheduler", out)
