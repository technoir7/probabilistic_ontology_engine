"""
Shared pytest fixtures.
"""
from __future__ import annotations

import sys
import os
# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from src.domains.test_domain_v1.domain import (
    TestDomainV1,
    make_null_candidate,
    make_spurious_1_candidate,
    make_spurious_2_candidate,
    make_talt_candidate,
    make_tstar_candidate,
    T_STAR_EDGES,
    T_ALT_EDGES,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import OntologyCandidate, OntologyPopulation


def chunk(lst: list, size: int) -> list[list]:
    """Split a list into chunks of `size`."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


@pytest.fixture
def generator():
    return SyntheticDataGenerator(graph="T*", random_seed=42)


@pytest.fixture
def engine_with_test_domain():
    eng = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = TestDomainV1()
    eng.register_domain(domain)
    eng.activate_domain(domain.module_id())
    return eng


@pytest.fixture
def tstar_candidate():
    return make_tstar_candidate()


@pytest.fixture
def talt_candidate():
    return make_talt_candidate()
