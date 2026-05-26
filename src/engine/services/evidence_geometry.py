"""Informational geometry diagnostics for evidence streams."""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from typing import Any

from ..schemas import EvidenceRecord, MissingnessType, Variable
from ..variable_identity import normalize_evidence_record_variable_ids

logger = logging.getLogger(__name__)

_OBSERVED_MISSINGNESS = {
    MissingnessType.OBSERVED,
    MissingnessType.SOFT_OBSERVED,
}


def build_evidence_geometry_diagnostics(
    records: list[EvidenceRecord],
    variables: list[Variable],
) -> dict[str, Any]:
    """Measure entropy, state diversity, transitions, MI, and weekly compression."""
    variable_names = [v.name for v in variables]
    variable_ids = {v.variable_id: v.name for v in variables}
    ordered_records = sorted(records, key=lambda record: record.timestamp)
    rows = []
    total_assignment_count = 0
    matched_assignment_count = 0
    mismatched_assignment_count = 0
    position_fallback_assignment_count = 0
    fallback_used = False
    for record in ordered_records:
        normalized_record, identity_diag = normalize_evidence_record_variable_ids(
            record, variables
        )
        total_assignment_count += identity_diag.total_assignments
        matched_assignment_count += identity_diag.matched_assignments
        mismatched_assignment_count += identity_diag.mismatched_assignments
        position_fallback_assignment_count += identity_diag.position_fallback_assignments
        fallback_used = fallback_used or identity_diag.fallback_used
        state = _record_to_state(normalized_record, variable_ids, variable_names)
        rows.append(state)
    total_records = len(ordered_records)

    variable_stats = _variable_stats(rows, variable_names, total_records)
    pattern_counts = _pattern_counts(rows, variable_names)
    mi_matrix, joint_counts, pair_summaries = _pairwise_mi(rows, variable_names, variable_stats)
    temporal = _temporal_stats(ordered_records, rows, variable_names)

    entropies = [
        (name, stats["shannon_entropy"])
        for name, stats in variable_stats.items()
    ]
    highest_mi_pair = max(
        pair_summaries,
        key=lambda item: (item["mutual_information"], item["joint_observed_count"]),
        default=None,
    )
    lowest_entropy = min(entropies, key=lambda item: item[1], default=None)
    highest_entropy = max(entropies, key=lambda item: item[1], default=None)

    diagnostics = {
        "total_evidence_records": total_records,
        "total_assignment_count": total_assignment_count,
        "variable_id_match_count": matched_assignment_count,
        "variable_id_mismatch_count": mismatched_assignment_count,
        "position_fallback_assignment_count": position_fallback_assignment_count,
        "variable_id_match_ratio": _safe_ratio(
            matched_assignment_count,
            total_assignment_count,
        ),
        "used_assignment_position_fallback": fallback_used,
        "variables": variable_stats,
        "unique_observed_assignment_patterns": len(pattern_counts),
        "top_10_most_common_assignment_patterns": _top_patterns(pattern_counts, variable_names, 10),
        "pairwise_mutual_information_matrix": mi_matrix,
        "pairwise_joint_observed_counts": joint_counts,
        "average_pairwise_mi": _average_pairwise_mi(pair_summaries),
        "highest_mi_variable_pair": highest_mi_pair,
        "lowest_entropy_variable": (
            {"variable": lowest_entropy[0], "shannon_entropy": lowest_entropy[1]}
            if lowest_entropy
            else None
        ),
        "highest_entropy_variable": (
            {"variable": highest_entropy[0], "shannon_entropy": highest_entropy[1]}
            if highest_entropy
            else None
        ),
        **temporal,
    }

    logger.debug(
        "Evidence geometry: records=%d unique_patterns=%d avg_mi=%.4f "
        "entropy_min=%s entropy_max=%s daily_transitions=%d weekly_transitions=%d "
        "compression_ratio=%.4f",
        total_records,
        diagnostics["unique_observed_assignment_patterns"],
        diagnostics["average_pairwise_mi"],
        diagnostics["lowest_entropy_variable"],
        diagnostics["highest_entropy_variable"],
        diagnostics["daily_transition_count"],
        diagnostics["weekly_transition_count"],
        diagnostics["compression_ratio_daily_to_weekly"],
    )
    return diagnostics


