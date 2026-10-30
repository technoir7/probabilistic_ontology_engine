"""What the API serves for success (REFACTOR_SPEC D31) and what its reports
are written from, apart from dto.py, which had outgrown its budget."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .dto import NarrativeCaseForecastOut


# ── Success (D31) ─────────────────────────────────────────────────────────────

class SuccessKindOut(BaseModel):
    key: str
    title: str
    outcome: str
    leader: list[str]                 # empty: own past alone
    leader_since: Optional[int]
    gain: float                       # nats over own past, all scored years
    mechanisms: list[tuple[str, float]]
    effects: dict[str, float]         # "feature=level" -> push on the log-odds of any outcome
    dealt: dict[str, list[float]]     # engine gain with that feature dealt at random
    placebo: float                    # engine gain with features from the year after
    placebo_fair: bool                # False: the year-after features count part of the outcome itself
    most_raised: list[tuple[str, float, float]]   # artist, chance from own past, with the leader
    years: list[tuple[int, float]]


class RewardedOut(BaseModel):
    kind: str
    name: str
    approvals: int
    disapprovals: int
    approved: list[str]
    disapproved: list[str]


class ThemeTestOut(BaseModel):
    """A theme's track record tested on top of one kind's leader (ART-PLAN §14)."""
    leader: list[str]
    leader_since: Optional[int]
    gain: float
    gain_without: float               # the kind's own leader, without the records
    effects: dict[str, float]         # "feature=level" -> push
    dealt: dict[str, list[float]]     # gain with each record feature dealt at random
    placebo: float
    year: int
    best: list[tuple[str, float]]     # named theme, record
    worst: list[tuple[str, float]]


class SuccessSnapshotOut(BaseModel):
    year: int
    forecast_for: int
    kinds: dict[str, SuccessKindOut]
    rewarded: list[RewardedOut]
    themes: dict[str, ThemeTestOut]   # kind -> its theme test


class SuccessOut(BaseModel):
    domain: str
    success: Optional[SuccessSnapshotOut]   # None: the domain has none


class NarrativeSuccessMechanismOut(BaseModel):
    mechanisms: str                   # in words
    gain_nats: float


class NarrativeSuccessEffectOut(BaseModel):
    feature: str                      # in words, with its level ("one" or "several")
    push: float                       # change in the log-odds of any success next year: + helps, - hurts
    times_the_odds_of_an_artist_with_the_same_past_and_none: float   # exp(push), so the report does no arithmetic


class NarrativeSuccessAddsOut(BaseModel):
    feature: str                      # in words
    nats: float                       # gain lost when this feature alone is dealt at random, mean of the deals


class NarrativeOtherKindOut(BaseModel):
    leading_features: list[str]       # in words; empty: own past alone
    gain_nats_over_own_past: float
    helps: list[str]                  # leading features whose pushes are above 0
    hurts: list[str]


class NarrativeLifeClaimOut(BaseModel):
    """A claim read as about an artist's life, numbered for the imagined artist's life to cite (ART-PLAN 15.1)."""
    n: int
    who: str
    when: str
    claim: str


class NarrativeImageSubjectOut(BaseModel):
    """What the report's image prompt shows, chosen by rule (narrative._image_subject)."""
    theme: str
    theme_is_on_this_years_lists: list[str]
    distinctive_words: list[str]
    what_critics_said: list[str]
    medium: str
    medium_from_the_leading_features: bool   # False: this year's most approved medium, not a tested feature
    reasons: list[str]                       # the rule's reasons, in words; the report prints them before the prompt
    describes_instead: bool                  # True: nothing predicts this kind, so it shows those who have it now
    wall_text_voice: str                     # who speaks in the wall text, fixed by kind (ART-PLAN §12.11)
    life_claims: list[NarrativeLifeClaimOut]  # the only claims the imagined artist's life may draw on; empty: none


class NarrativeThemeKindOut(BaseModel):
    """One kind of success's theme test, for the themes report."""
    kind: str
    title: str
    verdicts: list[str]               # fixed by rule (success_narrative._theme_verdicts)
    leader: str
    leader_effects: list[NarrativeSuccessEffectOut]
    best_records_this_year: list[str]
    worst_records_this_year: list[str]


class NarrativeThemesOut(BaseModel):
    """Which themes help (ART-PLAN §14), for its own written report."""
    domain: str
    how_records_are_made: str
    kinds: list[NarrativeThemeKindOut]
    note: str


class NarrativeSuccessOut(BaseModel):
    """One kind of success, for its own written report (D31)."""
    domain: str
    kind: str
    title: str
    success_means: str
    forecast_for: int
    leader: str
    leader_since: Optional[int]
    gain_nats_over_own_past: float
    scored_years: int
    verdicts: list[str]               # fixed by rule (success_narrative._verdicts); the report states them as they are
    best_rival_sets: list[NarrativeSuccessMechanismOut]
    leader_effects: list[NarrativeSuccessEffectOut]
    each_leading_feature_adds: list[NarrativeSuccessAddsOut]
    control_placebo_features_from_the_year_after_gain_nats: float
    control_placebo_is_a_fair_test: bool   # False: next year's features count part of next year's success
    artists_the_leader_favours: list[NarrativeCaseForecastOut]
    other_kinds: dict[str, NarrativeOtherKindOut]   # by title
    critics_rewarded_this_year: list[RewardedOut]
    image_subject: Optional[NarrativeImageSubjectOut]   # None: too small to claim, so nothing to illustrate
    note: str
