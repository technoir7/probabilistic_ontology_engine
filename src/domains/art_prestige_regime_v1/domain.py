"""
art_prestige_regime_v1 — what confers prestige in art, and how that changes.

Bourdieu: prestige is consecration, and three bodies consecrate. Each is
observed, and nothing more is assumed (docs/art-evidence-plan.md):
- the press: how much of a paper's art coverage carries a topic tag, per
  month. Two papers, London's and New York's, kept apart; the topics are the
  editors' most-used tags, chosen by a rule (plan §5).
- institutions: distinct artists two museums acquired, yearly.
- the market: four Art Basel & UBS report figures, yearly.

Every variable is graded: low, mid or high for its own series (D25). The
module id is unchanged so the dashboard's routes keep working; the old
twenty-five hand-named variables are gone (plan §9).
"""
from __future__ import annotations

from ..sources.grades import graded_variables
from ..sources.structure import with_lags
from ...engine.model.domain import DEFAULT_THRESHOLDS
from ...engine.schemas import EdgeExistenceThresholdConfig, Variable

DOMAIN_MODULE_ID = "art_prestige_regime_v1"

# Signal → (paper, the paper's own tag). Ranked by art articles carrying them.
TALK: dict[str, tuple[str, str]] = {
    "GuardianPhotographyTalk": ("guardian", "artanddesign/photography"),
    "GuardianExhibitionTalk": ("guardian", "artanddesign/exhibition"),
    "GuardianPaintingTalk": ("guardian", "artanddesign/painting"),
    "GuardianArchitectureTalk": ("guardian", "artanddesign/architecture"),
    "NYTMuseumsTalk": ("nyt", "museums"),
    "NYTPhotographyTalk": ("nyt", "photography"),
    "NYTSculptureTalk": ("nyt", "sculpture"),
    "NYTAuctionsTalk": ("nyt", "auctions"),
}
FIGURES = ["ArtSalesGrowth", "DealerShare", "OnlineShare", "HighEndShare"]
MUSEUMS = ["MuseumAcquisitionMomentum"]

VARIABLES: list[str] = [*TALK, *FIGURES, *MUSEUMS]

_VARIABLES = graded_variables(DOMAIN_MODULE_ID, VARIABLES)


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