def _record_to_state(
    record: EvidenceRecord,
    variable_ids: dict[Any, str],
    variable_names: list[str],
) -> dict[str, Any]:
    state = {name: None for name in variable_names}
    for assignment in record.observed_assignments:
        name = variable_ids.get(assignment.variable_id)
        if name is None:
            continue
        if assignment.missingness not in _OBSERVED_MISSINGNESS:
            continue
        state[name] = assignment.observed_value
    return state


def _variable_stats(
    rows: list[dict[str, Any]],
    variable_names: list[str],
    total_records: int,
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for name in variable_names:
        observed_values = [row[name] for row in rows if row.get(name) is not None]
        value_counts = Counter(_value_key(value) for value in observed_values)
        observed_count = len(observed_values)
        missing_count = total_records - observed_count
        stats[name] = {
            "observed_count": observed_count,
            "missing_count": missing_count,
            "observed_ratio": _safe_ratio(observed_count, total_records),
            "missing_ratio": _safe_ratio(missing_count, total_records),
            "shannon_entropy": _entropy(observed_values),
            "transition_count": _observed_transition_count(rows, name),
            "unique_value_count": len(value_counts),
            "value_distribution": dict(sorted(value_counts.items())),
        }
    return stats


def _pattern_counts(
    rows: list[dict[str, Any]],
    variable_names: list[str],
) -> Counter[tuple[Any, ...]]:
    return Counter(
        tuple(_hashable_value(row.get(name)) for name in variable_names)
        for row in rows
    )


def _top_patterns(
    counts: Counter[tuple[Any, ...]],
    variable_names: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    patterns = []
    for key, count in counts.items():
        patterns.append({
            "pattern": _key_to_pattern(key, variable_names),
            "count": count,
        })
    return sorted(
        patterns,
        key=lambda item: (-item["count"], str(item["pattern"])),
    )[:limit]


def _pairwise_mi(
    rows: list[dict[str, Any]],
    variable_names: list[str],
    variable_stats: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, int]], list[dict[str, Any]]]:
    matrix: dict[str, dict[str, float]] = {
        left: {right: 0.0 for right in variable_names}
        for left in variable_names
    }
    joint_counts: dict[str, dict[str, int]] = {
        left: {right: 0 for right in variable_names}
        for left in variable_names
    }

    for name in variable_names:
        matrix[name][name] = variable_stats[name]["shannon_entropy"]
        joint_counts[name][name] = variable_stats[name]["observed_count"]

    pair_summaries: list[dict[str, Any]] = []
    for left, right in combinations(variable_names, 2):
        joint_values = [
            (_hashable_value(row[left]), _hashable_value(row[right]))
            for row in rows
            if row.get(left) is not None and row.get(right) is not None
        ]
        mi = _mutual_information(joint_values)
        matrix[left][right] = mi
        matrix[right][left] = mi
        joint_counts[left][right] = len(joint_values)
        joint_counts[right][left] = len(joint_values)
        pair_summaries.append({
            "variable_x": left,
            "variable_y": right,
            "joint_observed_count": len(joint_values),
            "mutual_information": mi,
        })
    return matrix, joint_counts, pair_summaries


