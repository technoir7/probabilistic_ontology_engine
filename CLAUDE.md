# Probabilistic Ontology Engine

## Spec
Read `SPECM.md` in full before writing any code.
All architecture decisions are in SPECM.md. Do not deviate without flagging it.

## Stack
- Python 3.12
- FastAPI + Pydantic v2
- SQLite (MVP) — schema must be PostgreSQL-compatible
- NetworkX for graph operations per candidate
- pgmpy for Bayesian inference
- NumPy for edge existence updates
- pytest

## Build rules
- Do not proceed to the next build step until current step has passing tests
- PopulationManager has no library analog — implement directly from spec
- Do not use any library that abstracts population or structure search
- DAG constraint must be enforced on every candidate introduction
- All schema objects must be Pydantic v2 models
- SQLite and PostgreSQL share the same migration files

## Project structure
src/
  engine/
    schemas.py
    stores/
    services/
      population_manager.py      # novel — build from spec
      edge_existence.py
      learning.py
      inference.py
      explore_exploit.py
    api/
  domains/
    test_domain_v1/
    market_risk_v1/
tests/
  level1/
  level2/
  level3/
  integration/

## Critical tests
TEST-L3-03 (paradigm shift detection) is the milestone test.
The build is not complete until it passes.
