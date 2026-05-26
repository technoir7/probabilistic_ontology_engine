# Probabilistic Ontology Engine

## What it is and why it exists

Most learning systems have an implicit assumption baked in at design time: *the structure of the domain is already known*. A neural network has a fixed architecture. A regression model has a fixed set of predictors. Even a Bayesian network in production typically has a fixed DAG chosen before training began. The learning happens inside that fixed shape; the shape itself is not questioned.

This engine is built around the opposite assumption: **we do not know the causal structure of the domain, and the structure can change**.

The question it is trying to answer is not "given this model, what are the parameters?" but rather "given this stream of evidence, which model — among all plausible models — best explains what we're seeing, and is that model still the right one?"

To answer that question it maintains a **population of competing structural hypotheses** about a domain, scores each one against incoming evidence, and treats the current best-scoring hypothesis as the operative model for inference. When evidence accumulates that is better explained by a different structure, a *paradigm shift* is detected — the dominant model changes — and the system adapts accordingly. Variants of surviving models are introduced continuously, so the system can discover structures that were not in the initial seed population.

This is not an incremental parameter update inside a fixed model. It is a competition between models, run continuously on a stream of evidence.

### What it encodes

Each competing model is a Directed Acyclic Graph (DAG) of Boolean or categorical variables, where edges represent conditional probabilistic dependencies. For each candidate graph, the engine maintains a full conditional probability table for every variable, learned from evidence. The CPTs encode *what* the world looks like given the structure; the population machinery asks *which structure we should believe*.

Edge existence is treated as a first-class uncertain quantity. Each edge has an existence probability that starts at a prior and is updated using the Bayesian Information Criterion as a likelihood ratio. Edges not supported by data are pruned; edges the data demands can be discovered through variant introduction.

The system is domain-agnostic. You define what the variables are, what the initial candidate structures look like, and what thresholds govern pruning. The engine handles the rest.

---

## Architecture

### Three levels of belief

```
Level 3 — Structure:    Which DAG best explains the data?
                        OntologyPopulation of OntologyCandidates
                        PopulationManager — score, prune, introduce variants
                        Paradigm shift detection

Level 2 — Edge:         Does this causal link exist?
                        Per-edge existence_probability ∈ [0, 1]
                        EdgeExistenceService — BIC log-likelihood ratio update
                        Prune edges that fall below threshold

Level 1 — Parameters:   Given the structure, what are the CPT values?
                        Per-variable Dirichlet count tables (ParameterStore)
                        LearningService — accumulate + EM for missing data
```

Evidence flows upward: raw records update CPTs (Level 1), CPT counts drive edge existence updates (Level 2), candidate log-likelihoods drive population pruning and variant introduction (Level 3). All three levels are updated every learning cycle.

### Services

| Service | Level | Responsibility |
|---|---|---|
| `LearningService` | 1 | Dirichlet CPT update from evidence batches. Fast forward-pass for fully-observed data; EM via pgmpy VariableElimination for partially-observed data. |
| `EdgeExistenceService` | 2 | BIC score with vs. without each edge; updates existence probability via logit-domain Bayesian update; decays explore_weight as edges resolve. |
| `PopulationManager` | 3 | Scores candidates (BIC-corrected average log-likelihood); prunes bottom quartile; introduces structural variants; tracks paradigm shifts. Novel component — no library analog. |
| `InferenceService` | — | Converts a candidate into a pgmpy DiscreteBayesianNetwork and answers marginal, conditional, and weighted-population queries via VariableElimination. |

### Candidate lifecycle

```
Initial seed population
    │
    ▼
Learning cycle (per batch):
  for each active candidate:
    accumulate(batch)           ← Level 1: update CPTs
    update_edge_existence()     ← Level 2: BIC ratio update
    prune_below_threshold()     ← Level 2: disable low-existence edges
    compute_log_likelihood()    ← score for this batch
    update_score()              ← accumulate into candidate.log_score
  prune_low_scorers()           ← Level 3: bottom quartile → PRUNED
  introduce_variants()          ← Level 3: add/remove one edge on top survivors
  end_cycle()                   ← update dominant, detect paradigm shift
```

New variants are warm-started: they inherit their parent's `log_score` and `evidence_count` so they enter the competition on even footing. The BIC complexity penalty counts all edges — including later-pruned ones — to prevent over-parameterized variants from winning by accident.

---

## Running locally

Requires Python 3.12+.

```bash
# From the epistemic-monitor-suite root
make dev
```

This starts the backend (port 8000) and the frontend dashboard (port 3000) together. Ctrl-C kills both.

To run the backend alone:

```bash
cd probabilistic-ontology-engine
source .venv/bin/activate
uvicorn src.engine.api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Environment variables

Copy `.env.example` to `.env` and fill in:

```bash
EIA_API_KEY=...       # api.eia.gov — free registration
```

NOAA data (api.weather.gov) and Yahoo Finance futures prices require no key.

---

## Domain modules

Two domains are currently implemented:

**Natural gas (NG)** — variables: `TempAnom`, `HeatingDem`, `StorageDraw`, `PriceUp`. Evidence from NOAA daily temperature observations and EIA weekly storage reports + Henry Hub spot price. Scheduler runs daily at 07:00 UTC.

**Corn (ZC)** — variables: `PlantingDelayed`, `DroughtIndex`, `YieldForecastDown`, `ExportDemandHigh`, `CornPriceUp`. Evidence from USDA NASS crop reports, USDA FAS export inspections, and Yahoo Finance `ZC=F` front-month futures. Scheduler runs daily at 08:00 UTC. NASS data is seasonal — off-season variables are marked `MISSING` rather than defaulting to false.

### Implementing a new domain

A domain module implements this interface:

```python
class MyDomain:
    def module_id(self) -> str:
        return "my-domain-v1"

    def initial_candidates(self) -> list[OntologyCandidate]:
        # Seed population — at least one candidate per structural hypothesis
        return [make_primary_candidate(), make_alternative_candidate()]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.3, 0.7),
        )
```

One critical requirement: define variables at module level, not inside the candidate constructor. Evidence records are matched to candidates by variable UUID. If `uuid4()` is called each time the constructor runs, evidence will not match candidates.

---

## Frontend

The dashboard (`epistemic-monitor`) visualizes the engine's live epistemological state: competing belief structures, edge existence probabilities, paradigm shift history, and the exploration frontier. It connects to the engine API at `NEXT_PUBLIC_API_BASE_URL` (defaults to `http://localhost:8000`).

See `epistemic-monitor/README.md` for frontend-specific setup.

---

## Project structure

```
epistemic-monitor-suite/
├── Makefile                          # make dev — starts both services
├── probabilistic-ontology-engine/    # this repo — Python backend
└── epistemic-monitor/                # Next.js frontend dashboard
```

Full codebase state, known limitations, and bugs fixed during development are documented in `SNAPSHOT.md`.
