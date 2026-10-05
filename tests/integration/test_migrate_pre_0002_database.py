"""
REFACTOR_SPEC 3.3 / D1: a database written by the code on main before
population persistence (fixture generated with that code: legacy
{"true": p} soft-evidence keys, no schema_version table, signature-keyed
CPTs) must open, migrate, restore seed CPTs and correct scores once, and
from then on resume exactly.
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

from src.domains.test_domain_v1.domain import TestDomainV1
from src.engine.engine import ProbabilisticOntologyEngine
from tests.golden.probe import population_state
from tests.golden.snapshot import normalize

FIXTURE = Path(__file__).parents[1] / "fixtures" / "pre_0002_test_domain.db"
DOMAIN_ID = "test-domain-v1"


def _open(path) -> ProbabilisticOntologyEngine:
    engine = ProbabilisticOntologyEngine(db_path=str(path))
    engine.register_domain(TestDomainV1())
    engine.activate_domain(DOMAIN_ID)
    return engine


def test_pre_0002_database_migrates_then_resumes(tmp_path):
    db = tmp_path / "prod_like.db"
    shutil.copy(FIXTURE, db)

    migrated = _open(db)
    assert migrated.db.schema_version() >= 2
    pop = migrated.get_population(DOMAIN_ID)
    by_name = {c.description: c for c in pop.active_candidates()}
    assert set(by_name) == {"T*", "T_alt", "null"}
    for cand in by_name.values():
        assert cand.evidence_count == 120
        assert math.isfinite(cand.log_score)
    # With the legacy string keys read as strings, T* and T_alt scored identically.
    assert by_name["T*"].log_score != by_name["T_alt"].log_score
    assert by_name["T*"].log_score > by_name["null"].log_score
    # Seed CPTs restored from the old signature-keyed table, not reset to empty.
    assert sum(cpt.total_count() for cpt in migrated.parameter_store.get_all_for_candidate(by_name["T*"].candidate_id).values()) > 0

    resumed = _open(db)
    assert normalize(population_state(resumed, DOMAIN_ID, detail=True)) == normalize(
        population_state(migrated, DOMAIN_ID, detail=True)
    )