def _temporal_stats(
    records: list[EvidenceRecord],
    rows: list[dict[str, Any]],
    variable_names: list[str],
) -> dict[str, Any]:
    daily_keys = [
        tuple(_hashable_value(row.get(name)) for name in variable_names)
        for row in rows
    ]
    daily_state_count = len(daily_keys)
    daily_unique_state_count = len(set(daily_keys))
    daily_transition_count = _sequence_transition_count(daily_keys)

    weekly_buckets: dict[tuple[int, int], list[tuple[Any, ...]]] = defaultdict(list)
    for record, key in zip(records, daily_keys):
        iso = record.timestamp.date().isocalendar()
        weekly_buckets[(iso.year, iso.week)].append(key)

    weekly_sequence: list[tuple[Any, ...]] = []
    weekly_aggregation = []
    for iso_year, iso_week in sorted(weekly_buckets):
        keys = weekly_buckets[(iso_year, iso_week)]
        compressed_keys = _dedupe_preserve_order(keys)
        weekly_sequence.extend(compressed_keys)
        weekly_aggregation.append({
            "iso_year": iso_year,
            "iso_week": iso_week,
            "week_start_date": _iso_week_start(iso_year, iso_week).isoformat(),
            "daily_state_count": len(keys),
            "compressed_state_count": len(compressed_keys),
            "unique_state_count": len(set(keys)),
            "top_patterns": _top_patterns(Counter(keys), variable_names, 10),
        })

    weekly_compressed_state_count = len(weekly_sequence)
    weekly_unique_state_count = len(set(weekly_sequence))
    weekly_transition_count = _sequence_transition_count(weekly_sequence)
    compression_ratio = _safe_ratio(daily_state_count, weekly_compressed_state_count)
    density = _safe_ratio(daily_unique_state_count, daily_state_count)
    transitions_per_month = _transitions_per_month(records, daily_transition_count)

    return {
        "cadence_detected": _cadence_detected(records),
        "daily_state_count": daily_state_count,
        "daily_unique_state_count": daily_unique_state_count,
        "weekly_bucket_count": len(weekly_buckets),
        "weekly_compressed_state_count": weekly_compressed_state_count,
        "weekly_unique_state_count": weekly_unique_state_count,
        "daily_transition_count": daily_transition_count,
        "weekly_transition_count": weekly_transition_count,
        "compression_ratio_daily_to_weekly": compression_ratio,
        "weekly_compression_ratio": compression_ratio,
        "effective_state_density": density,
        "effective_transitions_per_month": transitions_per_month,
        "weekly_retention_ratio": _safe_ratio(weekly_compressed_state_count, daily_state_count),
        "unique_state_retention_ratio": _safe_ratio(weekly_unique_state_count, daily_unique_state_count),
        "weekly_aggregation": weekly_aggregation,
    }


def _cadence_detected(records: list[EvidenceRecord]) -> str:
    if len(records) < 2:
        return "insufficient_data"
    dates = [record.timestamp.date() for record in records]
    gaps = [
        (current - previous).days
        for previous, current in zip(dates, dates[1:])
        if (current - previous).days > 0
    ]
    if not gaps:
        return "duplicate_timestamps"
    gaps_sorted = sorted(gaps)
    median = gaps_sorted[len(gaps_sorted) // 2]
    if median <= 2:
        return "daily"
    if 5 <= median <= 9:
        return "weekly"
    return "irregular"


def _transitions_per_month(records: list[EvidenceRecord], transitions: int) -> float:
    if len(records) < 2:
        return 0.0
    start = records[0].timestamp.date()
    end = records[-1].timestamp.date()
    span_days = max((end - start).days, 1)
    months = span_days / 30.4375
    return _safe_ratio(transitions, months)


def _observed_transition_count(rows: list[dict[str, Any]], variable_name: str) -> int:
    transitions = 0
    previous = None
    has_previous = False
    for row in rows:
        value = row.get(variable_name)
        if value is None:
            continue
        current = _hashable_value(value)
        if has_previous and current != previous:
            transitions += 1
        previous = current
        has_previous = True
    return transitions


def _sequence_transition_count(keys: list[tuple[Any, ...]]) -> int:
    return sum(
        1
        for previous, current in zip(keys, keys[1:])
        if previous != current
    )


def _dedupe_preserve_order(keys: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    seen = set()
    result = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _iso_week_start(iso_year: int, iso_week: int) -> date:
    return date.fromisocalendar(iso_year, iso_week, 1)


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
    return _clean_float(entropy)


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
    return _clean_float(mi)


def _average_pairwise_mi(pair_summaries: list[dict[str, Any]]) -> float:
    if not pair_summaries:
        return 0.0
    return _clean_float(
        sum(item["mutual_information"] for item in pair_summaries) / len(pair_summaries)
    )


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return _clean_float(numerator / denominator)


def _clean_float(value: float) -> float:
    if abs(value) < 1e-12:
        return 0.0
    return float(value)


def _value_key(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "null"
    return str(value)


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


def _key_to_pattern(key: tuple[Any, ...], variable_names: list[str]) -> dict[str, Any]:
    return {
        name: _restore_hashable_value(value)
        for name, value in zip(variable_names, key)
    }
