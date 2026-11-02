# Probabilistic Ontology Engine

Start with `SNAPSHOT.md`: what this project is, how it works, and what is open,
across this repo, the dashboard and the abductive engine.

## Spec
Read `SPEC.md` in full before writing any code.
All architecture decisions are in SPEC.md. Do not deviate without flagging it.

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
Layers import downward only; `uv run lint-imports` enforces it (contracts in
pyproject.toml). See REFACTOR_SPEC.md §5.
src/
  engine/
    model/          # schemas-level math: cpt, scoring, cadence, domain contract, errors;
                    # cases, trends, success (art's snapshots)
    schemas.py
    services/       # pure learning/inference: learning, edge_existence,
                    # population_manager (novel — build from spec), synthesis, programmes,
                    # inference, bn_model; cases (the case engine, art only, D29)
    stores/         # SQLite: database.py (one connection, transactions), migrations/*.sql
    engine.py       # the facade everything outside the core uses
    runtime/        # registry (the one list of domains), settings, ingestion, scheduler;
                    # cases, trends, success (computed once per process)
    api/            # app.py, routers/, dto, presenters, context, narrative;
                    # report (LLM reports, the checked life), life_words (the word rule),
                    # success_narrative, success_dto
  domains/
    sources/        # shared clients and helpers: fred, yfinance, gdelt, grades, soft_evidence, structure
    <domain>_v1/    # domain.py, source.py (open_source), ingestion/
                    # art also: case_data/, trend_data/, success_data/ (snapshots rebuilt
                    # locally from abductive_engine once a year)
    test_domain_v1/
tests/
  level1/
  level2/
  level3/
  integration/
  golden/           # behaviour snapshots; POE_UPDATE_GOLDEN=1 to regenerate

## Critical tests
TEST-L3-03 (paradigm shift detection) is the milestone test.
The build is not complete until it passes.
