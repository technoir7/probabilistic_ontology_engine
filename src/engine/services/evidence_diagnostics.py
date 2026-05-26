"""Diagnostics over raw evidence coverage and dependence."""
from __future__ import annotations

import math
from collections import Counter
from itertools import combinations
from typing import Any

from ..schemas import EvidenceRecord, MissingnessType, Variable


def build_entropy_diagnostics(
    records: list[EvidenceRecord],
    variables: list[Variable],
) -> dict[str, Any]:
    """Summarise value coverage, entropy, row patterns, and pairwise MI."""
    variable_names = [v.name for v in variables]
    variable_ids = {v.variable_id: v.name for v in variables}
    rows = [_record_to_observed_map(record, variable_ids) for record in records]
    total_rows = len(records)

    variables_out: dict[str, dict[str, Any]] = {}
    for name in variable_names:
        observed_values = [
            row[name]
            for row in rows
            if name in row
        ]
        value_counts = Counter(_value_key(value) for value in observed_values)
        observed_count = len(observed_values)
        variables_out[name] = {
            "value_counts": dict(sorted(value_counts.items())),
            "observed_count": observed_count,
            "missing_count": total_rows - observed_count,
            "entropy": _entropy(observed_values),
        }

    return {
        "total_evidence_rows": total_rows,
        "variables": variables_out,
        "unique_observed_patterns": _unique_patterns(rows, variable_names),
        "pairwise_mutual_information": _pairwise_mi(rows, variable_names),
    }


def _record_to_observed_map(
    record: EvidenceRecord,
    variable_ids: dict[Any, str],
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for assignment in record.observed_assignments:
        name = variable_ids.get(assignment.variable_id)
        if name is None or assignment.missingness != MissingnessType.OBSERVED:
            continue
        observed[name] = assignment.observed_value
    return observed


def _value_key(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "null"
    return str(value)


def _entropy(values: list[Any]) -> float:
    if not values:
        return 0.0
    counts = Counter(_hashable_value(value) for value in values)
    total = len(values)
    entropy = -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
        if count > 0
    )
    return 0.0 if abs(entropy) < 1e-12 else entropy


def _unique_patterns(
    rows: list[dict[str, Any]],
    variable_names: list[str],
) -> list[dict[str, Any]]:
    counts: Counter[tuple[Any, ...]] = Counter(
        tuple(_hashable_value(row.get(name)) for name in variable_names)
        for row in rows
    )
    patterns = []
    for key, count in counts.items():
        pattern = {
            name: _restore_hashable_value(value)
            for name, value in zip(variable_names, key)
        }
        patterns.append({"pattern": pattern, "count": count})
    return sorted(
        patterns,
        key=lambda item: (-item["count"], str(item["pattern"])),
    )


def _pairwise_mi(
    rows: list[dict[str, Any]],
    variable_names: list[str],
) -> list[dict[str, Any]]:
    pairs = []
    for left, right in combinations(variable_names, 2):
        joint_values = [
            (_hashable_value(row[left]), _hashable_value(row[right]))
            for row in rows
            if left in row and right in row
        ]
        pairs.append({
            "variable_x": left,
            "variable_y": right,
            "joint_observed_count": len(joint_values),
            "mutual_information": _mutual_information(joint_values),
        })
    return pairs


def _mutual_information(joint_values: list[tuple[Any, Any]]) -> float:
    if not joint_values:
        return 0.0
    total = len(joint_values)
    joint_counts = Counter(joint_values)
    left_counts = Counter(left for left, _ in joint_values)
    right_counts = Counter(right for _, right in joint_values)

    mi = 0.0
    for (left, right), joint_count in joint_counts.items():
        p_xy = joint_count / total
        p_x = left_counts[left] / total
        p_y = right_counts[right] / total
        mi += p_xy * math.log2(p_xy / (p_x * p_y))
    return 0.0 if abs(mi) < 1e-12 else mi


def _hashable_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_hashable_value(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable_value(v)) for k, v in value.items()))
    return value


def _restore_hashable_value(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return {
                key: _restore_hashable_value(val)
                for key, val in value
            }
        return [_restore_hashable_value(item) for item in value]
    return value
