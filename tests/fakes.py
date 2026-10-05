"""
Test doubles for evidence fetching.

``patch_evidence_fetch`` is the one place tests replace the app's evidence
fetch. Today the seam is ``app._fetch_evidence_record``; when the refactor
moves fetching behind the domain registry (REFACTOR_SPEC Phase 5), only this
function changes, not every test that needs fake evidence.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Awaitable, Callable, Iterable

from src.engine.api import app as api_app
from src.engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
    Variable,
)

FetchFn = Callable[[str, date], Awaitable[EvidenceRecord]]


def soft_record(variables: Iterable[Variable], target_date: date, *, seed: int | str) -> EvidenceRecord:
    """A SOFT_OBSERVED record over *variables*, deterministic for (seed, target_date)."""
    rng = random.Random(f"{seed}:{target_date.isoformat()}")
    assignments = []
    for var in variables:
        p = round(rng.uniform(0.05, 0.95), 4)
        assignments.append(ObservedAssignment(
            variable_id=var.variable_id,
            observed_value=p > 0.5,
            missingness=MissingnessType.SOFT_OBSERVED,
            probabilities={True: p, False: round(1.0 - p, 4)},
        ))
    return EvidenceRecord(
        timestamp=datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc),
        observed_assignments=assignments,
        source_type=SourceType.API,
        source_ref=f"fake@{target_date.isoformat()}",
    )


def patch_evidence_fetch(monkeypatch, fetch: FetchFn) -> None:
    monkeypatch.setattr(api_app, "_fetch_evidence_record", fetch)


def patch_soft_evidence_for_all_domains(monkeypatch) -> list[tuple[str, date]]:
    """
    Every domain's fetch returns a deterministic soft record over that
    domain's own variables. Returns the list of (domain_key, target_date)
    calls, so tests can check which dates an entry point asked for.
    """
    calls: list[tuple[str, date]] = []

    async def fetch(domain_key: str, target_date: date) -> EvidenceRecord:
        calls.append((domain_key, target_date))
        return soft_record(domain_variables(domain_key), target_date, seed=domain_key)

    patch_evidence_fetch(monkeypatch, fetch)
    return calls


def domain_keys() -> list[str]:
    return list(api_app._DOMAIN_MAP)


def domain_variables(domain_key: str) -> list[Variable]:
    engine = api_app.app.state.engines[domain_key]
    return engine.get_population().candidates[0].variables


def freeze_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr(api_app, "_utcnow", lambda: now)
