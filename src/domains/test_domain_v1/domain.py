"""
test-domain-v1 — Synthetic domain with fully known ground truth.

Ground truth graph T*:
  A → C   (P(C=T|A=T)=0.8,  P(C=T|A=F)=0.1)
  B → C   (full CPT below)
  B → D   (P(D=T|B=T)=0.7,  P(D=T|B=F)=0.2)
  C → E   (full CPT below)
  D → E   (full CPT below)

T_alt differs:
  - Removes B → D
  - Adds    A → D  (P(D=T|A=T)=0.75, P(D=T|A=F)=0.15)
"""
from __future__ import annotations

from uuid import UUID, uuid4

from ...engine.variable_identity import stable_variable_id
from ...engine.schemas import (
    DependencyEdge,
    DependencyKind,
    EdgeExistenceThresholdConfig,
    OntologyCandidate,
    Variable,
    DomainType,
)


# ---------------------------------------------------------------------------
# CANONICAL variable definitions (fixed UUIDs so generator and candidates agree)
# ---------------------------------------------------------------------------

_VARIABLE_DEFS: dict[str, Variable] = {
    name: Variable(
        variable_id=stable_variable_id("test-domain-v1", name),
        name=name,
        domain_type=DomainType.BOOLEAN,
        support=[True, False],
    )
    for name in ["A", "B", "C", "D", "E"]
}


def get_variables() -> dict[str, Variable]:
    """Return the shared canonical variable set for test-domain-v1."""
    return _VARIABLE_DEFS


# ---------------------------------------------------------------------------
# Ground truth CPTs (SPEC §20.1)
# ---------------------------------------------------------------------------

CPT_A = {True: 0.5, False: 0.5}
CPT_B = {True: 0.5, False: 0.5}

# C has parents A, B  (key = (A_val, B_val))
CPT_C = {
    (True, True):   {True: 0.95, False: 0.05},
    (True, False):  {True: 0.80, False: 0.20},
    (False, True):  {True: 0.30, False: 0.70},
    (False, False): {True: 0.05, False: 0.95},
}

# D in T* (parent B)
CPT_D_TSTAR = {
    True:  {True: 0.70, False: 0.30},
    False: {True: 0.20, False: 0.80},
}

# D in T_alt (parent A)
CPT_D_TALT = {
    True:  {True: 0.75, False: 0.25},
    False: {True: 0.15, False: 0.85},
}

# E has parents C, D  (key = (C_val, D_val))
CPT_E = {
    (True,  True):  {True: 0.90, False: 0.10},
    (True,  False): {True: 0.85, False: 0.15},
    (False, True):  {True: 0.50, False: 0.50},
    (False, False): {True: 0.10, False: 0.90},
}

# Edge-set signatures for structure comparison
T_STAR_EDGES: frozenset[tuple[str, str]] = frozenset({
    ("A", "C"), ("B", "C"), ("B", "D"), ("C", "E"), ("D", "E")
})
T_ALT_EDGES: frozenset[tuple[str, str]] = frozenset({
    ("A", "C"), ("B", "C"), ("A", "D"), ("C", "E"), ("D", "E")
})

# Ground truth CPT dict keyed by parent_config tuple (for test assertions)
T_STAR_CPTS: dict = {
    "A": {(): {True: 0.5, False: 0.5}},
    "B": {(): {True: 0.5, False: 0.5}},
    "C": {
        (("A", True),  ("B", True)):  {True: 0.95, False: 0.05},
        (("A", True),  ("B", False)): {True: 0.80, False: 0.20},
        (("A", False), ("B", True)):  {True: 0.30, False: 0.70},
        (("A", False), ("B", False)): {True: 0.05, False: 0.95},
    },
    "D": {
        (("B", True),):  {True: 0.70, False: 0.30},
        (("B", False),): {True: 0.20, False: 0.80},
    },
    "E": {
        (("C", True),  ("D", True)):  {True: 0.90, False: 0.10},
        (("C", True),  ("D", False)): {True: 0.85, False: 0.15},
        (("C", False), ("D", True)):  {True: 0.50, False: 0.50},
        (("C", False), ("D", False)): {True: 0.10, False: 0.90},
    },
}


