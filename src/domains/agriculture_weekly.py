"""Weekly cadence helpers shared by agricultural domains."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from ..engine.schemas import EvidenceRecord

AGRICULTURE_DOMAIN_IDS = {"corn-v1", "soybean-v1"}


def is_agriculture_domain(domain_module_id: str) -> bool:
    return domain_module_id in AGRICULTURE_DOMAIN_IDS


def iso_week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def iso_week_end(day: date) -> date:
    return iso_week_start(day) + timedelta(days=6)


def latest_week_ending_on_or_before(day: date) -> date:
    """Return the most recent ISO week-ending Sunday on or before day."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def latest_complete_week_ending(as_of: date) -> date:
    """Return the latest completed weekly evidence date for a scheduler run."""
    return latest_week_ending_on_or_before(as_of - timedelta(days=1))


def canonical_weekly_timestamp(day: date) -> datetime:
    week_end = latest_week_ending_on_or_before(day)
    return datetime(week_end.year, week_end.month, week_end.day, tzinfo=timezone.utc)


def weekly_backfill_dates(backfill_days: int, today: date | None = None) -> list[date]:
    """Return unique week-ending dates covering the prior backfill window."""
    if backfill_days <= 0:
        return []
    today = today or datetime.now(timezone.utc).date()
    week_ends = {
        latest_week_ending_on_or_before(today - timedelta(days=delta))
        for delta in range(backfill_days, 0, -1)
    }
    return sorted(week_ends)


def evidence_state_signature(record: EvidenceRecord) -> tuple[Any, ...]:
    """State signature ignoring record id, source, and timestamp."""
    return tuple(
        (
            str(assignment.variable_id),
            _hashable_value(assignment.observed_value),
            assignment.missingness.value,
            _hashable_value(assignment.probabilities),
        )
        for assignment in record.observed_assignments
    )


def raw_evidence_state_signature(assignments: Iterable[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            str(assignment.get("variable_id")),
            _hashable_value(assignment.get("observed_value")),
            assignment.get("missingness", "OBSERVED"),
            _hashable_value(assignment.get("probabilities")),
        )
        for assignment in assignments
    )


def is_duplicate_recent_state(record: EvidenceRecord, recent_records: list[dict[str, Any]]) -> bool:
    if not recent_records:
        return False
    latest = recent_records[0]
    return evidence_state_signature(record) == raw_evidence_state_signature(
        latest.get("assignments", [])
    )


def _hashable_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_hashable_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k).lower(), _hashable_value(v)) for k, v in value.items()))
    return value
