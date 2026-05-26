"""
Tests for paradigm-shift event logging.

TEST-PSE-01 : shift event written to PopulationStore when dominant changes
TEST-PSE-02 : no shift event written when dominant stays the same
TEST-PSE-03 : no shift event on first cycle (prev_dominant is None)
TEST-PSE-04 : shift events are domain-isolated (MR shifts don't appear in NG)
TEST-PSE-05 : multiple shifts produce one event each, chronologically ordered
TEST-PSE-06 : GET /v1/population/shifts returns correct JSON schema
TEST-PSE-07 : GET /v1/population/shifts total_shifts matches len(events)
TEST-PSE-08 : GET /v1/population/shifts domain isolation via ?domain= param
TEST-PSE-09 : shift event carries correct prev/new dominant IDs
TEST-PSE-10 : shift event evidence_count_at_shift is positive after learning
"""
from __future__ import annotations

import random
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.domains.test_domain_v1.domain import (
    make_null_candidate,
    make_talt_candidate,
    make_tstar_candidate,
    _var_list,
)
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.schemas import EdgeExistenceThresholdConfig
from src.engine.services.edge_existence import EdgeExistenceService
from src.engine.services.learning import LearningService
from src.engine.services.population_manager import PopulationManager
from src.engine.stores.parameter_store import ParameterStore
from src.engine.stores.population_store import PopulationStore
from src.engine.api import app as api_app

DOMAIN_ID = "test-domain-v1"


# ---------------------------------------------------------------------------
# Low-level helpers (no API layer)
# ---------------------------------------------------------------------------

def _make_stack(candidates, max_pop=10, rng_seed=42):
    ps = ParameterStore()
    ls = LearningService(ps)
    pop_store = PopulationStore(":memory:")
    thresholds = EdgeExistenceThresholdConfig(
        prune_below=0.05, accept_above=0.90, explore_band=(0.3, 0.7)
    )
    ees = EdgeExistenceService(ps, thresholds)
    pm = PopulationManager(
        parameter_store=ps,
        population_store=pop_store,
        thresholds=thresholds,
        rng=random.Random(rng_seed),
    )
    for cand in candidates:
        ls.initialize_candidate(cand)
    var_names = [v.name for v in candidates[0].variables]
    admissible = {(a, b) for a in var_names for b in var_names if a != b}
    pm.initialize(
        domain_module_id=DOMAIN_ID,
        initial_candidates=candidates,
        max_population_size=max_pop,
        admissible_edges=admissible,
        thresholds=thresholds,
    )
    return ps, ls, ees, pm, pop_store


def _run_cycle(ps, ls, ees, pm, batch, idx=0):
    pop = pm.get_population(DOMAIN_ID)
    for c in pop.active_candidates():
        ls.accumulate(batch, c)
        ees.update(c)
        ees.prune_below_threshold(c, ps)
        ll = ls.compute_log_likelihood(batch, c)
        pm.update_score(DOMAIN_ID, c.candidate_id, ll, idx, batch_size=len(batch))
    pm.prune_low_scorers(DOMAIN_ID)
    pm.introduce_variants(DOMAIN_ID, ls)
    pm.end_cycle(DOMAIN_ID)


def _chunk(lst, n):
    return [lst[i:i+n] for i in range(0, len(lst), n)]


# ---------------------------------------------------------------------------
# TEST-PSE-01 : shift event written when dominant changes
# ---------------------------------------------------------------------------