# ---------------------------------------------------------------------------
# Edge factory using canonical variables
# ---------------------------------------------------------------------------

def _make_edge(pname: str, cname: str, prior: float = 0.5) -> DependencyEdge:
    v = _VARIABLE_DEFS
    return DependencyEdge(
        edge_id=uuid4(),
        parent_variable_id=v[pname].variable_id,
        child_variable_id=v[cname].variable_id,
        dependency_kind=DependencyKind.DIRECTED_CONDITIONAL,
        existence_prior=prior,
        existence_probability=prior,
        learnable=True,
        enabled=True,
    )


def _var_list() -> list[Variable]:
    return list(_VARIABLE_DEFS.values())


# ---------------------------------------------------------------------------
# Candidate constructors (all share canonical variable IDs)
# ---------------------------------------------------------------------------

def make_tstar_candidate(module_id: str = "test-domain-v1", gen: int = 0) -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=gen,
        variables=_var_list(),
        edges=[
            _make_edge("A", "C", 0.7),
            _make_edge("B", "C", 0.7),
            _make_edge("B", "D", 0.7),
            _make_edge("C", "E", 0.7),
            _make_edge("D", "E", 0.7),
        ],
        description="T*",
    )


def make_talt_candidate(module_id: str = "test-domain-v1", gen: int = 0) -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=gen,
        variables=_var_list(),
        edges=[
            _make_edge("A", "C", 0.7),
            _make_edge("B", "C", 0.7),
            _make_edge("A", "D", 0.5),   # T_alt key edge
            _make_edge("C", "E", 0.7),
            _make_edge("D", "E", 0.7),
        ],
        description="T_alt",
    )


def make_null_candidate(module_id: str = "test-domain-v1", gen: int = 0) -> OntologyCandidate:
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        generation=gen,
        variables=_var_list(),
        edges=[
            _make_edge("C", "E", 0.5),
        ],
        description="null",
    )


def make_spurious_1_candidate(module_id: str = "test-domain-v1") -> OntologyCandidate:
    """T* + spurious A→D."""
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        variables=_var_list(),
        edges=[
            _make_edge("A", "C", 0.7),
            _make_edge("B", "C", 0.7),
            _make_edge("B", "D", 0.7),
            _make_edge("A", "D", 0.5),   # spurious
            _make_edge("C", "E", 0.7),
            _make_edge("D", "E", 0.7),
        ],
        description="spurious_1",
    )


def make_spurious_2_candidate(module_id: str = "test-domain-v1") -> OntologyCandidate:
    """T* − B→D."""
    return OntologyCandidate(
        candidate_id=uuid4(),
        domain_module_id=module_id,
        variables=_var_list(),
        edges=[
            _make_edge("A", "C", 0.7),
            _make_edge("B", "C", 0.7),
            # B→D removed
            _make_edge("C", "E", 0.7),
            _make_edge("D", "E", 0.7),
        ],
        description="spurious_2",
    )


# ---------------------------------------------------------------------------
# Domain Module
# ---------------------------------------------------------------------------

class TestDomainV1:
    _MODULE_ID = "test-domain-v1"

    def module_id(self) -> str:
        return self._MODULE_ID

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        return [
            make_tstar_candidate(self._MODULE_ID),
            make_talt_candidate(self._MODULE_ID),
            make_null_candidate(self._MODULE_ID),
        ]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.3, 0.7),
        )

    def initial_entities(self) -> list:
        return []

    def initial_assertions(self) -> list:
        return []

    def variable_specs(self) -> list:
        return []

    def initial_parameterizations(self) -> list:
        return []
