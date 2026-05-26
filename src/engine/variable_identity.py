"""Stable variable identity and evidence compatibility helpers."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from .schemas import EvidenceRecord, ObservedAssignment, Variable

_NAMESPACE_PREFIX = "probabilistic-ontology-engine"


def stable_variable_id(domain_module_id: str, variable_name: str) -> UUID:
    """Return a deterministic UUID for a domain variable."""
    key = f"{_NAMESPACE_PREFIX}:variable:{domain_module_id}:{variable_name}"
    return uuid5(NAMESPACE_URL, key)


@dataclass(frozen=True)
class VariableIdentityDiagnostics:
    total_assignments: int
    matched_assignments: int
    mismatched_assignments: int
    position_fallback_assignments: int
    fallback_used: bool

    @property
    def variable_id_match_ratio(self) -> float:
        if self.total_assignments == 0:
            return 1.0
        return self.matched_assignments / self.total_assignments


def normalize_evidence_record_variable_ids(
    record: EvidenceRecord,
    variables: list[Variable],
) -> tuple[EvidenceRecord, VariableIdentityDiagnostics]:
    """
    Return a record whose assignments use current variable IDs when safe.

    Legacy persisted records created before stable variable IDs may contain
    random UUIDs.  If no assignment IDs match but the assignment count matches
    the domain variable count, we map by assignment order, which is how the
    existing domain pipelines emit records.  Partial UUID matches are left
    untouched to avoid guessing across mixed schemas.
    """
    current_ids = {var.variable_id for var in variables}
    total = len(record.observed_assignments)
    matched = sum(1 for assignment in record.observed_assignments if assignment.variable_id in current_ids)
    mismatched = total - matched

    if matched > 0 or total != len(variables):
        return record, VariableIdentityDiagnostics(
            total_assignments=total,
            matched_assignments=matched,
            mismatched_assignments=mismatched,
            position_fallback_assignments=0,
            fallback_used=False,
        )

    remapped: list[ObservedAssignment] = []
    for variable, assignment in zip(variables, record.observed_assignments):
        remapped.append(assignment.model_copy(update={"variable_id": variable.variable_id}))

    normalized = record.model_copy(update={"observed_assignments": remapped})
    return normalized, VariableIdentityDiagnostics(
        total_assignments=total,
        matched_assignments=0,
        mismatched_assignments=mismatched,
        position_fallback_assignments=total,
        fallback_used=total > 0,
    )
