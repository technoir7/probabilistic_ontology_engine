"""
Synthesis: hypotheses formed from the evidence (REFACTOR_SPEC D24).

The engine begins with its concepts and no connections between them. It
forms a hypothesis by asking, of a structure it holds: which connection it
lacks, or which of its connections turned the other way, would best have
explained the evidence already seen? A change is offered only when what it
explains exceeds what its extra parameters could fit by chance (BIC's
penalty), and it is then judged like any other hypothesis, on evidence that
comes after it. The past suggests; only the future confirms, so no evidence
is counted twice.

From nothing, a connection's direction is undecided: "A bears on B" and "B
bears on A" explain the same evidence. A direction is offered for reversal
only when the evidence prefers it, as when two independent signals both
bear on a third.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import product
from typing import Any, Iterable

from ..schemas import EvidenceRecord, MissingnessType, OntologyCandidate

_SEEN = (MissingnessType.OBSERVED, MissingnessType.SOFT_OBSERVED)
# Gains below this are floating-point error: turning round a connection the
# evidence cannot orient changes the score by exactly nothing in theory.
_ROUNDING = 1e-9


@dataclass(frozen=True)
class Connection:
    parent: str
    child: str
    gain: float              # nats it would have explained, net of the chance penalty
    reverses: bool = False   # True: child -> parent is held, and this turns it round


def connections(
    candidate: OntologyCandidate,
    records: Iterable[EvidenceRecord],
    admissible: set[tuple[str, str]],
) -> list[Connection]:
    """Admissible connections CANDIDATE lacks, and reversals of ones it holds,
    that would have explained RECORDS better than chance, best first. None
    closes a cycle."""
    names = {str(v.variable_id): v.name for v in candidate.variables}
    support = {v.name: len(v.support) for v in candidate.variables}
    seen = [_distributions(r, names) for r in records]
    parents = {v.name: sorted(p.name for p in candidate.get_parents(v.variable_id))
               for v in candidate.variables}
    held = candidate.edge_structure_signature()

    def score(child: str, given: list[str], rows: list[dict]) -> float:
        return _family_score(rows, child, given, support)

    found = []
    for parent, child in sorted(admissible - held):
        if parent not in support or child not in support:
            continue
        if (child, parent) in held:
            if _reaches(held - {(child, parent)}, child, parent):
                continue
            involved = {parent, child, *parents[parent], *parents[child]}
            rows = [d for d in seen if involved <= d.keys()]
            gain = (score(child, parents[child] + [parent], rows)
                    + score(parent, [p for p in parents[parent] if p != child], rows)
                    - score(child, parents[child], rows) - score(parent, parents[parent], rows))
            reverses = True
        else:
            if _reaches(held, child, parent):
                continue
            rows = [d for d in seen if {parent, child, *parents[child]} <= d.keys()]
            gain = score(child, parents[child] + [parent], rows) - score(child, parents[child], rows)
            reverses = False
        if gain > _ROUNDING:
            found.append(Connection(parent, child, gain, reverses))
    return sorted(found, key=lambda c: -c.gain)


def _distributions(record: EvidenceRecord, names: dict[str, str]) -> dict[str, dict[Any, float]]:
    """What the record shows of each variable it saw; missing ones are absent."""
    out = {}
    for a in record.observed_assignments:
        name = names.get(str(a.variable_id))
        if name is None or a.missingness not in _SEEN:
            continue
        out[name] = dict(a.probabilities) if a.missingness == MissingnessType.SOFT_OBSERVED and a.probabilities \
            else {a.observed_value: 1.0}
    return out


def _family_score(rows: list[dict], child: str, given: list[str], support: dict[str, int]) -> float:
    """How well GIVEN would have predicted CHILD over ROWS, from expected
    counts at their best-fitting probabilities, less BIC's penalty for the
    table's free parameters."""
    if not rows:
        return 0.0
    counts: dict[tuple, float] = defaultdict(float)
    involved = [child, *given]
    for dists in rows:
        for values in product(*(dists[v].items() for v in involved)):
            w = math.prod(p for _, p in values)
            if w > 0:
                counts[tuple(x for x, _ in values)] += w
    by_given: dict[tuple, float] = defaultdict(float)
    for (_, *g), w in counts.items():
        by_given[tuple(g)] += w
    fit = sum(w * math.log(w / by_given[tuple(g)]) for (_, *g), w in counts.items())
    free = (support[child] - 1) * math.prod(support[g] for g in given)
    return fit - 0.5 * free * math.log(len(rows))


def _reaches(edges: frozenset[tuple[str, str]], start: str, goal: str) -> bool:
    """Is there a directed path START ⇝ GOAL? (Then GOAL → START closes a cycle.)"""
    out: dict[str, list[str]] = defaultdict(list)
    for p, c in edges:
        out[p].append(c)
    stack, visited = [start], set()
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        if node not in visited:
            visited.add(node)
            stack.extend(out[node])
    return False
