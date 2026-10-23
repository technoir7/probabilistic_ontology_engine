"""
Crisis-sensitive doubt (REFACTOR_SPEC D17).

A believer should hold on to what it has learned in ordinary times and doubt
it when the world surprises it far more than usual. Surprise is the leading
candidate's negative log-likelihood per record of a batch, scored before
learning it. Its usual level and spread are tracked over the same half-life
as candidate scores; a batch more than CRISIS_Z standard deviations above
the usual, once MIN_RECORDS have been seen, is a crisis, and every
candidate's counts and score window then count for DISCOUNT of what they did
before it learns that batch. The thresholds are conventional, chosen before
any replay: two standard deviations, a year of weekly evidence, a half.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .scoring import SCORE_HALF_LIFE_RECORDS

CRISIS_Z = 2.0
MIN_RECORDS = 52
DISCOUNT = 0.5


@dataclass
class Surprise:
    mean: float = 0.0
    var: float = 0.0
    weight: float = 0.0   # discounted record count behind mean and var
    seen: int = 0         # records ever observed
    events: int = 0       # crises so far

    def observe(self, per_record: float, n_records: int) -> bool:
        """Is this batch a crisis? Judged against what came before it, then
        folded into the usual level."""
        crisis = (
            self.seen >= MIN_RECORDS
            and self.var > 0
            and per_record > self.mean + CRISIS_Z * math.sqrt(self.var)
        )
        decay = 0.5 ** (n_records / SCORE_HALF_LIFE_RECORDS)
        w_old, w_new = self.weight * decay, float(n_records)
        total = w_old + w_new
        mean = (self.mean * w_old + per_record * w_new) / total
        self.var = (w_old * (self.var + (self.mean - mean) ** 2) + w_new * (per_record - mean) ** 2) / total
        self.mean, self.weight = mean, total
        self.seen += n_records
        self.events += crisis
        return crisis

    def state(self) -> dict:
        return asdict(self)

    @classmethod
    def from_state(cls, state: dict | None) -> "Surprise":
        return cls(**state) if state else cls()
