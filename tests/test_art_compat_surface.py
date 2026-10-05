"""
The art-market-domain package (pinned in pyproject.toml) reaches into engine
internals directly. Until REFACTOR_SPEC Phase 5.6 gives it a public hook, these
names are a contract: a refactor that renames one breaks the art domain in
production. This test fails first, with the name, instead.

Source of the list: grep of engine.* uses in art_prestige_regime_v1 at commit
f6327080. When Phase 5.6 lands, replace this with the public hook's tests.
"""
from __future__ import annotations

import importlib

import pytest

from src.domains.test_domain_v1.domain import TestDomainV1
from src.engine.engine import ProbabilisticOntologyEngine

MODULES_IMPORTED_BY_ART = ["src.engine.schemas", "src.engine.variable_identity", "src.engine.engine"]

ENGINE_SURFACE = [
    "_modules", "_batch_index", "_learn_call_count", "_learn_last_ts", "_learn_records_total",
    "register_domain", "activate_domain", "get_population", "ingest_batch", "learn",
    "evidence_store.count", "evidence_store.load_all", "evidence_store.clear",
    "population_store.update_score", "population_store.save_population",
    "population_manager._populations", "population_manager._last_mutation_stats",
    "population_manager._admissible_edges",
    "parameter_store.remove_candidate", "learning_service.initialize_candidate",
    # reset_art_learning_state finds these with getattr(..., None) and runs raw
    # DELETEs on ontology_candidates / ontology_populations / candidate_scores /
    # paradigm_shifts / parameters. If one is missing it silently skips the
    # delete and a re-registered domain would reload stale state.
    "population_store._conn", "parameter_store._conn",
]


@pytest.mark.parametrize("module", MODULES_IMPORTED_BY_ART)
def test_modules_art_imports_still_exist(module):
    importlib.import_module(module)


@pytest.mark.parametrize("path", ENGINE_SURFACE)
def test_engine_attributes_art_uses_still_exist(path, tmp_path):
    # A file DB: the in-memory ParameterStore has no connection today.
    engine = ProbabilisticOntologyEngine(db_path=str(tmp_path / "art.db"))
    engine.register_domain(TestDomainV1())
    obj = engine
    for part in path.split("."):
        assert hasattr(obj, part), f"art-market-domain uses engine.{path}"
        obj = getattr(obj, part)
