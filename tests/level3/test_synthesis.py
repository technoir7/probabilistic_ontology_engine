"""Hypotheses formed from the evidence (REFACTOR_SPEC D24): the connection a
structure lacks that would best have explained the evidence already seen,
proposed only when it explains more than chance would."""
from datetime import datetime
from uuid import uuid4

from src.domains.test_domain_v1.domain import _make_edge, _var_list, get_variables
from src.domains.test_domain_v1.synthetic_generator import SyntheticDataGenerator
from src.engine.schemas import EvidenceRecord, MissingnessType, ObservedAssignment, OntologyCandidate
from src.engine.services.synthesis import connections

ALL_PAIRS = {(a, b) for a in "ABCDE" for b in "ABCDE" if a != b}


def structure(*edges):
    return OntologyCandidate(candidate_id=uuid4(), domain_module_id="test-domain-v1",
                             variables=_var_list(), edges=[_make_edge(p, c) for p, c in edges])


def records(n, seed=0, graph="T*"):
    return SyntheticDataGenerator(graph=graph, random_seed=seed).sample(n)


def test_from_nothing_the_strongest_dependence_comes_first():
    # A -> C is the strongest single dependence in T* (0.8 vs 0.1 given B mixed in).
    found = connections(structure(), records(200), ALL_PAIRS)
    assert {found[0].parent, found[0].child} in ({"A", "C"}, {"C", "E"})
    assert found[0].gain > 0


def test_every_proposal_explains_more_than_chance():
    found = connections(structure(), records(200), ALL_PAIRS)
    assert found and all(f.gain > 0 for f in found)
    assert found == sorted(found, key=lambda f: -f.gain)


def test_independent_signals_prompt_nothing():
    v = get_variables()
    import random
    rng = random.Random(3)
    recs = [EvidenceRecord(timestamp=datetime(2024, 1, 1), observed_assignments=[
        ObservedAssignment(variable_id=v[n].variable_id, observed_value=rng.random() < 0.5) for n in "AB"])
        for _ in range(300)]
    assert connections(structure(), recs, {("A", "B"), ("B", "A")}) == []


def test_a_connection_already_made_is_not_proposed_again():
    found = connections(structure(("A", "C")), records(200), ALL_PAIRS)
    assert ("A", "C") not in {(f.parent, f.child) for f in found}


def test_no_proposal_closes_a_cycle():
    found = connections(structure(("A", "C"), ("C", "E")), records(200), ALL_PAIRS)
    pairs = {(f.parent, f.child) for f in found}
    assert ("C", "A") not in pairs and ("E", "A") not in pairs and ("E", "C") not in pairs


def test_only_admissible_connections_are_proposed():
    found = connections(structure(), records(200), {("B", "D")})
    assert [(f.parent, f.child) for f in found] == [("B", "D")]


def test_judged_against_what_the_child_already_depends_on():
    # Given A -> C and B -> C, E adds nothing about A once C is known.
    found = connections(structure(("A", "C"), ("B", "C"), ("B", "D"), ("C", "E"), ("D", "E")),
                        records(400), ALL_PAIRS)
    assert ("A", "E") not in {(f.parent, f.child) for f in found}


def test_missing_values_are_left_out_not_counted_as_false():
    v = get_variables()
    def rec(a, b):
        return EvidenceRecord(timestamp=datetime(2024, 1, 1), observed_assignments=[
            ObservedAssignment(variable_id=v["A"].variable_id, observed_value=a),
            ObservedAssignment(variable_id=v["B"].variable_id, observed_value=b,
                               missingness=MissingnessType.OBSERVED if b is not None else MissingnessType.MISSING)])
    # A and B agree whenever B is seen; when B is missing A is True.
    recs = [rec(x, x) for x in [True, False] * 60] + [rec(True, None)] * 120
    found = connections(structure(), recs, {("A", "B")})
    assert found and found[0].gain > 0
    # Read as False, the missing B would break the agreement and weaken it.
    as_false = [rec(x, x) for x in [True, False] * 60] + [rec(True, False)] * 120
    assert found[0].gain > connections(structure(), as_false, {("A", "B")})[0].gain


def test_a_connection_the_evidence_shows_backwards_is_offered_reversed():
    # T*: A -> C <- B, with A and B independent. Holding C -> A, the evidence
    # (A and B independent, dependent given C) favours A -> C once B -> C is held.
    found = connections(structure(("C", "A"), ("B", "C")), records(400), ALL_PAIRS)
    reversals = [f for f in found if f.reverses]
    assert reversals and (reversals[0].parent, reversals[0].child) == ("A", "C")


def test_a_reversal_never_closes_a_cycle():
    found = connections(structure(("A", "B"), ("B", "C"), ("A", "C")), records(200), ALL_PAIRS)
    assert ("C", "A") not in {(f.parent, f.child) for f in found if f.reverses}


def test_a_reversal_must_be_admissible():
    found = connections(structure(("C", "A")), records(200), {("C", "A")})
    assert not any(f.reverses for f in found)


def test_turning_round_a_connection_the_evidence_cannot_orient_is_not_offered():
    # Either way round, D - B and E - C here explain the same evidence; only
    # rounding error could prefer one.
    found = connections(structure(("C", "A"), ("E", "C"), ("D", "B")), records(100), ALL_PAIRS)
    assert not any(f.reverses for f in found)
