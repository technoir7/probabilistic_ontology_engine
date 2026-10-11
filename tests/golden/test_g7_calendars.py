"""
G7 — calendar golden (REFACTOR_SPEC §7 Phase 0.3).

Records which target dates each entry point asks for, on each day of one week:

* ``api_trigger``     POST /v1/ingest/trigger
* ``api_backfill``    POST /v1/ingest/backfill?days=14
* ``startup_backfill`` the app's backfill-if-empty functions (2 weeks / 14 days)
* ``scheduler``       the date a weekly scheduler targets when it runs that day

They used to disagree (B8: Sunday via the API, Friday via schedulers, daily for
mr/ai via the API). Every entry point now reads the domain's one Cadence
(model/cadence.py; weekly = Sunday, D12).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.engine.api import app as api_app
from src.engine.runtime.registry import BY_KEY
from tests.fakes import domain_keys, freeze_clock, patch_evidence_fetch

from .snapshot import assert_matches_snapshot

WEEK = [date(2026, 3, 2) + timedelta(days=i) for i in range(7)]  # Monday..Sunday

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


def test_g7_startup_and_scheduler_calendars_match_golden():
    out: dict = {}
    for day in WEEK:
        per_day = out.setdefault(f"{day.isoformat()} {day.strftime('%a')}", {})
        for key in domain_keys():
            reg = BY_KEY[key]
            # Startup windows as in production: 14 days (daily) or 2 weeks (weekly).
            startup = reg.cadence.window_targets(14, day) if reg.scheduled else []
            entry = {"startup_backfill": _iso(startup)}
            if reg.scheduled and key != "ng":
                entry["scheduler"] = reg.cadence.default_target(day).isoformat()
            per_day[key] = entry
    assert_matches_snapshot("g7_calendars_startup_scheduler", out)
