"""
Shared pytest fixtures.
"""
from __future__ import annotations

import sys
import os
# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
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


def pytest_configure(config):
    # The app's lifespan loads .env; keep a developer's real keys out of tests.
    os.environ["POE_LOAD_DOTENV"] = "0"


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _sealed_runtime(request, monkeypatch, tmp_path):
    """
    Every test gets its own data dir, no schedulers, and no real HTTP.

    Without this, a test that forgets POE_DATA_DIR writes SQLite files into the
    cwd, and a test that forgets to fake a fetch silently calls EIA/FRED/etc.
    Only the real network transports are blocked, so TestClient and
    httpx.MockTransport keep working. Tests marked ``live`` are exempt.
    """
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path / "poe_data"))
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    if "live" in request.keywords:
        return

    def _refuse(self, req, *args, **kwargs):
        raise NetworkBlocked(f"test tried to reach the network: {req.method} {req.url}")

    async def _refuse_async(self, req, *args, **kwargs):
        _refuse(self, req)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refuse_async)


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
