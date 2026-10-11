"""
Request-time access to the running domains: which engine serves a domain key,
its ingest lock, fetching its evidence, and the clock.

``fetch_evidence_record`` and ``utcnow`` are the seams tests replace
(tests/fakes.py); other modules call them as ``context.<name>`` so a
replacement applies everywhere.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from ..engine import ProbabilisticOntologyEngine
from ..runtime.ingestion import ingest_and_learn
from ..runtime.registry import BY_KEY, REGISTRY
from ..runtime.settings import Settings
from ..schemas import EvidenceRecord, OntologyCandidate

# Short name → (domain_module_id, display_name)
DOMAIN_MAP: dict[str, tuple[str, str]] = {r.key: (r.module_id, r.display_name) for r in REGISTRY}


def utcnow() -> datetime:
    # Single wall-clock read for the API so tests can pin "today"
    # (tests/fakes.py:freeze_clock).
    return datetime.now(timezone.utc)


def resolve_domain(
    short_name: str,
    state: Any,
) -> tuple[ProbabilisticOntologyEngine, str, str]:
    """Return (engine, domain_module_id, display_name) or raise HTTP 404/503."""
    key = short_name.lower()
    if key not in DOMAIN_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{short_name}'")
    domain_id, display_name = DOMAIN_MAP[key]
    engines: dict[str, ProbabilisticOntologyEngine] = getattr(state, "engines", {})
    if key not in engines:
        raise HTTPException(status_code=503, detail=f"Domain '{key}' engine not initialised")
    return engines[key], domain_id, display_name


def build_engine(domain_module: Any, db_path: Path) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=str(db_path), random_seed=42)
    engine.register_domain(domain_module)
    engine.activate_domain(domain_module.module_id())
    return engine


def default_art_manual_dir(manual_ingest_module: Any) -> Path:
    return Path(manual_ingest_module.__file__).resolve().parents[2] / "data" / "manual_ingest"


def resolve_query_candidate(
    pop: Any,
    raw_candidate_id: str | None,
) -> OntologyCandidate:
    active = pop.active_candidates()
    if not active:
        raise HTTPException(status_code=503, detail="No active candidates")

    if not raw_candidate_id:
        cand = pop.dominant()
        if cand is None:
            raise HTTPException(status_code=503, detail="No active candidates")
        return cand

    raw = raw_candidate_id.strip()
    for cand in active:
        label = getattr(cand, "label", None)
        if str(cand.candidate_id) == raw or label == raw:
            return cand

    try:
        target_uuid = UUID(raw)
    except ValueError:
        cand = pop.dominant()
        return cand or active[0]

    for cand in active:
        if cand.candidate_id == target_uuid:
            return cand

    raise HTTPException(status_code=404, detail=f"Candidate '{raw_candidate_id}' not found")


def ingest_lock(state: Any, domain_key: str) -> asyncio.Lock:
    locks: dict[str, asyncio.Lock] = getattr(state, "ingest_locks", {})
    if domain_key not in locks:
        locks[domain_key] = asyncio.Lock()
        state.ingest_locks = locks
    return locks[domain_key]


async def fetch_evidence_record(domain_key: str, target_date: date) -> EvidenceRecord:
    if domain_key not in BY_KEY:
        raise ValueError(f"Unknown domain '{domain_key}'")
    settings = Settings.from_env()  # API keys as of this request
    settings.require_env(BY_KEY[domain_key])
    async with BY_KEY[domain_key].open_source(settings.environ) as source:
        return await source.fetch_evidence(target_date)


async def ingest_domain_evidence(
    *,
    domain_key: str,
    engine: ProbabilisticOntologyEngine,
    domain_id: str,
    target_date: date | None = None,
) -> int:
    cadence = BY_KEY[domain_key].cadence
    target_date = cadence.default_target(utcnow().date()) if target_date is None else cadence.align(target_date)
    return await ingest_and_learn(
        engine,
        domain_id,
        fetcher(domain_key),
        target_date,
        skip_unchanged_state=BY_KEY[domain_key].skip_unchanged_state,
    )


def fetcher(domain_key: str):
    # Looks fetch_evidence_record up at call time: tests replace it (tests/fakes.py).
    return lambda target: fetch_evidence_record(domain_key, target)
