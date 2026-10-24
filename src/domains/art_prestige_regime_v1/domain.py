"""
art_prestige_regime_v1 — the art world's prestige regime.

Twenty-five BOOLEAN variables in three groups (institutional, market,
cultural). Moved here from the separate art-market-domain package; the
module id, variable names and ids are unchanged, so stored evidence and
the dashboard keep working.

Evidence comes from two places (see source.py and manual.py): monthly
series fetched automatically, and hand-supplied report labels. Variables
neither source measures in a period are MISSING.
"""
from __future__ import annotations

from ..sources.structure import boolean_variables, with_lags
from ...engine.model.domain import DEFAULT_THRESHOLDS
from ...engine.schemas import EdgeExistenceThresholdConfig, Variable

DOMAIN_MODULE_ID = "art_prestige_regime_v1"

VARIABLES: list[str] = [
    # Institutional
    "InstitutionalRiskAversion",
    "MuseumFigurativeAcceptance",
    "ConceptualDominance",
    "AIArtInstitutionalAcceptance",
    "CuratorialMaterialityShift",
    "CraftPrestigeRising",
    "PrestigeFragmentation",
    "RegionalSceneMomentum",
    "BlueChipInstitutionalCapture",
    "BiennialFatigue",
    "MuseumAcquisitionMomentum",
    # Market
    "BlueChipConcentration",
    "AuctionSpeculationElevated",
    "CollectorFlightToSafety",
    "FigurativeAuctionMomentum",
    "EmergingMarketLiquidity",
    "MarketPolarization",
    "MarketUncertainty",
    # Cultural
    "RitualAuraPremium",
    "EmbodimentDiscourseRising",
    "AntiDigitalSentiment",
    "AIImageSaturation",
    "AuthenticityPremium",
    "NeoAcademicResurgence",
    "AttentionFragmentation",
]

_VARIABLES = boolean_variables(DOMAIN_MODULE_ID, VARIABLES)


def get_variables() -> dict[str, Variable]:
    return _VARIABLES


class ArtPrestigeRegimeV1:
    """Domain module for the art world's prestige regime."""

    def module_id(self) -> str:
        return DOMAIN_MODULE_ID

    def variables(self) -> list[Variable]:
        return list(with_lags(DOMAIN_MODULE_ID, _VARIABLES).values())

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return DEFAULT_THRESHOLDS
