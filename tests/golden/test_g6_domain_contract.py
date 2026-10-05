"""
G6 — domain contract golden (REFACTOR_SPEC §7 Phase 0.3).

One parametrized check of what the engine requires from every domain module,
plus a snapshot of each domain's definition (variables, seed candidates,
priors, thresholds), so Phase 4 can replace the copied domain.py boilerplate
with shared constructors and prove nothing moved.

Pipeline math (raw observations → evidence) is pinned per domain at the HTTP
layer in the Phase 4 PR that converts that domain.
"""
from __future__ import annotations

import pytest

from art_prestige_regime_v1 import ArtPrestigeRegimeV1
from src.domains.ai_regime_v1.domain import AIRegimeV1
from src.domains.credit_cycle_v1.domain import CreditCycleV1
from src.domains.crypto_regime_v1.domain import CryptoRegimeV1
from src.domains.energy_regime_v1.domain import EnergyRegimeV1
from src.domains.geopolitics_v1.domain import GeopoliticsV1
from src.domains.labor_market_v1.domain import LaborMarketV1
from src.domains.macro_regime_v1.domain import MacroRegimeV1
from src.domains.natural_gas_v1.domain import NaturalGasV1
from src.domains.sf_urban_v1.domain import SFUrbanV1
from src.domains.sovereign_debt_v1.domain import SovereignDebtV1
from src.domains.test_domain_v1.domain import TestDomainV1
from src.engine.api import app as api_app
from src.engine.schemas import DomainType
from src.engine.variable_identity import stable_variable_id

from .probe import signature
from .snapshot import assert_matches_snapshot

DOMAINS = [
    AIRegimeV1, ArtPrestigeRegimeV1, CreditCycleV1, CryptoRegimeV1, EnergyRegimeV1,
    GeopoliticsV1, LaborMarketV1, MacroRegimeV1, NaturalGasV1, SFUrbanV1,
    SovereignDebtV1, TestDomainV1,
]


def test_every_served_domain_is_covered():
    served = {module_id for module_id, _ in api_app._DOMAIN_MAP.values()}
    covered = {cls().module_id() for cls in DOMAINS} - {"test-domain-v1"}
    assert served == covered, "a domain was added or removed; update DOMAINS above"


@pytest.mark.parametrize("cls", DOMAINS, ids=lambda c: c.__name__)
def test_domain_satisfies_engine_contract(cls):
    domain = cls()
    module_id = domain.module_id()
    seeds = domain.initial_candidates()
    assert seeds, "a domain needs at least one seed candidate"

    names = [v.name for v in seeds[0].variables]
    for cand in seeds:
        assert cand.domain_module_id == module_id
        assert [v.name for v in cand.variables] == names, "seeds must share one variable set"
        assert cand.is_dag()
        for v in cand.variables:
            assert v.variable_id == stable_variable_id(module_id, v.name)
            if v.domain_type == DomainType.BOOLEAN:
                assert v.support == [True, False]
    signatures = [frozenset(signature(c)) for c in seeds]
    assert len(set(signatures)) == len(signatures), "seed candidates must differ in structure"

    t = domain.existence_thresholds()
    assert 0.0 < t.prune_below < t.explore_band[0] < t.explore_band[1] < t.accept_above < 1.0


def _definition(domain) -> dict:
    t = domain.existence_thresholds()
    return {
        "module_id": domain.module_id(),
        "thresholds": {
            "prune_below": t.prune_below,
            "accept_above": t.accept_above,
            "explore_band": list(t.explore_band),
        },
        "variables": [
            [v.name, v.domain_type.value, v.support, v.time_indexed, v.hidden]
            for v in domain.initial_candidates()[0].variables
        ],
        "seed_candidates": [
            {
                "description": c.description,
                "edges": [
                    [
                        f"{c.get_variable_by_id(e.parent_variable_id).name}->"
                        f"{c.get_variable_by_id(e.child_variable_id).name}",
                        e.existence_prior, e.existence_probability, e.explore_weight,
                        e.dependency_kind.value, e.learnable, e.enabled, e.explanatory_label,
                    ]
                    for e in c.edges
                ],
            }
            for c in domain.initial_candidates()
        ],
    }


def test_domain_definitions_match_golden():
    assert_matches_snapshot(
        "g6_domain_definitions",
        {cls.__name__: _definition(cls()) for cls in DOMAINS},
    )
