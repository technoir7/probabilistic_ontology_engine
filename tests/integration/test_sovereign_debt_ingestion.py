"""
Integration tests — sovereign debt domain ingestion pipeline.

Test inventory
--------------
TEST-SD-01  All 8 variable IDs are stable across module imports
TEST-SD-05  USD strong (DEXUSEU far below its mean) → DollarStrengthening high
TEST-SD-06  Active Fed QT → FedBalanceSheetShrinking high
TEST-SD-07  HY OAS above 6.5% → CreditDefaultRisk high
TEST-SD-08  HY OAS below 4.5% → CreditDefaultRisk low
TEST-SD-09  build_evidence_record maps all 8 variable UUIDs correctly
TEST-SD-10  build_evidence_record observes every variable exactly, at a level
TEST-SD-11  FRED client fetch_series with mocked HTTP returns correct observations
TEST-SD-12  FRED client skips missing (".") values
TEST-SD-13  compute_snapshot with no data gives no signal (all MISSING)
TEST-SD-15  Existence thresholds are within valid ranges
TEST-SD-16  Domain registers and activates in the engine
TEST-SD-18  Full pipeline fetch_evidence with mocked FREDClient
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.sources.grades import LEVELS, level_of
from src.domains.sovereign_debt_v1.domain import (
    SovereignDebtV1,
    get_variables,
)
from src.domains.sovereign_debt_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
    FRED_SERIES,
)
from src.domains.sovereign_debt_v1.ingestion.pipeline import (
    SovereignDebtPipeline,
    SovereignDebtSnapshot,
    compute_snapshot,
    _compute_fed_balance_sheet_shrinking,
    _compute_credit_default_risk,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


def _make_obs(series_id: str, values: list[float], base_date: date = _TARGET_DATE) -> list[FREDObservation]:
    return [
        FREDObservation(obs_date=base_date - timedelta(days=i), value=v, series_id=series_id)
        for i, v in enumerate(values)
    ]


def _make_full_observations(
    dgs10_current: float = 4.50,
    dgs10_mean: float = 3.50,
    hy_spread_current: float = 4.00,
    hy_spread_mean: float = 3.80,
    dexuseu_current: float = 1.05,   # lower = stronger USD
    dexuseu_mean: float = 1.10,
    walcl_now: float = 7_800.0,
    walcl_13w: float = 8_100.0,
    dtwexbgs_current: float = 110.0,
    dtwexbgs_mean: float = 100.0,
    gfdebtn_now: float = 34_000.0,
    gfdebtn_yr_ago: float = 32_000.0,
    m2sl_now: float = 20_000.0,
    m2sl_3m_ago: float = 20_400.0,
) -> dict[str, list[FREDObservation]]:
    import numpy as np
    rng = np.random.default_rng(42)

    # DGS10: 260 daily
    dgs10_values = [dgs10_mean] * 260
    dgs10_values[0] = dgs10_current
    dgs10_obs = _make_obs("DGS10", dgs10_values)

    # BAMLH0A0HYM2: 260 daily
    hy_values = (rng.normal(hy_spread_mean, 0.30, 260)).tolist()
    hy_values[0] = hy_spread_current
    hy_obs = _make_obs("BAMLH0A0HYM2", hy_values)

    # DEXUSEU: 260 daily
    dex_values = [dexuseu_mean] * 260
    dex_values[0] = dexuseu_current
    dex_obs = _make_obs("DEXUSEU", dex_values)

    # WALCL: 20 weekly
    walcl_values = [walcl_now] + [walcl_now - (walcl_now - walcl_13w) * i / 13 for i in range(1, 14)] + [walcl_13w] * 6
    walcl_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 7), value=walcl_values[i], series_id="WALCL")
        for i in range(20)
    ]

    # DTWEXBGS: 100 weekly
    dtwex_values = [dtwexbgs_mean] * 100
    dtwex_values[0] = dtwexbgs_current
    dtwex_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 7), value=dtwex_values[i], series_id="DTWEXBGS")
        for i in range(100)
    ]

    # GFDEBTN: quarterly — 8 quarters
    gfdebtn_obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 90),
            value=(gfdebtn_now if i == 0 else gfdebtn_yr_ago if i == 4 else
                   gfdebtn_now - (gfdebtn_now - gfdebtn_yr_ago) * i / 4),
            series_id="GFDEBTN",
        )
        for i in range(8)
    ]

    # M2SL: monthly — 6 months
    m2sl_values = [m2sl_now, m2sl_now, m2sl_now, m2sl_3m_ago, m2sl_3m_ago, m2sl_3m_ago]
    m2sl_obs = [
        FREDObservation(obs_date=_TARGET_DATE - timedelta(days=i * 30), value=m2sl_values[i], series_id="M2SL")
        for i in range(6)
    ]

    return {
        "DGS10": dgs10_obs,
        "BAMLH0A0HYM2": hy_obs,
        "DEXUSEU": dex_obs,
        "WALCL": walcl_obs,
        "DTWEXBGS": dtwex_obs,
        "GFDEBTN": gfdebtn_obs,
        "M2SL": m2sl_obs,
    }


# ---------------------------------------------------------------------------
# TEST-SD-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = SovereignDebtV1()
    domain_vars = {v.name: v.variable_id for v in domain.variables()}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == domain_vars[name]


# ---------------------------------------------------------------------------
# TEST-SD-05 — DollarStrengthening calibration
# ---------------------------------------------------------------------------

def test_a_high_ten_year_yield_is_us_yield_spiking():
    """DGS10 at 5.5 against a two-year mean near 3.5 → USYieldSpiking high."""
    from src.domains.sovereign_debt_v1.ingestion.pipeline import _compute_us_yield_spiking
    obs = [
        FREDObservation(obs_date=date(2024, 5, 3) - timedelta(days=i), value=(5.5 if i == 0 else 3.5),
                        series_id="DGS10")
        for i in range(400)
    ]
    sig, _ = _compute_us_yield_spiking(obs)
    assert sig is not None and level_of(sig) == "high"


def test_global_liquidity_from_one_series_is_that_series_not_a_third_less():
    """With M2 missing, the composite is the balance sheet's own signal: the
    missing half is not averaged in as a zero reading (D10, D25)."""
    from src.domains.sovereign_debt_v1.ingestion.pipeline import _compute_global_liquidity_contracting
    walcl = [FREDObservation(obs_date=date(2024, 5, 3) - timedelta(weeks=i), value=(97.0 if i == 0 else 100.0),
                             series_id="WALCL") for i in range(20)]
    alone, conf = _compute_global_liquidity_contracting(walcl, [])
    assert alone == pytest.approx(15.0)  # a 3% fall over 13 weeks, times 5
    assert conf == 0.5  # one of its two inputs


def test_strong_usd_produces_high_dollar_strengthening_p():
    """USD very strong (DEXUSEU far below mean) → DollarStrengthening high."""
    obs = _make_full_observations(dexuseu_current=0.95, dexuseu_mean=1.15)
    snap = compute_snapshot(obs, _TARGET_DATE)
    assert level_of(snap.signals["DollarStrengthening"]) == "high"


# ---------------------------------------------------------------------------
# TEST-SD-06 — FedBalanceSheetShrinking calibration
# ---------------------------------------------------------------------------

def test_active_qt_produces_high_fed_shrinking_p():
    """WALCL falls 3% over 13 weeks (active QT) → FedBalanceSheetShrinking high."""
    walcl_values = [7_800.0] + [7_900.0 + 15.0 * i for i in range(13)] + [8_100.0] * 6
    obs = [
        FREDObservation(
            obs_date=_TARGET_DATE - timedelta(days=i * 7),
            value=walcl_values[i],
            series_id="WALCL",
        )
        for i in range(20)
    ]
    sig, _ = _compute_fed_balance_sheet_shrinking(obs)
    assert sig is not None
    assert level_of(sig) == "high"


# ---------------------------------------------------------------------------
# TEST-SD-07 & 08 — CreditDefaultRisk calibration
# ---------------------------------------------------------------------------

def test_high_hy_spread_produces_high_credit_default_risk():
    """BAMLH0A0HYM2 = 7.0% (above 6.0% threshold) → CreditDefaultRisk high."""
    obs = _make_obs("BAMLH0A0HYM2", [7.0] * 5)
    sig, _ = _compute_credit_default_risk(obs)
    assert sig is not None
    assert level_of(sig) == "high"


def test_low_hy_spread_produces_low_credit_default_risk():
    """BAMLH0A0HYM2 = 3.5% (well below threshold) → CreditDefaultRisk low."""
    obs = _make_obs("BAMLH0A0HYM2", [3.5] * 5)
    sig, _ = _compute_credit_default_risk(obs)
    assert sig is not None
    assert level_of(sig) == "low"


# ---------------------------------------------------------------------------
# TEST-SD-09 — build_evidence_record maps all 8 variable UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids


# ---------------------------------------------------------------------------
# TEST-SD-10 — Every variable observed exactly, at a level
# ---------------------------------------------------------------------------

def test_build_evidence_record_observes_every_variable_at_a_level():
    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.OBSERVED
        assert a.probabilities is None
        assert a.observed_value in LEVELS


# ---------------------------------------------------------------------------
# TEST-SD-11 — FRED client with mocked HTTP
# ---------------------------------------------------------------------------

def test_fred_client_fetch_series_returns_observations():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "4.50"},
            {"date": "2024-05-02", "value": "4.45"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("DGS10", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert result[0].obs_date == date(2024, 5, 3)
    assert result[0].value == 4.50
    assert result[0].series_id == "DGS10"


# ---------------------------------------------------------------------------
# TEST-SD-12 — FRED client skips missing values
# ---------------------------------------------------------------------------

def test_fred_client_skips_missing_values():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "observations": [
            {"date": "2024-05-03", "value": "4.50"},
            {"date": "2024-05-02", "value": "."},
            {"date": "2024-05-01", "value": "4.40"},
        ]
    })
    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)
    client = FREDClient(api_key="test-key", client=http_mock)
    result = asyncio.run(client.fetch_series("DGS10", end_date=date(2024, 5, 3)))
    assert len(result) == 2
    assert date(2024, 5, 2) not in {o.obs_date for o in result}


# ---------------------------------------------------------------------------
# TEST-SD-13 — No data: no signal, so every variable is MISSING
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_gracefully_with_no_data():
    """No input is MISSING, never a middle reading."""
    assert compute_snapshot({}, _TARGET_DATE).signals == {}


def test_compute_snapshot_partial_data_leaves_the_rest_missing():
    full = _make_full_observations()
    snapshot = compute_snapshot({"DGS10": full["DGS10"]}, _TARGET_DATE)

    assert set(snapshot.signals) == {"USYieldSpiking"}
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    missing = [a for a in record.observed_assignments if a.missingness == MissingnessType.MISSING]
    assert len(missing) == 7


# ---------------------------------------------------------------------------
# TEST-SD-15 — Existence thresholds are valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    domain = SovereignDebtV1()
    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-SD-16 — Domain registers in the engine
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = SovereignDebtV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert [(c.edges, c.lineage) for c in pop.active_candidates()] == [([], "unconnected")]

    observations = _make_full_observations()
    snapshot = compute_snapshot(observations, _TARGET_DATE)
    record = SovereignDebtPipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-SD-18 — Full pipeline fetch_evidence with mocked FREDClient
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    mock_fred = AsyncMock(spec=FREDClient)
    observations = _make_full_observations(
        walcl_now=7_800.0,   # QT → FedBalanceSheetShrinking high
        walcl_13w=8_100.0,
        hy_spread_current=7.0,  # > 6.0% threshold → CreditDefaultRisk high
    )
    mock_fred.fetch_all_series = AsyncMock(return_value=observations)

    pipeline = SovereignDebtPipeline(mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}
    assert "FRED" in record.source_ref

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.OBSERVED
    amap = {a.variable_id: a.observed_value for a in record.observed_assignments}
    assert amap[variables["FedBalanceSheetShrinking"].variable_id] == "high"
    assert amap[variables["CreditDefaultRisk"].variable_id] == "high"

    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)