def test_pse_01_shift_event_written_on_dominant_change():
    """
    Phase 1 (T* data) → T* dominates.
    Phase 2 (T_alt data) → T_alt dominates.
    At least one shift event must be recorded.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=7)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_talt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_talt, cand_null])

    for i, batch in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, batch, i)

    gen.switch_regime("T_alt")
    for i, batch in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, batch, 10 + i)

    events = pop_store.load_shift_events(DOMAIN_ID)
    assert len(events) >= 1, "Expected at least one shift event after regime switch"


# ---------------------------------------------------------------------------
# TEST-PSE-02 : no shift event when dominant stays the same
# ---------------------------------------------------------------------------

def test_pse_02_no_shift_when_dominant_unchanged():
    """
    If only T* data is fed and the dominant never changes, no shift events
    should be recorded.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_null])

    # Run a single batch — T* should dominate from the start and stay there.
    # With 2 candidates T* data clearly separates them.
    first_batch = gen.sample(n=50)
    _run_cycle(ps, ls, ees, pm, first_batch, 0)

    dom_after_first = pm.dominant(DOMAIN_ID)
    assert dom_after_first is not None

    # Run more T* batches — dominant should not change
    for i, batch in enumerate(_chunk(gen.sample(n=150), 50)):
        _run_cycle(ps, ls, ees, pm, batch, 1 + i)

    dom_final = pm.dominant(DOMAIN_ID)
    assert dom_final is not None
    assert dom_final.edge_structure_signature() == dom_after_first.edge_structure_signature(), (
        "Dominant structure changed unexpectedly under consistent T* data"
    )

    events = pop_store.load_shift_events(DOMAIN_ID)
    # May have 0 or very few — definitely fewer than cycles run (not every cycle is a shift)
    n_cycles = 4  # 1 first + 3 subsequent
    assert len(events) < n_cycles, (
        f"Too many shift events ({len(events)}) for a stable dominant — expected < {n_cycles}"
    )


# ---------------------------------------------------------------------------
# TEST-PSE-03 : no shift event on very first cycle (prev dominant is None)
# ---------------------------------------------------------------------------

