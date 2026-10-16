"""
art_prestige_regime_v1 — the art world's prestige regime.

Twenty-five BOOLEAN variables in three groups (institutional, market,
cultural) and five seed hypotheses about how they connect. Moved here from
the separate art-market-domain package; the module id, variable names and
ids, hypotheses and priors are unchanged, so stored evidence and the
dashboard keep working.

Evidence comes from two places (see source.py and manual.py): monthly
series fetched automatically, and hand-supplied report labels. Variables
neither source measures in a period are MISSING.

Seeds
-----
H1 CraftAuraBacklash: AIImageSaturation → RitualAuraPremium → CraftPrestigeRising
   → MuseumFigurativeAcceptance; CuratorialMaterialityShift → CraftPrestigeRising
H2 AINormalization: AIImageSaturation → AIArtInstitutionalAcceptance
   → {MuseumAcquisitionMomentum, ConceptualDominance}
H3 DefensiveBlueChipConsolidation: MarketUncertainty → CollectorFlightToSafety
   → BlueChipConcentration → InstitutionalRiskAversion;
   BlueChipInstitutionalCapture → MuseumAcquisitionMomentum
H4 PrestigeFragmentation: AttentionFragmentation → PrestigeFragmentation
   → {RegionalSceneMomentum, BlueChipConcentration}
H5 NeoAcademicResurgence: {RitualAuraPremium, AuthenticityPremium}
   → NeoAcademicResurgence → MuseumFigurativeAcceptance
"""
from __future__ import annotations

from uuid import uuid4

from ..sources.structure import boolean_variables, seed_edge
from ...engine.model.domain import DEFAULT_THRESHOLDS
from ...engine.schemas import EdgeExistenceThresholdConfig, OntologyCandidate, Variable

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


def _candidate(module_id: str, description: str, edges: list[tuple[str, str, float, str]]) -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=0,
        variables=list(_VARIABLES.values()),
        edges=[seed_edge(_VARIABLES, parent, child, prior, label) for parent, child, prior, label in edges],
        description=description,
    )


def make_craft_aura_backlash_candidate(module_id: str = DOMAIN_MODULE_ID) -> OntologyCandidate:
    """H1: AI image saturation creates a premium on aura and presence, which lifts craft into museums."""
    return _candidate(module_id, "H1: CraftAuraBacklash — AI saturation → aura premium → craft/figurative institutionalisation", [
        ("AIImageSaturation", "RitualAuraPremium", 0.65, "AI image saturation → aura/ritual premium"),
        ("RitualAuraPremium", "CraftPrestigeRising", 0.65, "ritual aura premium → craft prestige elevation"),
        ("CraftPrestigeRising", "MuseumFigurativeAcceptance", 0.60, "craft prestige → institutional figurative acceptance"),
        ("CuratorialMaterialityShift", "CraftPrestigeRising", 0.60, "curatorial materiality shift → craft rising"),
    ])


def make_ai_normalization_candidate(module_id: str = DOMAIN_MODULE_ID) -> OntologyCandidate:
    """H2: AI imagery is absorbed: institutions acquire AI work and conceptual frameworks gain."""
    return _candidate(module_id, "H2: AINormalization — AI saturation absorbed into institutional legitimacy", [
        ("AIImageSaturation", "AIArtInstitutionalAcceptance", 0.60, "AI image presence → institutional normalisation"),
        ("AIArtInstitutionalAcceptance", "MuseumAcquisitionMomentum", 0.65, "AI institutional acceptance → museum acquisitions"),
        ("AIArtInstitutionalAcceptance", "ConceptualDominance", 0.60, "AI acceptance → conceptual framework dominance"),
    ])


def make_defensive_blue_chip_candidate(module_id: str = DOMAIN_MODULE_ID) -> OntologyCandidate:
    """H3: market uncertainty drives capital into blue-chip names; museums follow and take fewer risks."""
    return _candidate(module_id, "H3: DefensiveBlueChipConsolidation — market uncertainty → blue-chip flight → institutional conservatism", [
        ("MarketUncertainty", "CollectorFlightToSafety", 0.70, "market uncertainty → flight to established names"),
        ("CollectorFlightToSafety", "BlueChipConcentration", 0.70, "safety seeking → blue-chip market concentration"),
        ("BlueChipConcentration", "InstitutionalRiskAversion", 0.65, "market concentration → institutional risk aversion"),
        ("BlueChipInstitutionalCapture", "MuseumAcquisitionMomentum", 0.60, "blue-chip institutional capture → acquisition momentum"),
    ])


def make_prestige_fragmentation_candidate(module_id: str = DOMAIN_MODULE_ID) -> OntologyCandidate:
    """H4: dispersed attention fractures the prestige hierarchy; regional scenes gain."""
    return _candidate(module_id, "H4: PrestigeFragmentation — attention dispersal fractures hierarchy → regional momentum", [
        ("AttentionFragmentation", "PrestigeFragmentation", 0.65, "attention dispersal → prestige hierarchy fragmentation"),
        ("PrestigeFragmentation", "RegionalSceneMomentum", 0.60, "prestige fragmentation → regional scenes gain visibility"),
        ("PrestigeFragmentation", "BlueChipConcentration", 0.55, "fragmentation → suppressed blue-chip consensus"),
    ])


def make_neo_academic_resurgence_candidate(module_id: str = DOMAIN_MODULE_ID) -> OntologyCandidate:
    """H5: embodiment, authenticity and aura discourse drive a figurative, neo-academic revival."""
    return _candidate(module_id, "H5: NeoAcademicResurgence — aura + authenticity premium → neo-academic figurative revival", [
        ("RitualAuraPremium", "NeoAcademicResurgence", 0.65, "ritual aura premium → neo-academic interest"),
        ("AuthenticityPremium", "NeoAcademicResurgence", 0.65, "authenticity premium → neo-academic validation"),
        ("NeoAcademicResurgence", "MuseumFigurativeAcceptance", 0.65, "neo-academic resurgence → museum figurative programming"),
    ])


class ArtPrestigeRegimeV1:
    """Domain module for the art world's prestige regime."""

    def module_id(self) -> str:
        return DOMAIN_MODULE_ID

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_craft_aura_backlash_candidate(),
            make_ai_normalization_candidate(),
            make_defensive_blue_chip_candidate(),
            make_prestige_fragmentation_candidate(),
            make_neo_academic_resurgence_candidate(),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return DEFAULT_THRESHOLDS
