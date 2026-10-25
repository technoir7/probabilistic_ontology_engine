"""
Epistemic health, observed each learning cycle before the batch is learned
(REFACTOR_SPEC D18): the population's weighted predictive log-likelihood
against the leader's, and the calibration of both, from the batch's last
record (live batches are one week). Calibration is judged against each
signal rounded to true or false and, for the leader, against the
probability the evidence itself gave it (D21). Changes nothing the engine
learns.
"""
from __future__ import annotations

from uuid import UUID

from ..model.calibration import Calibration, mixture_log_likelihood
from ..model.scoring import score_weights
from ..schemas import EvidenceRecord, OntologyCandidate
from .inference import InferenceService

_NEGLIGIBLE_WEIGHT = 1e-3
_SEEN = ("OBSERVED", "SOFT_OBSERVED")


class EpistemicHealth:
    def __init__(self, inference: InferenceService) -> None:
        self.inference = inference
        self._leader: dict[str, Calibration] = {}
        self._population: dict[str, Calibration] = {}
        self._leader_vs_evidence: dict[str, Calibration] = {}
        self._last: dict[str, dict] = {}

    def observe(self, domain: str, candidates: list[OntologyCandidate], leader: OntologyCandidate | None,
                scores: dict[UUID, float], batch: list[EvidenceRecord]) -> None:
        if leader is None or not candidates or not batch:
            return
        weights = score_weights(candidates)
        self._last[domain] = {
            "leader_ll": scores[leader.candidate_id],
            "population_ll": mixture_log_likelihood([scores[c.candidate_id] for c in candidates], weights),
        }
        if leader.evidence_count == 0:
            return  # nothing learned yet to be confident about
        record = batch[-1]
        names = {str(v.variable_id): v.name for v in leader.variables}
        judged = [a for a in record.observed_assignments
                  if a.missingness.value in _SEEN and str(a.variable_id) in names]
        seen = {names[str(a.variable_id)]: a.observed_value for a in judged}
        evidence = {names[str(a.variable_id)]: a for a in judged}
        self._last[domain]["forecast_ll"] = self.inference.forecast_log_prob(leader, seen)
        lead = self.inference.leave_one_out(leader, seen)
        heavy = [(c, w) for c, w in zip(candidates, weights) if w > _NEGLIGIBLE_WEIGHT]
        total = sum(w for _, w in heavy)
        mixed: dict[str, dict] = {}
        for c, w in heavy:
            for name, dist in self.inference.leave_one_out(c, seen).items():
                for value, p in dist.items():
                    mixed.setdefault(name, {})[value] = mixed.get(name, {}).get(value, 0.0) + w / total * p
        for name, value in seen.items():
            if name not in lead:
                continue  # last period's values are not judged (D19)
            for level in _judged_values(lead[name]):
                self.leader_calibration(domain).observe(lead[name][level], value == level)
                self.population_calibration(domain).observe(mixed[name][level], value == level)
                self.leader_calibration_vs_evidence(domain).observe(
                    lead[name][level], _evidence_for(evidence[name], level))

    def leader_calibration(self, domain: str) -> Calibration:
        return self._leader.setdefault(domain, Calibration())

    def population_calibration(self, domain: str) -> Calibration:
        return self._population.setdefault(domain, Calibration())

    def leader_calibration_vs_evidence(self, domain: str) -> Calibration:
        return self._leader_vs_evidence.setdefault(domain, Calibration())

    def report(self, domain: str) -> dict:
        return {"last_cycle": self._last.get(domain, {}),
                "leader_calibration": self.leader_calibration(domain).summary(),
                "population_calibration": self.population_calibration(domain).summary(),
                "leader_calibration_vs_evidence": self.leader_calibration_vs_evidence(domain).summary()}

    def state(self, domain: str) -> dict:
        return {"leader": self.leader_calibration(domain).state(),
                "population": self.population_calibration(domain).state(),
                "leader_vs_evidence": self.leader_calibration_vs_evidence(domain).state()}

    def adopt(self, domain: str, state: dict | None) -> None:
        state = state or {}
        self._leader[domain] = Calibration.from_state(state.get("leader"))
        self._population[domain] = Calibration.from_state(state.get("population"))
        self._leader_vs_evidence[domain] = Calibration.from_state(state.get("leader_vs_evidence"))

    def forget(self, domain: str) -> None:
        for d in (self._leader, self._population, self._leader_vs_evidence, self._last):
            d.pop(domain, None)


def _judged_values(dist: dict) -> list:
    """The values a forecast is judged on: True alone for a yes/no (False is
    its complement and would count the same forecast twice), every level of
    a graded signal (D25)."""
    return [True] if set(dist) == {True, False} else list(dist)


def _evidence_for(assignment, value) -> float:
    """The probability the evidence gave VALUE."""
    if assignment.probabilities:
        return assignment.probabilities.get(value, 0.0)
    return float(assignment.observed_value == value)