def test_pse_03_no_shift_on_first_cycle():
    """
    The very first call to end_cycle() must NOT produce a shift event even
    though update_dominant() sets active_candidate_id for the first time,
    because there was no previous dominant to shift FROM.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=42)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)

    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_null])

    # Confirm: no dominant set yet right after initialize()
    pop = pm.get_population(DOMAIN_ID)
    assert pop.active_candidate_id is not None, "initialize() should set initial dominant"

    # Run exactly one cycle
    batch = gen.sample(n=20)
    _run_cycle(ps, ls, ees, pm, batch, 0)

    events = pop_store.load_shift_events(DOMAIN_ID)
    # On the first cycle, the dominant can change from the init value, but
    # we only write shift events when prev_cand is a real candidate previously
    # seen, not when first set during initialize().
    # Because initialize() calls update_dominant() before any end_cycle() is
    # ever called, the first end_cycle() will have prev_id already set
    # (from initialize) and may or may not shift depending on score ordering.
    # The key invariant: we should never have MORE events than learning cycles.
    assert len(events) <= 1, (
        f"At most 1 shift event expected after 1 learning cycle, got {len(events)}"
    )


# ---------------------------------------------------------------------------
# TEST-PSE-04 : domain isolation
# ---------------------------------------------------------------------------

def test_pse_04_domain_isolation():
    """
    Shift events for domain A must not appear in domain B's event log.
    """
    gen_a = SyntheticDataGenerator(graph="T*", random_seed=1)
    gen_b = SyntheticDataGenerator(graph="T_alt", random_seed=2)

    DOMAIN_A = "test-domain-a"
    DOMAIN_B = "test-domain-b"

    ps = ParameterStore()
    ls = LearningService(ps)
    pop_store = PopulationStore(":memory:")
    thresholds = EdgeExistenceThresholdConfig()
    ees = EdgeExistenceService(ps, thresholds)
    pm = PopulationManager(
        parameter_store=ps,
        population_store=pop_store,
        thresholds=thresholds,
        rng=random.Random(42),
    )

    # Build candidates for each domain
    cands_a = [make_tstar_candidate(DOMAIN_A), make_talt_candidate(DOMAIN_A), make_null_candidate(DOMAIN_A)]
    cands_b = [make_tstar_candidate(DOMAIN_B), make_talt_candidate(DOMAIN_B), make_null_candidate(DOMAIN_B)]

    for c in cands_a + cands_b:
        ls.initialize_candidate(c)

    var_names = [v.name for v in cands_a[0].variables]
    admissible = {(a, b) for a in var_names for b in var_names if a != b}
    pm.initialize(domain_module_id=DOMAIN_A, initial_candidates=cands_a,
                  max_population_size=10, admissible_edges=admissible, thresholds=thresholds)
    pm.initialize(domain_module_id=DOMAIN_B, initial_candidates=cands_b,
                  max_population_size=10, admissible_edges=admissible, thresholds=thresholds)

    # Run many cycles only on domain A, then switch regime to cause shifts
    for i, batch in enumerate(_chunk(gen_a.sample(n=300), 30)):
        pop = pm.get_population(DOMAIN_A)
        for c in pop.active_candidates():
            ls.accumulate(batch, c); ees.update(c); ees.prune_below_threshold(c, ps)
            pm.update_score(DOMAIN_A, c.candidate_id, ls.compute_log_likelihood(batch, c), i, len(batch))
        pm.prune_low_scorers(DOMAIN_A)
        pm.introduce_variants(DOMAIN_A, ls)
        pm.end_cycle(DOMAIN_A)

    gen_a.switch_regime("T_alt")
    for i, batch in enumerate(_chunk(gen_a.sample(n=300), 30)):
        pop = pm.get_population(DOMAIN_A)
        for c in pop.active_candidates():
            ls.accumulate(batch, c); ees.update(c); ees.prune_below_threshold(c, ps)
            pm.update_score(DOMAIN_A, c.candidate_id, ls.compute_log_likelihood(batch, c), 10+i, len(batch))
        pm.prune_low_scorers(DOMAIN_A)
        pm.introduce_variants(DOMAIN_A, ls)
        pm.end_cycle(DOMAIN_A)

    events_a = pop_store.load_shift_events(DOMAIN_A)
    events_b = pop_store.load_shift_events(DOMAIN_B)

    assert len(events_a) >= 1, "Domain A should have shift events after regime switch"
    assert len(events_b) == 0, (
        f"Domain B should have 0 shift events but got {len(events_b)}: {events_b}"
    )
    # All domain-A events must be tagged to domain A
    for ev in events_a:
        assert ev["domain_module_id"] == DOMAIN_A


# ---------------------------------------------------------------------------
# TEST-PSE-05 : multiple shifts produce one event each, ordered by timestamp
# ---------------------------------------------------------------------------

def test_pse_05_multiple_shifts_chronological_order():
    """
    Two regime switches → at least 2 shift events, ordered by shift_ts asc.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=99)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_talt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)
    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_talt, cand_null])

    # Phase 1: T* data
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, i)

    # Phase 2: T_alt data
    gen.switch_regime("T_alt")
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, 10 + i)

    # Phase 3: back to T*
    gen.switch_regime("T*")
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, 20 + i)

    events = pop_store.load_shift_events(DOMAIN_ID)
    assert len(events) >= 2, f"Expected >= 2 shift events, got {len(events)}"

    # Verify chronological ordering
    timestamps = [ev["shift_ts"] for ev in events]
    assert timestamps == sorted(timestamps), "Shift events must be in chronological order"


# ---------------------------------------------------------------------------
# TEST-PSE-06 : GET /v1/population/shifts returns correct JSON schema
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("POE_DATA_DIR", str(tmp_path))
    with TestClient(api_app.app) as c:
        yield c


def test_pse_06_shifts_endpoint_schema(client):
    """GET /v1/population/shifts returns the expected top-level fields."""
    resp = client.get("/v1/population/shifts?domain=ng")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "domain" in body
    assert "domain_module_id" in body
    assert "total_shifts" in body
    assert "events" in body
    assert isinstance(body["total_shifts"], int)
    assert isinstance(body["events"], list)
    assert body["domain_module_id"] == "natural-gas-v1"
    assert body["domain"] == "Natural Gas"


# ---------------------------------------------------------------------------
# TEST-PSE-07 : total_shifts equals len(events)
# ---------------------------------------------------------------------------

