"""
Calibration and humility (SPEC §13.1, REFACTOR_SPEC D18).

Calibration: of the times the engine said a variable was true with
probability about p (given the week's other signals, before learning it),
how often was it true? Reported as the Brier score and the expected
calibration error over ten equal bins. The outcome may itself be a
probability: soft evidence says how likely a signal was, not whether it was,
and a belief learned from it is judged fairly only against it. Humility: the probability the whole
population, each structure weighted by its posterior weight, gave a batch,
against the leader's alone.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Sequence

BINS = 10


def mixture_log_likelihood(log_likelihoods: Sequence[float], weights: Sequence[float]) -> float:
    """log Σ w·exp(ll), computed stably; weights need not sum to one."""
    terms = [ll + math.log(w) for ll, w in zip(log_likelihoods, weights) if w > 0]
    top = max(terms)
    return top + math.log(sum(math.exp(t - top) for t in terms)) - math.log(sum(w for w in weights if w > 0))


@dataclass
class Calibration:
    n: list[int] = field(default_factory=lambda: [0] * BINS)
    said: list[float] = field(default_factory=lambda: [0.0] * BINS)   # sum of stated probabilities
    true: list[float] = field(default_factory=lambda: [0.0] * BINS)   # how many came true (expected, if uncertain)
    brier: float = 0.0

    def observe(self, p: float, outcome: bool | float) -> None:
        """OUTCOME: whether it came true, or the probability the evidence gives it."""
        o = float(outcome)
        b = min(int(p * BINS), BINS - 1)
        self.n[b] += 1
        self.said[b] += p
        self.true[b] += o
        self.brier += (p - o) ** 2

    def summary(self) -> dict:
        total = sum(self.n)
        if not total:
            return {"n": 0, "brier": None, "calibration_error": None, "bins": []}
        ece = sum(abs(self.said[b] / self.n[b] - self.true[b] / self.n[b]) * self.n[b] / total
                  for b in range(BINS) if self.n[b])
        bins = [{"from": b / BINS, "n": self.n[b], "said": self.said[b] / self.n[b], "came_true": self.true[b] / self.n[b]}
                for b in range(BINS) if self.n[b]]
        return {"n": total, "brier": round(self.brier / total, 6), "calibration_error": round(ece, 6), "bins": bins}

    def state(self) -> dict:
        return asdict(self)

    @classmethod
    def from_state(cls, state: dict | None) -> "Calibration":
        return cls(**state) if state else cls()
