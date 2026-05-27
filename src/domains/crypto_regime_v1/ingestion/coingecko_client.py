"""
CoinGeckoClient — crypto-regime-v1 CoinGecko data fetcher.

Endpoints used
--------------
/coins/bitcoin/market_chart     BTC prices, market caps, volumes
/coins/ethereum/market_chart    ETH prices
/global                         BTC dominance percentage
/coins/tether/market_chart      USDT market caps
/coins/usd-coin/market_chart    USDC market caps

No API key required (free tier, rate-limited).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"


@dataclass(frozen=True)
class CGObs:
    """A single daily observation from CoinGecko market chart."""
    obs_date: date
    price_usd: float
    market_cap_usd: float
    volume_usd: float
    coin_id: str


@dataclass(frozen=True)
class CGGlobal:
    """CoinGecko global market data."""
    btc_dominance_pct: float
    total_market_cap_usd: float


class CoinGeckoClient:
    """
    Asynchronous CoinGecko client for crypto-regime-v1.

    Parameters
    ----------
    client : httpx.AsyncClient, optional
        Injected HTTP client for testing.
    timeout : float
        Request timeout in seconds.
    """

    BASE_URL = _BASE_URL

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ) -> None:
        self._injected = client is not None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
        )

    async def aclose(self) -> None:
        if not self._injected:
            await self._client.aclose()

    async def __aenter__(self) -> "CoinGeckoClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def fetch_coin_chart(
        self,
        coin_id: str,
        days: int = 365,
    ) -> list[CGObs]:
        """Fetch market chart data for a coin. Returns observations newest-first."""
        url = f"{self.BASE_URL}/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": str(days)}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("CoinGecko fetch_coin_chart(%s) failed: %s", coin_id, exc)
            return []

        prices = body.get("prices", [])
        market_caps = body.get("market_caps", [])
        volumes = body.get("total_volumes", [])

        # Build lookup by date
        mcap_by_date: dict[date, float] = {}
        for ms, val in market_caps:
            try:
                d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
                mcap_by_date[d] = float(val)
            except Exception:
                continue

        vol_by_date: dict[date, float] = {}
        for ms, val in volumes:
            try:
                d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
                vol_by_date[d] = float(val)
            except Exception:
                continue

        result: list[CGObs] = []
        for ms, price in prices:
            try:
                obs_date = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
                result.append(CGObs(
                    obs_date=obs_date,
                    price_usd=float(price),
                    market_cap_usd=mcap_by_date.get(obs_date, 0.0),
                    volume_usd=vol_by_date.get(obs_date, 0.0),
                    coin_id=coin_id,
                ))
            except Exception:
                continue

        result.sort(key=lambda o: o.obs_date, reverse=True)
        logger.debug("CoinGecko %s: %d obs", coin_id, len(result))
        return result

    async def fetch_global(self) -> Optional[CGGlobal]:
        """Fetch global market data (BTC dominance, total market cap)."""
        url = f"{self.BASE_URL}/global"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("CoinGecko fetch_global failed: %s", exc)
            return None

        data = body.get("data", {})
        try:
            btc_dom = float(data.get("bitcoin_dominance_percentage", 50.0))
            total_mcap = float(data.get("total_market_cap", {}).get("usd", 0.0))
            return CGGlobal(btc_dominance_pct=btc_dom, total_market_cap_usd=total_mcap)
        except Exception as exc:
            logger.warning("CoinGecko global parse error: %s", exc)
            return None

    async def fetch_stablecoin_market_caps(
        self,
        days: int = 90,
    ) -> tuple[list[CGObs], list[CGObs]]:
        """Fetch market cap data for USDT and USDC. Returns (usdt_obs, usdc_obs)."""
        usdt_task = asyncio.create_task(self.fetch_coin_chart("tether", days=days))
        usdc_task = asyncio.create_task(self.fetch_coin_chart("usd-coin", days=days))
        usdt, usdc = await asyncio.gather(usdt_task, usdc_task)
        return usdt, usdc

    async def fetch_all(
        self,
        end_date: Optional[date] = None,
    ) -> dict:
        """
        Fetch all required CoinGecko data concurrently.

        Returns dict with keys:
            "btc": list[CGObs]
            "eth": list[CGObs]
            "global": CGGlobal | None
            "usdt": list[CGObs]
            "usdc": list[CGObs]
        """
        btc_task = asyncio.create_task(self.fetch_coin_chart("bitcoin", days=365))
        eth_task = asyncio.create_task(self.fetch_coin_chart("ethereum", days=365))
        global_task = asyncio.create_task(self.fetch_global())
        usdt_task = asyncio.create_task(self.fetch_coin_chart("tether", days=90))
        usdc_task = asyncio.create_task(self.fetch_coin_chart("usd-coin", days=90))

        btc, eth, global_data, usdt, usdc = await asyncio.gather(
            btc_task, eth_task, global_task, usdt_task, usdc_task
        )

        # Filter to end_date if provided
        if end_date is not None:
            btc = [o for o in btc if o.obs_date <= end_date]
            eth = [o for o in eth if o.obs_date <= end_date]
            usdt = [o for o in usdt if o.obs_date <= end_date]
            usdc = [o for o in usdc if o.obs_date <= end_date]

        return {
            "btc": btc,
            "eth": eth,
            "global": global_data,
            "usdt": usdt,
            "usdc": usdc,
        }