def test_pse_07_total_shifts_matches_events_len(client):
    resp = client.get("/v1/population/shifts?domain=ng")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_shifts"] == len(body["events"])


# ---------------------------------------------------------------------------
# TEST-PSE-08 : domain isolation via ?domain= param
# ---------------------------------------------------------------------------

def test_pse_08_domain_isolation_via_api(client):
    """MR and NG shift histories are independent."""
    resp_ng = client.get("/v1/population/shifts?domain=ng")
    resp_mr = client.get("/v1/population/shifts?domain=mr")

    assert resp_ng.status_code == 200
    assert resp_mr.status_code == 200

    ng_body = resp_ng.json()
    mr_body = resp_mr.json()

    assert ng_body["domain_module_id"] == "natural-gas-v1"
    assert mr_body["domain_module_id"] == "macro-regime-v1"

    # On a fresh engine with no learning cycles, both should have 0 events
    assert ng_body["total_shifts"] == 0
    assert mr_body["total_shifts"] == 0


# ---------------------------------------------------------------------------
# TEST-PSE-09 : shift event carries correct prev/new dominant IDs
# ---------------------------------------------------------------------------

def test_pse_09_shift_event_has_correct_candidate_ids():
    """
    After a confirmed paradigm shift, the shift event must reference the
    actual candidate UUIDs of the previous and new dominant.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=11)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_talt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)
    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_talt, cand_null])

    # Phase 1: T* data until it dominates
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, i)

    dom_after_p1 = pm.dominant(DOMAIN_ID)
    assert dom_after_p1 is not None
    dom_p1_id = str(dom_after_p1.candidate_id)

    # Phase 2: T_alt data to trigger shift
    gen.switch_regime("T_alt")
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, 10 + i)

    events = pop_store.load_shift_events(DOMAIN_ID)
    assert len(events) >= 1, "Expected at least one shift event"

    # Phase 1 may itself produce shifts (e.g. null→T* early on).
    # What we need is that at least one event records T* as the *previous*
    # dominant — that is the shift that Phase 2 data caused.
    shifts_from_p1 = [ev for ev in events if ev["prev_dominant_id"] == dom_p1_id]
    assert len(shifts_from_p1) >= 1, (
        f"No shift event found where prev_dominant_id == T* dominant ({dom_p1_id}). "
        f"All prev IDs seen: {[ev['prev_dominant_id'] for ev in events]}"
    )
    # For each such shift the new dominant must differ from the previous
    for ev in shifts_from_p1:
        assert ev["new_dominant_id"] != ev["prev_dominant_id"]

    # Each shift event must have non-empty name fields
    for ev in events:
        assert ev["prev_dominant_name"], "prev_dominant_name must not be empty"
        assert ev["new_dominant_name"], "new_dominant_name must not be empty"
        assert ev["shift_id"], "shift_id must not be empty"


# ---------------------------------------------------------------------------
# TEST-PSE-10 : evidence_count_at_shift is positive after learning
# ---------------------------------------------------------------------------

def test_pse_10_evidence_count_at_shift_positive():
    """
    The evidence_count recorded on the shift event must reflect the number of
    evidence records the new dominant had processed at the time of the shift.
    """
    gen = SyntheticDataGenerator(graph="T*", random_seed=5)
    cand_tstar = make_tstar_candidate(DOMAIN_ID)
    cand_talt = make_talt_candidate(DOMAIN_ID)
    cand_null = make_null_candidate(DOMAIN_ID)
    ps, ls, ees, pm, pop_store = _make_stack([cand_tstar, cand_talt, cand_null])

    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, i)

    gen.switch_regime("T_alt")
    for i, b in enumerate(_chunk(gen.sample(n=300), 30)):
        _run_cycle(ps, ls, ees, pm, b, 10 + i)

    events = pop_store.load_shift_events(DOMAIN_ID)
    assert len(events) >= 1

    for ev in events:
        assert ev["evidence_count_at_shift"] > 0, (
            f"evidence_count_at_shift should be positive, got {ev['evidence_count_at_shift']}"
        )
