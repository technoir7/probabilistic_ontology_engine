"""
SyntheticDataGenerator — samples EvidenceRecords from ground truth T* or T_alt.

Uses the canonical variable IDs from domain.py so evidence records match
the candidate variable IDs.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import numpy as np

from ...engine.schemas import (
    EvidenceRecord,
    MissingnessType,
    ObservedAssignment,
    SourceType,
    Variable,
)
from .domain import (
    CPT_A,
    CPT_B,
    CPT_C,
    CPT_D_TALT,
    CPT_D_TSTAR,
    CPT_E,
    get_variables,
)


class SyntheticDataGenerator:
    """
    Samples EvidenceRecords from T* or T_alt.

    Parameters
    ----------
    graph        : "T*" | "T_alt"
    random_seed  : int
    missing_rate : float  — fraction of assignments to mark MISSING
    """

    def __init__(
        self,
        graph: str = "T*",
        random_seed: int = 42,
        missing_rate: float = 0.0,
    ) -> None:
        self.graph = graph
        self.rng = np.random.default_rng(random_seed)
        self.missing_rate = missing_rate
        # Share canonical variable IDs with domain
        self._variables: dict[str, Variable] = get_variables()

    def switch_regime(self, new_graph: str) -> None:
        """Switch generating distribution mid-stream (for paradigm shift tests)."""
        self.graph = new_graph

    # ------------------------------------------------------------------
    def sample(self, n: int) -> list[EvidenceRecord]:
        """Draw n independent full-graph records from current regime."""
        return [self._sample_one() for _ in range(n)]

    def sample_variable_only(
        self, variable_name: str, n: int, p_true: float
    ) -> list[EvidenceRecord]:
        """
        n records with only `variable_name` observed (P(var=True)=p_true).
        Used for single-variable CPT convergence tests.
        """
        var = self._variables[variable_name]
        records = []
        for _ in range(n):
            val = bool(self.rng.random() < p_true)
            records.append(EvidenceRecord(
                evidence_id=uuid4(),
                timestamp=datetime.utcnow(),
                observed_assignments=[
                    ObservedAssignment(
                        variable_id=var.variable_id,
                        observed_value=val,
                        missingness=MissingnessType.OBSERVED,
                    )
                ],
                source_type=SourceType.SIMULATION,
            ))
        return records

    # ------------------------------------------------------------------
    def _sample_one(self) -> EvidenceRecord:
        rng = self.rng

        # Root nodes
        a = bool(rng.random() < CPT_A[True])
        b = bool(rng.random() < CPT_B[True])

        # C (parents A, B — same in T* and T_alt)
        c = bool(rng.random() < CPT_C[(a, b)][True])

        # D — differs by regime
        if self.graph == "T*":
            d = bool(rng.random() < CPT_D_TSTAR[b][True])
        else:
            d = bool(rng.random() < CPT_D_TALT[a][True])

        # E (parents C, D — same in T* and T_alt)
        e = bool(rng.random() < CPT_E[(c, d)][True])

        vals = {"A": a, "B": b, "C": c, "D": d, "E": e}

        assignments = []
        for vname, val in vals.items():
            miss = MissingnessType.OBSERVED
            if self.missing_rate > 0 and rng.random() < self.missing_rate:
                miss = MissingnessType.MISSING
            assignments.append(ObservedAssignment(
                variable_id=self._variables[vname].variable_id,
                observed_value=val,
                missingness=miss,
            ))

        return EvidenceRecord(
            evidence_id=uuid4(),
            timestamp=datetime.utcnow(),
            observed_assignments=assignments,
            source_type=SourceType.SIMULATION,
        )

    # ------------------------------------------------------------------
    def get_variable(self, name: str) -> Variable:
        return self._variables[name]

    def get_variable_id(self, name: str):
        return self._variables[name].variable_id

    def variables(self) -> dict[str, Variable]:
        return self._variables
