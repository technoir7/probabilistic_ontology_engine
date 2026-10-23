"""
CPTData — a conditional probability table as Dirichlet-smoothed counts.

Pure model code: probabilities, log-likelihood and BIC terms for one variable
given its parents. Storage (ParameterStore) and services use it through its
methods. Moved here from stores/parameter_store.py (REFACTOR_SPEC 2.1) because
it is math, not persistence.

Parent configuration key format: tuple of (parent_name, value) pairs, sorted
by parent_name, e.g. (("A", True), ("B", False)).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Counts serialisation helpers
# ---------------------------------------------------------------------------

def serialize_counts(counts: dict) -> str:
    """
    Serialise a CPTData counts dict to JSON.

    counts key: tuple of (parent_name, value) pairs, e.g. (("A", True), ("B", False))
    counts value: dict of {support_value: float_count}

    Both tuple keys and dict keys are serialised via repr() so that
    ast.literal_eval() can round-trip booleans and strings faithfully.
    """
    entries = []
    for parent_config, val_dict in counts.items():
        entries.append({
            "k": repr(parent_config),
            "v": {repr(k): v for k, v in val_dict.items()},
        })
    return json.dumps(entries)


def deserialize_counts(counts_json: str) -> dict:
    """Inverse of serialize_counts."""
    entries = json.loads(counts_json)
    counts: dict = {}
    for entry in entries:
        key = ast.literal_eval(entry["k"])
        val_dict = {ast.literal_eval(k): v for k, v in entry["v"].items()}
        counts[key] = val_dict
    return counts


# ---------------------------------------------------------------------------
# CPTData
# ---------------------------------------------------------------------------

@dataclass
class CPTData:
    variable_name: str
    parents: list[str]              # sorted list of parent names
    support: list[Any]              # variable's possible values
    counts: dict                    # {parent_config_tuple: {value: count}}
    alpha: float = 1.0              # Dirichlet prior pseudo-count per cell

    def config_key(self, parent_assignment: Mapping[str, Any]) -> tuple:
        """Row key for a parent assignment; only this CPT's parents are used."""
        return tuple(sorted((p, parent_assignment[p]) for p in self.parents))

    def ensure_row(self, parent_assignment: Mapping[str, Any]) -> None:
        """
        Create an all-zero row for this parent configuration if absent.

        Observed configurations count toward the BIC parameter penalty
        (bic_score uses len(counts)), so a configuration seen with negligible
        weight must still exist as a row.
        """
        key = self.config_key(parent_assignment)
        if key not in self.counts:
            self.counts[key] = {v: 0 for v in self.support}

    def add(self, value: Any, parent_assignment: Mapping[str, Any], weight: float = 1) -> None:
        """Add *weight* (default one whole observation) to count(value | parents)."""
        self.ensure_row(parent_assignment)
        row = self.counts[self.config_key(parent_assignment)]
        row[value] = row.get(value, 0) + weight

    def row(self, parent_assignment: Mapping[str, Any]) -> dict[Any, float]:
        """Copy of the raw counts for one parent configuration ({} if never seen)."""
        return dict(self.counts.get(self.config_key(parent_assignment), {}))

    def discount(self, factor: float) -> None:
        """Count every observation for `factor` of what it did (D17)."""
        for row in self.counts.values():
            for v in row:
                row[v] *= factor

    def total_count(self) -> float:
        return sum(sum(row.values()) for row in self.counts.values())

    def serialized_counts(self) -> str:
        return serialize_counts(self.counts)

    def get_probability(self, value: Any, parent_assignment: dict[str, Any]) -> float:
        """Compute smoothed P(variable=value | parent_assignment)."""
        r = len(self.support)
        row = self.counts.get(self.config_key(parent_assignment), {})
        n_q = sum(row.values())
        n_qk = row.get(value, 0)
        return (n_qk + self.alpha) / (n_q + self.alpha * r)

    def log_prob(self, value: Any, parent_assignment: dict[str, Any]) -> float:
        p = self.get_probability(value, parent_assignment)
        return math.log(max(p, 1e-12))

    def get_probability_given(self, value: Any, known: Mapping[str, Any]) -> float:
        """Smoothed P(variable=value | the parents in KNOWN), the others
        unknown: the rows that agree with KNOWN, pooled, so each unknown
        parent is averaged over as often as the data has seen its values.
        With every parent known, this is get_probability."""
        known = {p: v for p, v in known.items() if p in self.parents}
        if len(known) == len(self.parents):
            return self.get_probability(value, known)
        rows = [row for key, row in self.counts.items() if all(dict(key)[p] == v for p, v in known.items())]
        n_q = sum(sum(row.values()) for row in rows)
        n_qk = sum(row.get(value, 0) for row in rows)
        return (n_qk + self.alpha) / (n_q + self.alpha * len(self.support))

    def mle_log_likelihood(self) -> float:
        """Log-likelihood of all data under MLE (no smoothing)."""
        ll = 0.0
        for parent_config, row in self.counts.items():
            n_q = sum(row.values())
            if n_q == 0:
                continue
            for v, n_qk in row.items():
                if n_qk > 0:
                    ll += n_qk * math.log(n_qk / n_q)
        return ll

    def bic_score(self) -> float:
        """BIC score = log_lik_MLE - 0.5 * num_free_params * log(N)."""
        n_total = sum(
            sum(row.values()) for row in self.counts.values()
        )
        if n_total == 0:
            return 0.0
        ll = self.mle_log_likelihood()
        # Number of free params = prod(parent cardinalities) * (|support| - 1)
        # We approximate parent cardinalities as len(support) = 2 for BOOLEAN
        n_configs = max(len(self.counts), 1)
        n_free = n_configs * (len(self.support) - 1)
        penalty = 0.5 * n_free * math.log(max(n_total, 1))
        return ll - penalty

    def bic_score_without_parent(self, parent_name: str) -> float:
        """BIC score for the variable as if `parent_name` were removed from Pa."""
        # Marginalize out parent_name from counts
        marginal_counts: dict = {}
        for parent_config, row in self.counts.items():
            reduced = tuple((k, v) for k, v in parent_config if k != parent_name)
            if reduced not in marginal_counts:
                marginal_counts[reduced] = {v: 0 for v in self.support}
            for val, cnt in row.items():
                marginal_counts[reduced][val] = marginal_counts[reduced].get(val, 0) + cnt

        n_total = sum(sum(r.values()) for r in marginal_counts.values())
        if n_total == 0:
            return 0.0

        ll = 0.0
        for reduced, row in marginal_counts.items():
            n_q = sum(row.values())
            if n_q == 0:
                continue
            for v, n_qk in row.items():
                if n_qk > 0:
                    ll += n_qk * math.log(n_qk / n_q)

        n_configs = max(len(marginal_counts), 1)
        n_free = n_configs * (len(self.support) - 1)
        penalty = 0.5 * n_free * math.log(max(n_total, 1))
        return ll - penalty

    def digest(self) -> str:
        """SHA-256 digest of the counts for reproducibility checking."""
        blob = json.dumps(
            {str(k): v for k, v in sorted(self.counts.items(), key=lambda x: str(x[0]))},
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def copy(self) -> CPTData:
        return CPTData(
            variable_name=self.variable_name,
            parents=list(self.parents),
            support=list(self.support),
            counts=copy.deepcopy(self.counts),
            alpha=self.alpha,
        )
