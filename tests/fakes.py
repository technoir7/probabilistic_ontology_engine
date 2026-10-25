"""
Test doubles and the seams tests use to reach into the running app.

Tests replace the evidence fetch, freeze the clock, and look up a domain's
engine only through these helpers. They patch ``api.context.fetch_evidence_record``
/ ``api.context.utcnow`` and read ``app.state.engines``; when the refactor moves those
(REFACTOR_SPEC Phase 5), only this module changes, not every test.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Awaitable, Callable, Iterable

from src.engine.api import app as api_app
from src.engine.api import context as api_context
from src.engine.schemas import (
    DomainType,
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
    Variable,
)

FetchFn = Callable[[str, date], Awaitable[EvidenceRecord]]

# conftest sets POE_ADMIN_TOKEN to this for every test.
ADMIN_TOKEN = "test-admin-token"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def fake_record(variables: Iterable[Variable], target_date: date, *, seed: int | str) -> EvidenceRecord:
    """A record over *variables* as their domain would give it, deterministic
    for (seed, target_date): a soft yes/no for a BOOLEAN variable, an exact
    level for a graded one (D25)."""
    rng = random.Random(f"{seed}:{target_date.isoformat()}")
    assignments = []
    for var in variables:
        p = round(rng.uniform(0.05, 0.95), 4)
        if var.domain_type == DomainType.BOOLEAN:
            assignments.append(ObservedAssignment(
                variable_id=var.variable_id,
                observed_value=p > 0.5,
                missingness=MissingnessType.SOFT_OBSERVED,
                probabilities={True: p, False: round(1.0 - p, 4)},
            ))
        else:
            assignments.append(ObservedAssignment(
                variable_id=var.variable_id,
                observed_value=var.support[min(int(p * len(var.support)), len(var.support) - 1)],
            ))
    return EvidenceRecord(
        timestamp=datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc),
        observed_assignments=assignments,
        source_type=SourceType.API,
        source_ref=f"fake@{target_date.isoformat()}",
    )


def patch_evidence_fetch(monkeypatch, fetch: FetchFn) -> None:
    monkeypatch.setattr(api_context, "fetch_evidence_record", fetch)


def patch_fake_evidence_for_all_domains(monkeypatch) -> list[tuple[str, date]]:
    """
    Every domain's fetch returns a deterministic fake_record over that
    domain's own variables. Returns the list of (domain_key, target_date)
    calls, so tests can check which dates an entry point asked for.
    """
    calls: list[tuple[str, date]] = []

    async def fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        calls.append((domain_key, target_date))
        return fake_record(domain_variables(domain_key), target_date, seed=domain_key)

    patch_evidence_fetch(monkeypatch, fetch)
    return calls


def domain_keys() -> list[str]:
    return list(api_context.DOMAIN_MAP)


def running_engine(domain_key: str):
    """The engine the running app (inside a TestClient block) uses for *domain_key*."""
    return api_app.app.state.engines[domain_key]


def domain_variables(domain_key: str) -> list[Variable]:
    return running_engine(domain_key).get_population().candidates[0].variables


def freeze_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr(api_context, "utcnow", lambda: now)
