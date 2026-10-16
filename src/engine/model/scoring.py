"""
The one candidate score: BIC-corrected average log-likelihood over the score
window, where older evidence counts for less (half-life SCORE_HALF_LIFE_RECORDS).

Population ranking, pruning, dominance, structure diagnostics and the API all
compare candidates with this. It lives in the model layer (not services/)
because OntologyPopulation.dominant() uses it and the art domain calls that.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from ..schemas import OntologyCandidate


def free_parameter_count(candidate: OntologyCandidate) -> int:
    """
    k for the BIC penalty: 2**(number of parents) per BOOLEAN variable.

    Counts ALL edges, including disabled (pruned) ones. This penalizes a
    candidate that explored extra edges even after pruning them, so a
    warm-started variant cannot game the score by adding and then pruning
    spurious edges.
    """
    k = 0
    for v in candidate.variables:
        n_parents = sum(1 for e in candidate.edges if e.child_variable_id == v.variable_id)
        k += 2 ** n_parents
    return k


# A structure is judged mostly on its last few hundred records, so one that fits
# a new regime can overtake one that fitted the old (TEST-L3-03). Over seeds
# 0-39: 100 detects the shift within 200 records in 35/40 runs with ~2% of
# stationary batches flipping the dominant; 150-200 flip less but detect
# less; no window detects 6/20 (REFACTOR_SPEC D14).
SCORE_HALF_LIFE_RECORDS = 100


def add_to_window(window_ll: float, window_n: float, batch_ll: float, batch_n: int) -> tuple[float, float]:
    """Discount the window by the batch's length, then add the batch."""
    decay = 0.5 ** (batch_n / SCORE_HALF_LIFE_RECORDS)
    return window_ll * decay + batch_ll, window_n * decay + batch_n


def average_log_likelihood(candidate: OntologyCandidate) -> float:
    """Per-record log-likelihood over the score window. Requires window_evidence > 0."""
    return candidate.window_log_score / candidate.window_evidence


def bic_penalty(candidate: OntologyCandidate) -> float:
    """Per-record BIC penalty 0.5·k·log(N)/N, N = window evidence (> 0)."""
    n = candidate.window_evidence
    return 0.5 * free_parameter_count(candidate) * math.log(max(n, 2)) / n


def candidate_score(candidate: OntologyCandidate, *, bic_multiplier: float = 1.0) -> float:
    """
    Window average log-likelihood minus the BIC penalty; -inf with no evidence.

    Averaging makes candidates introduced late comparable with old ones.
    ``bic_multiplier`` is 1.0 everywhere in production; the structure
    diagnostics also report 0.25 ("explore") side by side.
    """
    if candidate.window_evidence <= 0:
        return float("-inf")
    return average_log_likelihood(candidate) - bic_penalty(candidate) * bic_multiplier


def dominant(candidates: Sequence[OntologyCandidate]) -> Optional[OntologyCandidate]:
    """Highest-scoring candidate; the first one wins ties."""
    return max(candidates, key=candidate_score) if candidates else None


def score_weights(candidates: Sequence[OntologyCandidate]) -> list[float]:
    """
    Posterior weight of each structure under the BIC approximation.

    log P(data | structure) ≈ n · candidate_score (total log-likelihood minus
    the BIC penalty), with n and the total taken over the score window.
    Softmaxing the per-record averages instead gives near equal weights,
    because averages differ by hundredths of a nat (B21).
    Unscored candidates get no weight; if none is scored, all share it.
    """
    if not candidates:
        return []
    log_w = [c.window_evidence * candidate_score(c) if c.window_evidence > 0 else -math.inf for c in candidates]
    best = max(log_w)
    if best == -math.inf:
        return [1.0 / len(candidates)] * len(candidates)
    weights = [math.exp(lw - best) for lw in log_w]
    total = sum(weights)
    return [w / total for w in weights]


def structure_entropy(candidates: Sequence[OntologyCandidate]) -> float:
    """Entropy of score_weights: 0 when one structure dominates completely."""
    return -sum(w * math.log(w + 1e-12) for w in score_weights(candidates) if w > 0)
