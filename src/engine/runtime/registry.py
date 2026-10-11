"""
The domains this service runs — the one place they are listed.

Adding a domain: give its package a DomainModule and a ``source.open_source``,
then add one DomainRegistration here. Nothing else names domains.
"""
from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ...domains.ai_regime_v1 import source as ai_source
from ...domains.ai_regime_v1.domain import AIRegimeV1
from ...domains.credit_cycle_v1 import source as cc_source
from ...domains.credit_cycle_v1.domain import CreditCycleV1
from ...domains.crypto_regime_v1 import source as cr_source
from ...domains.crypto_regime_v1.domain import CryptoRegimeV1
from ...domains.energy_regime_v1 import source as er_source
from ...domains.energy_regime_v1.domain import EnergyRegimeV1
from ...domains.geopolitics_v1 import source as gp_source
from ...domains.geopolitics_v1.domain import GeopoliticsV1
from ...domains.labor_market_v1 import source as lm_source
from ...domains.labor_market_v1.domain import LaborMarketV1
from ...domains.macro_regime_v1 import source as mr_source
from ...domains.macro_regime_v1.domain import MacroRegimeV1
from ...domains.natural_gas_v1 import source as ng_source
from ...domains.natural_gas_v1.domain import NaturalGasV1
from ...domains.sf_urban_v1 import source as sf_source
from ...domains.sf_urban_v1.domain import SFUrbanV1
from ...domains.sovereign_debt_v1 import source as sd_source
from ...domains.sovereign_debt_v1.domain import SovereignDebtV1
from . import art
from .scheduler import DailySchedule, Schedule, WeeklySchedule

OpenSource = Callable[[Mapping[str, str]], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True)
class DomainRegistration:
    key: str                       # short name used by the API (?domain=mr)
    module_id: str
    display_name: str
    db_filename: str               # under POE_DATA_DIR; keep: existing volumes use these names
    build_domain: Callable[[], Any]
    open_source: OpenSource
    required_env: tuple[str, ...] = ()
    # Env var prefix for <PREFIX>_RUN_HOUR_UTC / <PREFIX>_BACKFILL_WEEKS (existing names).
    env_prefix: str = ""
    default_run_hour_utc: int = 9
    schedule: Schedule = WeeklySchedule()
    scheduled: bool = True
    # Skip a fetched weekly state identical to the latest stored one.
    skip_unchanged_state: bool = False

    @property
    def scheduler_task_name(self) -> str:
        return f"{self.module_id.removesuffix('-v1')}-evidence-scheduler"


_FRED = ("FRED_API_KEY",)

REGISTRY: tuple[DomainRegistration, ...] = (
    DomainRegistration("ng", "natural-gas-v1", "Natural Gas", "natural_gas.db", NaturalGasV1,
                       ng_source.open_source, ("EIA_API_KEY",), "NATURAL_GAS", default_run_hour_utc=7,
                       schedule=DailySchedule()),
    DomainRegistration("mr", "macro-regime-v1", "Macro Regime", "macro_regime.db", MacroRegimeV1,
                       mr_source.open_source, _FRED, "MACRO_REGIME"),
    DomainRegistration("ai", "ai-regime-v1", "AI Regime", "ai_regime.db", AIRegimeV1,
                       ai_source.open_source, _FRED, "AI_REGIME"),
    DomainRegistration("sd", "sovereign-debt-v1", "Sovereign Debt", "sovereign_debt.db", SovereignDebtV1,
                       sd_source.open_source, _FRED, "SOVEREIGN_DEBT", skip_unchanged_state=True),
    DomainRegistration("cc", "credit-cycle-v1", "Credit Cycle", "credit_cycle.db", CreditCycleV1,
                       cc_source.open_source, _FRED, "CREDIT_CYCLE", skip_unchanged_state=True),
    DomainRegistration("er", "energy-regime-v1", "Energy Regime", "energy_regime.db", EnergyRegimeV1,
                       er_source.open_source, _FRED, "ENERGY_REGIME", skip_unchanged_state=True),
    DomainRegistration("lm", "labor-market-v1", "Labor Market", "labor_market.db", LaborMarketV1,
                       lm_source.open_source, _FRED, "LABOR_MARKET", skip_unchanged_state=True),
    DomainRegistration("cr", "crypto-regime-v1", "Crypto Regime", "crypto_regime.db", CryptoRegimeV1,
                       cr_source.open_source, _FRED, "CRYPTO_REGIME", skip_unchanged_state=True),
    DomainRegistration("gp", "geopolitics-v1", "Geopolitics", "geopolitics.db", GeopoliticsV1,
                       gp_source.open_source, _FRED, "GEOPOLITICS", skip_unchanged_state=True),
    DomainRegistration("sf", "sf-urban-v1", "SF Urban", "sf_urban.db", SFUrbanV1,
                       sf_source.open_source, _FRED, "SF_URBAN", skip_unchanged_state=True),
    DomainRegistration("art", "art_prestige_regime_v1", "Art Prestige Regime", "art_prestige_regime.db",
                       art.build_art_domain, art.open_source, scheduled=False),
)

BY_KEY: dict[str, DomainRegistration] = {r.key: r for r in REGISTRY}
