"""
G9 — yfinance client behaviour per domain (REFACTOR_SPEC 4.4).

Feeds each of the three yfinance clients the same synthetic download in the
column layouts yfinance has used (Price/Ticker MultiIndex, Ticker/Price, flat)
plus failure cases, and pins what they return and request, so merging them
into domains/sources/yfinance.py is checked against the copies.
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import date

import numpy as np
import pandas as pd
import pytest

from .snapshot import assert_matches_snapshot

CLIENTS = {
    "ai_regime_v1": ("AIYFinanceClient", "AI_TICKERS"),
    "crypto_regime_v1": ("CryptoYFinanceClient", "CRYPTO_YF_TICKERS"),
    "energy_regime_v1": ("EnergyYFinanceClient", "ENERGY_TICKERS"),
}
END = date(2026, 3, 6)


def _frame(tickers: list[str], layout: str) -> pd.DataFrame:
    idx = pd.date_range("2023-09-01", "2026-03-10", freq="7D")
    data = {}
    for i, t in enumerate(tickers):
        values = 100 + 10 * np.sin(np.arange(len(idx)) / (5 + i)) + i
        values[3] = np.nan          # a missing close
        values[5] = -1.0            # a non-positive close
        data[t] = values
    if layout == "flat":
        return pd.DataFrame({"Close": data[tickers[0]], "Open": data[tickers[0]]}, index=idx)
    cols = []
    arrays = []
    for t in tickers:
        for field in ("Close", "Open"):
            cols.append((field, t) if layout == "price_ticker" else (t, field))
            arrays.append(data[t])
    names = ["Price", "Ticker"] if layout == "price_ticker" else ["Ticker", "Price"]
    return pd.DataFrame(np.column_stack(arrays), index=idx, columns=pd.MultiIndex.from_tuples(cols, names=names))


def _run(domain: str) -> dict:
    module = importlib.import_module(f"src.domains.{domain}.ingestion.yfinance_client")
    cls_name, tickers_name = CLIENTS[domain]
    cls, tickers = getattr(module, cls_name), getattr(module, tickers_name)
    calls: list[dict] = []
    out: dict = {"tickers": list(tickers)}

    for layout in ("price_ticker", "ticker_price", "flat"):
        def download(**kwargs):
            calls.append({k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in kwargs.items()})
            return _frame(list(tickers), layout)

        result = asyncio.run(cls(download_fn=download).fetch_all(end_date=END))
        out[layout] = {
            t: [len(obs), obs[0].obs_date.isoformat() if obs else None, obs[-1].obs_date.isoformat() if obs else None,
                round(obs[0].close_price, 9) if obs else None]
            for t, obs in result.items()
        }

    def boom(**_kwargs):
        raise RuntimeError("yahoo down")

    out["download_raises"] = {t: len(v) for t, v in asyncio.run(cls(download_fn=boom).fetch_all(end_date=END)).items()}
    out["download_empty"] = {
        t: len(v) for t, v in asyncio.run(cls(download_fn=lambda **_: pd.DataFrame()).fetch_all(end_date=END)).items()
    }
    out["download_call"] = calls[0]
    return out


@pytest.mark.parametrize("domain", sorted(CLIENTS))
def test_g9_yfinance_client_matches_golden(domain):
    assert_matches_snapshot(f"g9_yfinance_{domain}", _run(domain))
