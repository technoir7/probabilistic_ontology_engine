"""
Integration tests — crypto regime domain ingestion pipeline.

Test inventory
--------------
TEST-CR-01  Variable IDs stable across imports
TEST-CR-02  All 5 candidates are valid DAGs
TEST-CR-03  All candidates share same variable set
TEST-CR-04  _soft_bool clamped to [0.01, 0.99]
TEST-CR-05  compute_snapshot falls back to 0.5 with empty data
TEST-CR-06  BTC positive 13w return → P(BTCMomentumPositive) > 0.5
TEST-CR-07  BTC negative 13w return → P(BTCMomentumPositive) < 0.5
TEST-CR-08  Low BTC dominance (40%) → P(AltcoinSeasonActive) > 0.5
TEST-CR-09  High BTC dominance (65%) → P(AltcoinSeasonActive) < 0.5
TEST-CR-10  build_evidence_record maps all 8 UUIDs
TEST-CR-11  build_evidence_record produces SOFT_OBSERVED
TEST-CR-12  Domain module_id matches candidates
TEST-CR-13  Existence thresholds valid
TEST-CR-14  Domain registers in engine, evidence ingested
TEST-CR-15  Candidates have distinct edge structures
TEST-CR-16  CoinGeckoClient parses mocked market chart response
TEST-CR-17  Full pipeline fetch_evidence with all mocked clients
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, timedelta, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from src.domains.crypto_regime_v1.domain import (
    CryptoRegimeV1,
    get_variables,
    make_liquidity_overflow_candidate,
    make_digital_gold_candidate,
    make_speculative_mania_candidate,
    make_utility_adoption_candidate,
    make_null_candidate,
)
from src.domains.crypto_regime_v1.ingestion.coingecko_client import (
    CoinGeckoClient,
    CGObs,
    CGGlobal,
)
from src.domains.crypto_regime_v1.ingestion.yfinance_client import (
    CryptoYFinanceClient,
    CryptoYFObs,
)
from src.domains.crypto_regime_v1.ingestion.fred_client import (
    FREDClient,
    FREDObservation,
)
from src.domains.crypto_regime_v1.ingestion.pipeline import (
    CryptoRegimePipeline,
    CryptoRegimeSnapshot,
    compute_snapshot,
    _soft_bool,
    _sigmoid,
)
from src.engine.engine import ProbabilisticOntologyEngine
from src.engine.schemas import EvidenceRecord, MissingnessType

_TARGET_DATE = date(2024, 5, 3)  # a Friday


def _make_btc_obs(
    num_days: int = 365,
    base_price: float = 60_000.0,
    trend: float = 0.0,
) -> list[CGObs]:
    """Create synthetic BTC observations, newest first."""
    obs = []
    for i in range(num_days):
        d = _TARGET_DATE - timedelta(days=i)
        price = base_price * (1.0 + trend * i / num_days)
        obs.append(CGObs(
            obs_date=d,
            price_usd=price,
            market_cap_usd=price * 19_000_000,
            volume_usd=30_000_000_000.0,
            coin_id="bitcoin",
        ))
    return obs


def _make_eth_obs(
    num_days: int = 365,
    base_price: float = 3_000.0,
) -> list[CGObs]:
    """Create synthetic ETH observations, newest first."""
    obs = []
    for i in range(num_days):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(CGObs(
            obs_date=d,
            price_usd=base_price,
            market_cap_usd=base_price * 120_000_000,
            volume_usd=10_000_000_000.0,
            coin_id="ethereum",
        ))
    return obs


def _make_stable_obs(coin_id: str, num_days: int = 90, base_mcap: float = 80e9) -> list[CGObs]:
    obs = []
    for i in range(num_days):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(CGObs(
            obs_date=d,
            price_usd=1.0,
            market_cap_usd=base_mcap,
            volume_usd=5_000_000_000.0,
            coin_id=coin_id,
        ))
    return obs


def _make_yf_obs(ticker: str, num_days: int = 730, base_price: float = 100.0) -> list[CryptoYFObs]:
    obs = []
    for i in range(num_days):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(CryptoYFObs(obs_date=d, close_price=base_price, ticker=ticker))
    return obs


def _make_fred_obs(
    series_id: str = "DEXUSEU",
    num_obs: int = 260,
    base_value: float = 1.10,
) -> list[FREDObservation]:
    obs = []
    for i in range(num_obs):
        d = _TARGET_DATE - timedelta(days=i)
        obs.append(FREDObservation(obs_date=d, value=base_value, series_id=series_id))
    return obs


def _make_full_data(
    btc_trend: float = 0.0,
    btc_dominance: float = 52.0,
    btc_price: float = 60_000.0,
) -> tuple[dict, dict, dict]:
    cg_data = {
        "btc": _make_btc_obs(365, btc_price, btc_trend),
        "eth": _make_eth_obs(365, 3_000.0),
        "global": CGGlobal(btc_dominance_pct=btc_dominance, total_market_cap_usd=2_500_000_000_000.0),
        "usdt": _make_stable_obs("tether", 90, 80e9),
        "usdc": _make_stable_obs("usd-coin", 90, 30e9),
    }
    yf_data = {
        "BTC-USD": _make_yf_obs("BTC-USD", 730, 60_000.0),
        "QQQ": _make_yf_obs("QQQ", 730, 400.0),
        "GLD": _make_yf_obs("GLD", 730, 180.0),
    }
    fred_data = {
        "DEXUSEU": _make_fred_obs("DEXUSEU", 260, 1.10),
    }
    return cg_data, yf_data, fred_data


# ---------------------------------------------------------------------------
# TEST-CR-01 — Stable variable IDs
# ---------------------------------------------------------------------------

def test_variable_ids_are_stable():
    vars1 = get_variables()
    vars2 = get_variables()
    domain = CryptoRegimeV1()
    cands = domain.initial_candidates()
    cand_vars = {v.name: v.variable_id for v in cands[0].variables}
    for name in vars1:
        assert vars1[name].variable_id == vars2[name].variable_id
        assert vars1[name].variable_id == cand_vars[name]


# ---------------------------------------------------------------------------
# TEST-CR-02 — All 5 candidates are valid DAGs
# ---------------------------------------------------------------------------

def test_all_candidates_are_dags():
    factories = [
        make_liquidity_overflow_candidate,
        make_digital_gold_candidate,
        make_speculative_mania_candidate,
        make_utility_adoption_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        assert cand.is_dag(), f"Candidate '{cand.description}' violates DAG constraint"


# ---------------------------------------------------------------------------
# TEST-CR-03 — All candidates share the canonical variable set
# ---------------------------------------------------------------------------

def test_all_candidates_share_variable_set():
    expected_names = set(get_variables().keys())
    expected_ids = {v.variable_id for v in get_variables().values()}
    factories = [
        make_liquidity_overflow_candidate,
        make_digital_gold_candidate,
        make_speculative_mania_candidate,
        make_utility_adoption_candidate,
        make_null_candidate,
    ]
    for factory in factories:
        cand = factory()
        cand_names = {v.name for v in cand.variables}
        assert cand_names == expected_names
        assert {v.variable_id for v in cand.variables} == expected_ids


# ---------------------------------------------------------------------------
# TEST-CR-04 — _soft_bool clamped to [0.01, 0.99]
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("signal", [-100.0, -10.0, 0.0, 10.0, 100.0])
def test_soft_bool_clamped(signal: float):
    result = _soft_bool(signal)
    assert 0.01 <= result <= 0.99
    assert not math.isnan(result)


# ---------------------------------------------------------------------------
# TEST-CR-05 — compute_snapshot falls back to 0.5 with empty data
# ---------------------------------------------------------------------------

def test_compute_snapshot_falls_back_with_empty_data():
    snap = compute_snapshot({}, {}, {}, _TARGET_DATE)
    assert snap.p_btc_momentum_positive == 0.5
    assert snap.p_altcoin_season_active == 0.5
    assert snap.p_onchain_activity_elevated == 0.5
    assert snap.p_stablecoin_flow_positive == 0.5
    assert snap.p_crypto_volatility_shock == 0.5
    assert snap.p_risk_asset_correlation == 0.5
    assert snap.p_narrative_momentum == 0.5
    assert snap.p_dollar_debasement_narrative == 0.5


# ---------------------------------------------------------------------------
# TEST-CR-06 — BTC positive return → P(BTCMomentumPositive) > 0.5
# ---------------------------------------------------------------------------

def test_btc_positive_return_drives_momentum_high():
    """BTC price much higher now than 90 days ago → positive 13w return → P(BTCMomentumPositive) > 0.5.

    Since obs are newest-first (i=0 is most recent), a positive return means
    prices[0] (current) > prices[90] (90 days ago). The z-score computes
    return = prices[i] / prices[i+90] - 1 for each window i. The most recent
    return (i=0) should be large and positive relative to all historical returns.
    """
    # Create obs: current price (i=0) is much higher than 90 days ago (i=90)
    # Use a price series with a big jump in recent 90 days vs flat historical
    obs = []
    for i in range(365):
        d = _TARGET_DATE - timedelta(days=i)
        if i < 90:
            # Recent 90 days: price is high (100k)
            price = 100_000.0
        else:
            # Prior period: price was much lower (40k)
            price = 40_000.0
        obs.append(CGObs(obs_date=d, price_usd=price, market_cap_usd=price*19e6, volume_usd=30e9, coin_id="bitcoin"))

    cg_data = {
        "btc": obs,
        "eth": _make_eth_obs(365),
        "global": CGGlobal(52.0, 2.5e12),
        "usdt": _make_stable_obs("tether"),
        "usdc": _make_stable_obs("usd-coin"),
    }
    yf_data = {"BTC-USD": _make_yf_obs("BTC-USD"), "QQQ": _make_yf_obs("QQQ"), "GLD": _make_yf_obs("GLD")}
    fred_data = {"DEXUSEU": _make_fred_obs()}

    snap = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    assert snap.p_btc_momentum_positive > 0.5, \
        f"Expected P > 0.5 for positive BTC trend, got {snap.p_btc_momentum_positive:.3f}"


# ---------------------------------------------------------------------------
# TEST-CR-07 — BTC negative return → P(BTCMomentumPositive) < 0.5
# ---------------------------------------------------------------------------

def test_btc_negative_return_drives_momentum_low():
    """BTC price lower now than 90 days ago → negative momentum."""
    obs = []
    for i in range(365):
        d = _TARGET_DATE - timedelta(days=i)
        # Price was HIGHER in the past: current (i=0) is lowest
        price = 30_000.0 * (1.0 + 0.8 * i / 365)  # increasing as we go back in time
        obs.append(CGObs(obs_date=d, price_usd=price, market_cap_usd=price*19e6, volume_usd=30e9, coin_id="bitcoin"))

    cg_data = {
        "btc": obs,
        "eth": _make_eth_obs(365),
        "global": CGGlobal(52.0, 2.5e12),
        "usdt": _make_stable_obs("tether"),
        "usdc": _make_stable_obs("usd-coin"),
    }
    yf_data = {"BTC-USD": _make_yf_obs("BTC-USD"), "QQQ": _make_yf_obs("QQQ"), "GLD": _make_yf_obs("GLD")}
    fred_data = {"DEXUSEU": _make_fred_obs()}

    snap = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    assert snap.p_btc_momentum_positive < 0.5, \
        f"Expected P < 0.5 for negative BTC trend, got {snap.p_btc_momentum_positive:.3f}"


# ---------------------------------------------------------------------------
# TEST-CR-08 — Low BTC dominance (40%) → P(AltcoinSeasonActive) > 0.5
# ---------------------------------------------------------------------------

def test_low_btc_dominance_signals_altcoin_season():
    """BTC dominance at 40% (well below 52% mean) → P(AltcoinSeasonActive) > 0.5."""
    cg_data, yf_data, fred_data = _make_full_data(btc_dominance=40.0)
    snap = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    assert snap.p_altcoin_season_active > 0.5, \
        f"Expected P > 0.5 for low dominance (40%), got {snap.p_altcoin_season_active:.3f}"


# ---------------------------------------------------------------------------
# TEST-CR-09 — High BTC dominance (65%) → P(AltcoinSeasonActive) < 0.5
# ---------------------------------------------------------------------------

def test_high_btc_dominance_suppresses_altcoin_season():
    """BTC dominance at 65% (well above 52% mean) → P(AltcoinSeasonActive) < 0.5."""
    cg_data, yf_data, fred_data = _make_full_data(btc_dominance=65.0)
    snap = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    assert snap.p_altcoin_season_active < 0.5, \
        f"Expected P < 0.5 for high dominance (65%), got {snap.p_altcoin_season_active:.3f}"


# ---------------------------------------------------------------------------
# TEST-CR-10 — build_evidence_record maps all 8 UUIDs
# ---------------------------------------------------------------------------

def test_build_evidence_record_maps_all_uuids():
    variables = get_variables()
    expected_ids = {v.variable_id for v in variables.values()}
    cg_data, yf_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    record = CryptoRegimePipeline.build_evidence_record(snapshot)
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert len(record.observed_assignments) == 8
    assert assignment_ids == expected_ids


# ---------------------------------------------------------------------------
# TEST-CR-11 — build_evidence_record produces SOFT_OBSERVED
# ---------------------------------------------------------------------------

def test_build_evidence_record_all_soft_observed():
    cg_data, yf_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    record = CryptoRegimePipeline.build_evidence_record(snapshot)
    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED
        assert a.probabilities is not None
        assert set(a.probabilities.keys()) == {True, False}
        p_true = a.probabilities[True]
        assert 0.01 <= p_true <= 0.99
        assert abs(a.probabilities[True] + a.probabilities[False] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# TEST-CR-12 — Domain module_id matches candidates
# ---------------------------------------------------------------------------

def test_domain_module_id_matches_candidates():
    domain = CryptoRegimeV1()
    module_id = domain.module_id()
    for cand in domain.initial_candidates():
        assert cand.domain_module_id == module_id


# ---------------------------------------------------------------------------
# TEST-CR-13 — Existence thresholds valid
# ---------------------------------------------------------------------------

def test_existence_thresholds_are_valid():
    domain = CryptoRegimeV1()
    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < 1.0
    assert 0.0 < t.accept_above < 1.0
    assert t.prune_below < t.explore_band[0]
    assert t.explore_band[0] < t.explore_band[1]
    assert t.explore_band[1] < t.accept_above


# ---------------------------------------------------------------------------
# TEST-CR-14 — Domain registers in engine, evidence ingested
# ---------------------------------------------------------------------------

def test_domain_registers_in_engine():
    engine = ProbabilisticOntologyEngine(db_path=":memory:", random_seed=42)
    domain = CryptoRegimeV1()
    engine.register_domain(domain)
    engine.activate_domain(domain.module_id())
    pop = engine.get_population(domain.module_id())
    assert pop is not None
    assert len(pop.active_candidates()) == 5

    cg_data, yf_data, fred_data = _make_full_data()
    snapshot = compute_snapshot(cg_data, yf_data, fred_data, _TARGET_DATE)
    record = CryptoRegimePipeline.build_evidence_record(snapshot)
    engine.ingest(record)
    assert engine.evidence_store.count(domain.module_id()) == 1


# ---------------------------------------------------------------------------
# TEST-CR-15 — Candidates have distinct edge structures
# ---------------------------------------------------------------------------

def test_candidates_have_distinct_edge_structures():
    domain = CryptoRegimeV1()
    candidates = domain.initial_candidates()
    signatures = [c.edge_structure_signature() for c in candidates]
    assert len(set(signatures)) == len(signatures), \
        "Some candidates share the same edge structure"


# ---------------------------------------------------------------------------
# TEST-CR-16 — CoinGeckoClient parses mocked market chart response
# ---------------------------------------------------------------------------

def test_coingecko_client_parses_market_chart():
    """CoinGeckoClient correctly parses the market chart JSON structure."""
    # Build mock response: timestamps in milliseconds
    base_ms = int(datetime(2024, 5, 3, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    mock_body = {
        "prices": [
            [base_ms, 60000.0],
            [base_ms - 86400000, 59000.0],
        ],
        "market_caps": [
            [base_ms, 1.14e12],
            [base_ms - 86400000, 1.12e12],
        ],
        "total_volumes": [
            [base_ms, 30e9],
            [base_ms - 86400000, 28e9],
        ],
    }

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=mock_body)

    http_mock = AsyncMock()
    http_mock.get = AsyncMock(return_value=resp)

    client = CoinGeckoClient(client=http_mock)
    result = asyncio.run(client.fetch_coin_chart("bitcoin", days=365))

    assert len(result) == 2
    assert result[0].price_usd == 60000.0
    assert result[0].coin_id == "bitcoin"
    assert result[0].obs_date == date(2024, 5, 3)
    assert result[0].volume_usd == 30e9


# ---------------------------------------------------------------------------
# TEST-CR-17 — Full pipeline fetch_evidence with all mocked clients
# ---------------------------------------------------------------------------

def test_fetch_evidence_full_pipeline_mocked():
    variables = get_variables()
    cg_data, yf_data, fred_data = _make_full_data()

    mock_cg = AsyncMock(spec=CoinGeckoClient)
    mock_cg.fetch_all = AsyncMock(return_value=cg_data)

    mock_yf = AsyncMock(spec=CryptoYFinanceClient)
    mock_yf.fetch_all = AsyncMock(return_value=yf_data)

    mock_fred = AsyncMock(spec=FREDClient)
    mock_fred.fetch_all_series = AsyncMock(return_value=fred_data)

    pipeline = CryptoRegimePipeline(mock_cg, mock_yf, mock_fred)
    record = asyncio.run(pipeline.fetch_evidence(_TARGET_DATE))

    assert len(record.observed_assignments) == 8
    assignment_ids = {a.variable_id for a in record.observed_assignments}
    assert assignment_ids == {v.variable_id for v in variables.values()}
    assert "CoinGecko" in record.source_ref
    assert "yfinance" in record.source_ref
    assert "FRED" in record.source_ref

    for a in record.observed_assignments:
        assert a.missingness == MissingnessType.SOFT_OBSERVED

    mock_cg.fetch_all.assert_called_once_with(end_date=_TARGET_DATE)
    mock_yf.fetch_all.assert_called_once_with(end_date=_TARGET_DATE)
    mock_fred.fetch_all_series.assert_called_once_with(end_date=_TARGET_DATE)
