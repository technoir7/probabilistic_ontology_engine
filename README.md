# Probabilistic Ontology Engine

## What it is and why it exists

Most learning systems have an implicit assumption baked in at design time: *the structure of the domain is already known*. A neural network has a fixed architecture. A regression model has a fixed set of predictors. Even a Bayesian network in production typically has a fixed DAG that was chosen before training began. The learning happens inside that fixed shape; the shape itself is not questioned.

This engine is built around the opposite assumption: **we do not know the causal structure of the domain, and the structure can change**.

The question it is trying to answer is not "given this model, what are the parameters?" but rather "given this stream of evidence, which model — among all plausible models — best explains what we're seeing, and is that model still the right one?"

To answer that question it maintains a **population of competing structural hypotheses** about a domain, scores each one against incoming evidence, and treats the current best-scoring hypothesis as the operative model for inference. When evidence accumulates that is better explained by a different structure, a *paradigm shift* is detected — the dominant model changes — and the system adapts accordingly. Variants of surviving models are introduced continuously, so the system can discover structures that were not in the initial seed population.

This is not an incremental parameter update inside a fixed model. It is a competition between models, run continuously on a stream of evidence.

### What it encodes

Each competing model is a **Directed Acyclic Graph (DAG)** of Boolean or categorical variables, where edges represent conditional probabilistic dependencies. Variables are the concepts in the domain; edges are the causal or statistical links between them. For each candidate graph, the engine maintains a full conditional probability table (CPT) for every variable, learned from evidence. The CPTs encode *what* the world looks like given the structure; the population machinery asks *which structure we should believe*.

Edge existence is treated as a first-class uncertain quantity. Each edge has an existence probability that starts at a prior and is updated using the Bayesian Information Criterion as a likelihood ratio. Edges that are not supported by data are pruned; edges that the data demands can be discovered through variant introduction.

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
| `LearningService` | 1 | Dirichlet CPT update from evidence batches. Two modes: fast forward-pass for fully-observed data; proper EM via pgmpy VariableElimination for partially-observed data. |
| `EdgeExistenceService` | 2 | Computes BIC score with vs. without each edge; updates existence probability via logit-domain Bayesian update; decays explore_weight as edges resolve. |
| `PopulationManager` | 3 | Scores candidates (BIC-corrected average log-likelihood); prunes bottom quartile; introduces structural variants (add or remove one edge); tracks paradigm shifts. Novel component — no library analog. |
| `InferenceService` | — | Converts a candidate into a pgmpy `DiscreteBayesianNetwork` and answers marginal, conditional, and weighted-population queries via VariableElimination. |

### Stores

| Store | Backend | Contents |
|---|---|---|
| `ParameterStore` | In-memory dict | `CPTData` per `(candidate_id, variable_name)` — count tables, alpha, parent list |
| `EvidenceStore` | SQLite (WAL mode) | Append-only log of `EvidenceRecord` objects, domain-isolated |
| `PopulationStore` | SQLite (WAL mode) | `OntologyPopulation` metadata, candidate scores, score history, pruning records |

The SQLite schema is written to be PostgreSQL-compatible; TEXT is used where PostgreSQL would use JSONB.

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

New variants are warm-started: they inherit their parent's `log_score` and `evidence_count` so they enter the competition on even footing. The BIC complexity penalty (which counts all edges, including later-pruned ones) prevents over-parameterized variants from winning by accident.

### Scoring formula

Candidate ranking uses BIC-corrected average log-likelihood:

```
avg_BIC(c) = log_score(c) / N  −  (0.5 × k × ln N) / N

where:
  N = evidence_count
  k = Σ_{variables v} 2^(num_parents of v, counting ALL edges including disabled)
```

Counting all edges — including pruned ones — in `k` prevents a variant from gaming the score by adding a spurious edge, observing that evidence prunes it, and then inheriting the parent's accumulated score while avoiding the complexity penalty.

---

## Installation

Requires Python 3.12+.

```bash
# Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

Dependencies: `pydantic>=2.0`, `fastapi>=0.100`, `networkx>=3.0`, `pgmpy>=0.1.20`, `numpy>=1.24`, `scipy>=1.10`, `uvicorn>=0.22`, `httpx>=0.24`, `pytest>=7.0`.

---

## Running the tests

```bash
# All tests (15 total, L1–L3)
pytest tests/

# By level
pytest tests/level1/   # CPT parameter learning (4 tests)
pytest tests/level2/   # Edge existence (5 tests)
pytest tests/level3/   # Population management (6 tests), includes TEST-L3-03 milestone

# Verbose output
pytest tests/ -v

