"""
Research programmes (Lakatos): what founds one, what its hard core is, and
how a rival to the leader is founded with a fair trial (REFACTOR_SPEC D24,
D26), and how the leader's core is itself put on trial (D27).

A programme is founded by a connection between two concepts, and named for
the pair. Persistence, a concept following its own last value, is common
ground every worldview needs, so it founds none. A descendant inherits its
parent's record of the past (warm start), except a rival, which inherits the
leader's, so the two are judged only on what comes after.
"""
from __future__ import annotations

import math
from uuid import uuid4

from ..model.scoring import bic_penalty, candidate_score
from ..model.scoring import dominant as best_candidate
from ..schemas import (
    CandidateStatus,
    DependencyEdge,
    DependencyKind,
    EvidenceRecord,
    OntologyCandidate,
    Variable,
)
from .synthesis import connections

# The programme of the structures that connect no two concepts: where every
# domain begins, holding at most each concept's persistence.
UNCONNECTED = "unconnected"


def programme_name(a: str, b: str) -> str:
    """A programme founded on the connection between A and B, either way."""
    return "–".join(sorted((a, b)))


def unconnected(domain_module_id: str, variables: list[Variable]) -> OntologyCandidate:
    """Where every domain begins: its concepts, and no hypothesis connecting
    them (D24)."""
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=domain_module_id,
        variables=variables,
        edges=[],
        description=f"{UNCONNECTED}: no hypotheses yet",
        lineage=UNCONNECTED,
    )


def is_persistence(candidate: OntologyCandidate, parent: str, child: str) -> bool:
    """A concept following its own last value: common ground every worldview
    needs, so it founds no programme (D26)."""
    var = candidate.get_variable_by_name(parent)
    return var is not None and var.lag_of == child


def edge(candidate: OntologyCandidate, parent: str, child: str) -> DependencyEdge:
    """A new connection PARENT → CHILD between CANDIDATE's concepts."""
    return DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=candidate.get_variable_by_name(parent).variable_id,
        child_variable_id=candidate.get_variable_by_name(child).variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
        existence_prior=0.5,
        existence_probability=0.5,
        learnable=True,
        enabled=True,
    )


def copied_edges(parent: OntologyCandidate) -> list[DependencyEdge]:
    return [e.model_copy(update={"edge_id": uuid4()}) for e in parent.edges]


def descendant(
    parent: OntologyCandidate, domain_module_id: str, edges: list[DependencyEdge],
    description: str, lineage: str,
) -> OntologyCandidate:
    # Warm-start: inherit the parent's score, so the two differ only by how
    # they predict from here on. The evidence that prompted a connection is
    # already in that score, and counts for the parent as much as the child.
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=domain_module_id,
        generation=parent.generation + 1,
        parent_candidate_id=parent.candidate_id,
        variables=parent.variables,  # shared; immutable at engine level
        edges=edges,
        log_score=parent.log_score,
        evidence_count=parent.evidence_count,
        window_log_score=parent.window_log_score,
        window_evidence=parent.window_evidence,
        status=CandidateStatus.ACTIVE,
        description=description,
        lineage=lineage,
    )


def rival(
    domain_module_id: str,
    active: list[OntologyCandidate],
    recent: list[EvidenceRecord],
    admissible: set[tuple[str, str]],
    held: set[frozenset[tuple[str, str]]],
    max_population_size: int,
) -> OntologyCandidate | None:
    """A rival to the leader, founded on the connection between two concepts
    that the recent evidence most supports and the leader lacks: the
    leader's structure without its hard core, with that connection in its
    place, level with the leader (D26). It shares the leader's auxiliaries,
    denies its core and asserts its own, so the trial is of the core.

    None while half the places hold programmes, so programmes keep room to
    revise themselves; while the leader holds no programme, since its own
    prompted connections found them; or when the evidence prompts nothing
    new."""
    programmes = {c.lineage for c in active if c.lineage != UNCONNECTED}
    if len(programmes) >= max_population_size // 2:
        return None
    leader = best_candidate(active)
    if leader.lineage == UNCONNECTED:
        return None
    core = _core(leader)
    sig = leader.edge_structure_signature()
    for c in connections(leader, recent, admissible):
        if c.reverses or is_persistence(leader, c.parent, c.child):
            continue
        name = programme_name(c.parent, c.child)
        if name in programmes or (sig - core) | {(c.parent, c.child)} in held:
            continue
        kept = [e for e in copied_edges(leader)
                if (leader.get_variable_by_id(e.parent_variable_id).name,
                    leader.get_variable_by_id(e.child_variable_id).name) not in core]
        founded = descendant(leader, domain_module_id, [*kept, edge(leader, c.parent, c.child)],
                             description=f"rival_{c.parent}->{c.child}", lineage=name)
        return _level_with(founded, leader)
    return None


def trial(
    domain_module_id: str,
    active: list[OntologyCandidate],
    held: set[frozenset[tuple[str, str]]],
) -> OntologyCandidate | None:
    """The leader without its hard core, everything else kept, level with it
    (D27): where no anomaly prompts a rival, the core still faces a test, and
    the leader keeps it only by predicting better from here on (Popper).
    Without its core it holds no worldview.

    None while any worldview but the leader's is alive, a trial among them,
    so each is settled before the next; or while the leader holds no core."""
    leader = best_candidate(active)
    if any(c.lineage != leader.lineage for c in active):
        return None
    core = _core(leader)
    if not core or leader.edge_structure_signature() - core in held:
        return None
    (parent, child), = core
    kept = [e for e in copied_edges(leader)
            if (leader.get_variable_by_id(e.parent_variable_id).name,
                leader.get_variable_by_id(e.child_variable_id).name) not in core]
    founded = descendant(leader, domain_module_id, kept,
                         description=f"trial_{parent}->{child}", lineage=UNCONNECTED)
    return _level_with(founded, leader)


def _core(candidate: OntologyCandidate) -> set[tuple[str, str]]:
    """The connection that founded the candidate's programme, if it still
    holds it: its hard core."""
    if "–" not in candidate.lineage:
        return set()
    pair = set(candidate.lineage.split("–"))
    return {e for e in candidate.edge_structure_signature() if set(e) == pair}


def _level_with(founded: OntologyCandidate, leader: OntologyCandidate) -> OntologyCandidate:
    """FOUNDED with the LEADER's record of the past, so neither is ahead on
    the evidence and the trial is on what comes after. Where the rival is
    the simpler, its fit is lowered by the difference in complexity, so it
    ties the leader rather than outranking it before predicting anything:
    the incumbent keeps the lead on a tie."""
    founded = founded.model_copy(update={
        "log_score": leader.log_score, "evidence_count": leader.evidence_count,
        "window_log_score": leader.window_log_score, "window_evidence": leader.window_evidence,
    })
    if founded.window_evidence > 0:
        cheaper = bic_penalty(leader) - bic_penalty(founded)
        if cheaper > 0:
            founded.window_log_score -= cheaper * founded.window_evidence
        # Rounding can leave the founded a hair ahead, which would hand it the
        # lead unearned; step its fit down until it is level or behind.
        while candidate_score(founded) > candidate_score(leader):
            founded.window_log_score = math.nextafter(founded.window_log_score, -math.inf)
    return founded
