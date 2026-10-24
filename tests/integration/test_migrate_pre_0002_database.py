"""
REFACTOR_SPEC 3.3 / D1: a database written by the code on main before
population persistence (fixture generated with that code: legacy
{"true": p} soft-evidence keys, no schema_version table, signature-keyed
CPTs) must open, migrate, score its evidence once, and from then on resume
exactly. Its seed population is not resumed: the engine now starts with no
hypotheses (D24).
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
    # The old seeds are not resumed: the engine starts with no hypotheses
    # (D24), scored on the stored evidence.
    [start] = pop.active_candidates()
    assert start.edges == [] and start.evidence_count == 120
    assert math.isfinite(start.log_score)

    resumed = _open(db)
    assert normalize(population_state(resumed, DOMAIN_ID, detail=True)) == normalize(
        population_state(migrated, DOMAIN_ID, detail=True)
    )