# All tests pass regardless of PYTHONHASHSEED
PYTHONHASHSEED=0 pytest tests/
```

Expected output: `15 passed`. Tests cover:
- **L1-01** Single-variable posterior convergence within 0.08 of ground truth
- **L1-02** Full CPT convergence (all entries within 0.10) under ground truth graph
- **L1-03** Bitwise reproducibility: same evidence + same seed → same parameter hash
- **L1-04** EM convergence with 30% missing data, within 0.12 of ground truth
- **L2-01** True edge existence rises above 0.85 after 300 records
- **L2-02** Spurious edge existence falls below 0.15 after 300 records
- **L2-03** Monotone trend: true edges trend up, spurious edges trend down
- **L2-04** Spurious edge disabled when existence_probability < prune_below threshold
- **L2-05** explore_weight decays below 0.5 once an edge resolves
- **L3-01** True structure (T*) is dominant after 500 records from T*
- **L3-02** Null candidate is pruned (marked PRUNED) within 500 records
- **L3-03** ⭐ **MILESTONE** — Paradigm shift: T* dominates on T* data; switch to T_alt regime → T_alt rises to dominance, paradigm_shift_count increments
- **L3-04** All introduced variants are valid DAGs (no cycles)
- **L3-05** Active population size never exceeds max_population_size
- **L3-06** Variant lineage tracking: generation and parent_candidate_id are correct

---

## Implementing a domain module

A domain module is a class that implements the following interface. Register it with the engine and all learning, inference, and population management is handled automatically.

```python
class MyDomain:
    def module_id(self) -> str:
        """Unique string identifier for this domain."""
        return "my-domain-v1"

    def version(self) -> str:
        return "1.0.0"

    def initial_candidates(self) -> list[OntologyCandidate]:
        """
        The seed population. At least one candidate with the structure you
        believe is most plausible. Include structural alternatives if you have
        prior reason to believe they may emerge.

        Variables must share canonical UUIDs — define them once at module level,
        not inside the function, or evidence records will not match candidates.
        """
        return [make_my_best_guess_candidate(), make_alternative_candidate()]

    def existence_thresholds(self) -> EdgeExistenceThresholdConfig:
        """
        prune_below: existence_probability below this → edge is disabled
        accept_above: existence_probability above this → explore_weight starts decaying
        explore_band: (lo, hi) — edges inside this band are considered uncertain
        """
        return EdgeExistenceThresholdConfig(
            prune_below=0.05,
            accept_above=0.90,
            explore_band=(0.3, 0.7),
        )
```

### Critical: canonical variable UUIDs

Evidence records are matched to candidate variables by UUID. If you create new `Variable` objects inside the candidate constructor (each call to `uuid4()` produces a different UUID), evidence ingested before candidate creation will not match. Define variables at module level:

```python
# module_level_variables.py — created ONCE at import time
_VARIABLES: dict[str, Variable] = {
    name: Variable(variable_id=uuid4(), name=name,
                   domain_type=DomainType.BOOLEAN, support=[True, False])
    for name in ["price", "volume", "volatility", "spread"]
}

def get_variables() -> dict[str, Variable]:
    return _VARIABLES  # same objects every call
```

The `SyntheticDataGenerator` in `test_domain_v1` shows the correct pattern: it calls `get_variables()` to obtain the shared canonical objects, so every generated `EvidenceRecord` references the same UUIDs that the candidates carry.

### Engine usage

```python
engine = ProbabilisticOntologyEngine(db_path="my_domain.db", random_seed=42)
engine.register_domain(MyDomain())
engine.activate_domain("my-domain-v1")

# Ingest evidence
engine.ingest_batch(evidence_records)

# Run one learning cycle
snapshot = engine.learn(batch=evidence_records)

# Query the dominant model
query = InferenceQuery(
    domain_module_id="my-domain-v1",
    target_variables=["volatility"],
    conditioned_on=[ObservedAssignment(variable_id=price_var_id, observed_value=True)],
    query_type=QueryType.MARGINAL,
)
result = engine.query(query)
# result["posteriors"]["volatility"] → {"True": 0.73, "False": 0.27}

# Check population status
status = engine.population_status()
# status["paradigm_shift_count"] → number of dominant-model changes
```

---

## Test domain: T* and T_alt

The reference domain (`test_domain_v1`) has five Boolean variables (A, B, C, D, E) and two generating graphs:

```
T*:     A → C   B → C   B → D   C → E   D → E
T_alt:  A → C   B → C   A → D   C → E   D → E
                                 ↑ differs: A→D instead of B→D
```

The TEST-L3-03 milestone test runs 300 records of T* data (T* should dominate), then switches the generator to T_alt and runs 300 more records (T_alt should rise, paradigm_shift_count should increment). This validates the core hypothesis of the system: that structure-level adaptation tracks regime changes in the data.
# probabilistic_ontology_engine
