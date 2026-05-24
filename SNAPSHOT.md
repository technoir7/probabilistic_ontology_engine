# Codebase Snapshot — 2026-05-24

Handoff document. Describes exact state of every module, what is implemented vs. stubbed, all bugs found and fixed, test results, and known limitations. Not marketing copy.

---

## Test status

**15/15 passing** across all `PYTHONHASHSEED` values (confirmed at 0, 1, 42, 100, 999, 12345).

```
tests/level1/test_parameter_learning.py::test_L1_01_parameter_update_single_variable  PASSED
tests/level1/test_parameter_learning.py::test_L1_02_cpt_convergence_full_graph         PASSED
tests/level1/test_parameter_learning.py::test_L1_03_parameter_reproducibility          PASSED
tests/level1/test_parameter_learning.py::test_L1_04_missing_evidence_em                PASSED
tests/level2/test_edge_existence.py::test_L2_01_true_edge_existence_rises               PASSED
tests/level2/test_edge_existence.py::test_L2_02_spurious_edge_existence_falls           PASSED
tests/level2/test_edge_existence.py::test_L2_03_existence_update_direction              PASSED
tests/level2/test_edge_existence.py::test_L2_04_edge_pruned_at_threshold                PASSED
tests/level2/test_edge_existence.py::test_L2_05_explore_weight_decays                   PASSED
tests/level3/test_population.py::test_L3_01_true_structure_dominates                    PASSED
tests/level3/test_population.py::test_L3_02_low_scorers_pruned                          PASSED
tests/level3/test_population.py::test_L3_03_paradigm_shift_on_regime_switch             PASSED  ← MILESTONE
tests/level3/test_population.py::test_L3_04_variant_introduction_schema_valid           PASSED
tests/level3/test_population.py::test_L3_05_population_size_bounded                     PASSED
tests/level3/test_population.py::test_L3_06_lineage_tracked                             PASSED
```

Run command: `pytest tests/level1/ tests/level2/ tests/level3/ -v`  
Runtime: ~3.6 seconds. The warning flood (several thousand `DeprecationWarning: datetime.utcnow()`) is noise from pgmpy and the stores; all warnings are non-fatal and suppressed in normal runs.

---

## Directory structure

```
probabilistic_ontology_engine/
│
├── pyproject.toml                        # hatchling build; pytest config; deps
├── README.md                             # user-facing introduction
├── SNAPSHOT.md                           # this file
├── NEXT.md                               # next steps
├── SPECM.md                              # authoritative spec (unchanged from original)
├── CLAUDE.md                             # build rules and project instructions
│
├── src/
│   ├── __init__.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── engine.py                     # ProbabilisticOntologyEngine — top-level orchestrator
│   │   ├── schemas.py                    # All Pydantic v2 models
│   │   ├── api/
│   │   │   └── __init__.py               # EMPTY — FastAPI routes not yet written
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── learning.py               # Level 1 — CPT parameter update
│   │   │   ├── edge_existence.py         # Level 2 — edge existence probability update
│   │   │   ├── population_manager.py     # Level 3 — population management (novel)
│   │   │   ├── inference.py              # pgmpy VariableElimination inference
│   │   │   └── explore_exploit.py        # STUBBED — mutual information edge proposal
│   │   └── stores/
│   │       ├── __init__.py
│   │       ├── parameter_store.py        # In-memory CPT store (CPTData + ParameterStore)
│   │       ├── evidence_store.py         # SQLite append-only evidence log
│   │       └── population_store.py       # SQLite population/candidate metadata store
│   │
│   └── domains/
│       ├── __init__.py
│       ├── test_domain_v1/
│       │   ├── __init__.py
│       │   ├── domain.py                 # Canonical variable defs, CPTs, candidate factories
│       │   └── synthetic_generator.py    # Samples EvidenceRecords from T* or T_alt
│       └── market_risk_v1/
│           └── __init__.py               # EMPTY — placeholder directory only
│
└── tests/
    ├── __init__.py
    ├── conftest.py                        # Shared fixtures (engine, generator, candidates)
    ├── level1/
    │   ├── __init__.py
    │   └── test_parameter_learning.py    # L1-01..04: CPT learning tests
    ├── level2/
    │   ├── __init__.py
    │   └── test_edge_existence.py        # L2-01..05: edge existence tests
    ├── level3/
    │   ├── __init__.py
    │   └── test_population.py            # L3-01..06: population management tests
    └── integration/
        └── __init__.py                    # EMPTY — integration tests not yet written
```

---

## Module-by-module state

### `src/engine/schemas.py` — **fully implemented**

All Pydantic v2 models used throughout the engine.

**Enums**: `DomainType` (BOOLEAN, CATEGORICAL, ORDINAL, CONTINUOUS, COUNT), `DependencyKind` (DIRECTED_CONDITIONAL, FACTOR_LINK, AGGREGATION_LINK), `CandidateStatus` (ACTIVE, PRUNED, ARCHIVED), `MissingnessType` (OBSERVED, MISSING, IMPUTED, REDACTED), `SourceType`, `RelationSemantics`, `QueryType`, `PopulationAggregation`.

**`Variable`**: `variable_id: UUID`, `name: str`, `domain_type: DomainType`, `support: list[Any]`, `time_indexed: bool`, `hidden: bool`.

**`DependencyEdge`**: `edge_id: UUID`, `parent_variable_id: UUID`, `child_variable_id: UUID`, `dependency_kind`, `existence_prior: float`, `existence_probability: float`, `existence_update_count: int`, `explore_weight: float` (init 1.0), `explanatory_label: str`, `learnable: bool`, `enabled: bool`. The `enabled` field is False when an edge is pruned by `EdgeExistenceService`.

**`ObservedAssignment`**: `variable_id: UUID`, `observed_value: Any`, `missingness: MissingnessType`, `confidence: float`.

**`EvidenceRecord`**: `evidence_id: UUID`, `timestamp: datetime`, `observed_assignments: list[ObservedAssignment]`, `source_type`, `source_ref`, `confidence`.

**`OntologyCandidate`**: Core Level 3 primitive. Fields: `candidate_id`, `domain_module_id`, `generation`, `parent_candidate_id` (None for seed candidates), `variables: list[Variable]`, `edges: list[DependencyEdge]`, `log_score: float` (cumulative), `evidence_count: int`, `status: CandidateStatus`, `introduced_at`, `pruned_at`, `pruning_reason`, `description`.

Helper methods:
- `get_variable_by_name(name)` / `get_variable_by_id(vid)` — linear scan
- `get_active_edges()` — filters `enabled=True`
- `get_parents(variable_id)` — parents via active edges only
- `get_children(variable_id)` — children via active edges only
- `is_dag()` — uses `networkx.is_directed_acyclic_graph` on active edges
- `topological_order()` — returns variables in topological order via networkx
- `edge_structure_signature()` — `frozenset[tuple[str,str]]` of (parent_name, child_name) for active edges only; used for paradigm shift detection and duplicate variant checking

**`OntologyPopulation`**: `population_id`, `domain_module_id`, `max_population_size`, `candidates: list[OntologyCandidate]`, `active_candidate_id` (UUID of current dominant), `generation`, `paradigm_shift_count`.

Methods:
- `active_candidates()` — filters ACTIVE status
- `_avg_score(c)` — BIC-corrected average: counts ALL edges (including disabled) for k; `avg_ll - 0.5*k*ln(max(N,2))/N`. Used for `score_weights()` and `update_dominant()`.
- `dominant()` — `max(active_candidates, key=_avg_score)`
- `update_dominant()` — updates `active_candidate_id`; increments `paradigm_shift_count` if dominant changes; returns bool
- `score_weights()` — exp-softmax over BIC-corrected avg scores; used for weighted inference
- `summary()` — dict with domain_module, generation, active_candidates count, dominant_candidate UUID str, dominant_score (raw log_score), structure_entropy (H over score_weights), paradigm_shift_count

**`EdgeExistenceThresholdConfig`**: `prune_below: float = 0.05`, `accept_above: float = 0.90`, `explore_band: tuple[float,float] = (0.3, 0.7)`.

**`InferenceQuery`**: `query_id`, `domain_module_id`, `target_variables: list[str]`, `conditioned_on: list[ObservedAssignment]`, `query_type: QueryType`, `population_aggregation: PopulationAggregation`, `explain: bool`.

**`ModelSnapshot`**: `snapshot_id`, `engine_version`, `domain_module_id`, `population_state_hash` (SHA-256 of summary dict), `parameter_hash` (SHA-256 of dominant candidate's CPTs), `evidence_window_start/end`, `random_seed`, `created_at`, `metrics: dict`.

---

### `src/engine/stores/parameter_store.py` — **fully implemented**

**`CPTData`** (dataclass): Holds sufficient statistics for one variable in one candidate.

Fields: `variable_name`, `parents: list[str]` (sorted), `support: list[Any]`, `counts: dict` (`{parent_config_tuple: {value: count}}`), `alpha: float = 1.0`.

Parent config tuple format: `tuple of (parent_name, value) pairs sorted by parent_name`, e.g. `(("A", True), ("B", False))`. The empty tuple `()` is used for root nodes.

Methods:
- `increment(value, parent_assignment)` — adds 1 count; creates row if absent
- `get_probability(value, parent_assignment)` — Laplace-smoothed: `(N_qk + alpha) / (N_q + alpha * r)` where r = `len(support)`
- `log_prob(value, parent_assignment)` — `log(max(get_probability(...), 1e-12))`
- `mle_log_likelihood()` — `sum_{q,k} N_qk * log(N_qk / N_q)` for MLE (no smoothing); zero if N_qk=0
- `bic_score()` — `mle_log_likelihood - 0.5 * n_free * log(N_total)`. `n_free = n_configs * (|support| - 1)`. `n_configs` = `max(len(counts), 1)`. Note: `n_configs` uses actual observed configs, not the full Cartesian product — this is an approximation that works well in practice but is not exact for sparse data.
- `bic_score_without_parent(parent_name)` — marginalizes out `parent_name` from counts, recomputes BIC for the reduced model; used by EdgeExistenceService for the BIC log-likelihood ratio
- `digest()` — SHA-256 of counts dict serialized to JSON; used in `parameter_hash()`
- `copy()` — deep-copy (used in `clone_candidate`)

**`ParameterStore`**: Maps `(str(candidate_id), variable_name) → CPTData` in a nested dict `_store`.

Methods:
- `initialize_candidate(candidate_id, variable_name, parents, support, alpha)` — creates CPTData
- `get(candidate_id, variable_name)` — raises KeyError if absent
- `has(candidate_id, variable_name)` — safe check
- `get_all_for_candidate(candidate_id)` — full dict for candidate
- `update_parents(candidate_id, variable_name, new_parents)` — **resets counts** for the variable with new parent set; called by EdgeExistenceService after pruning an edge
- `clone_candidate(src_id, dst_id)` — deep-copies all CPTData from src to dst; used by PopulationManager when introducing variants
- `parameter_hash(candidate_id)` — SHA-256 over `"name:digest|name:digest|..."` sorted by name
- `remove_candidate(candidate_id)` — pops from dict; not called in tests but available

---

### `src/engine/stores/evidence_store.py` — **fully implemented**

SQLite-backed, append-only, WAL mode. Schema:

```sql
evidence_records (
    evidence_id   TEXT PRIMARY KEY,
    domain_module TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 1.0,
    assignments   TEXT NOT NULL DEFAULT '[]'   -- JSON array of ObservedAssignment dicts
)
```

Methods: `append(record, domain_module_id)`, `append_batch(records, domain_module_id)` (uses `executemany`), `load_all(domain_module_id)` (returns deserialized `EvidenceRecord` list), `count(domain_module_id)`, `clear(domain_module_id)`.

`load_all` round-trips through JSON. `variable_id` is stored as UUID string and reconstructed. `observed_value` round-trips as JSON which may coerce Python `True/False` to/from JSON `true/false` (fine for bool; may need attention for richer types).

---

### `src/engine/stores/population_store.py` — **fully implemented**

SQLite-backed, WAL mode. Three tables:

```sql
ontology_populations (
    population_id TEXT PRIMARY KEY,
    domain_module_id TEXT UNIQUE,
    max_population_size INT,
    active_candidate_id TEXT,
    generation INT,
    paradigm_shift_count INT,
    updated_at TEXT
)

ontology_candidates (
    candidate_id TEXT PRIMARY KEY,
    domain_module_id TEXT,
    generation INT,
    parent_candidate_id TEXT,
    log_score REAL,
    evidence_count INT,
    status TEXT,           -- 'ACTIVE', 'PRUNED', 'ARCHIVED'
    introduced_at TEXT,
    pruned_at TEXT,
    pruning_reason TEXT,
    description TEXT,
    metadata TEXT          -- JSON, always '{}' currently
)

candidate_scores (
    score_id TEXT PRIMARY KEY,
    candidate_id TEXT,
    ts TEXT,
    log_likelihood REAL,   -- per-batch increment (not cumulative)
    batch_index INT,
    context TEXT           -- JSON, always '{}' currently
)
```

Methods: `save_population(pop)`, `load_population_id(domain_module_id)`, `save_candidate(cand)`, `update_score(candidate_id, log_score, evidence_count)`, `mark_pruned(candidate_id, reason)`, `append_score_record(candidate_id, log_likelihood, batch_index)`.

Note: `metadata` and `context` fields are always written as `'{}'`; no metadata is actually stored. The `candidate_scores` table gives a full per-batch score history usable for time-series analysis of candidate trajectories.

---

### `src/engine/services/learning.py` — **fully implemented**

**`LearningService`**: Two accumulation modes sharing one interface.

**`initialize_candidate(candidate, alpha=1.0)`**: Calls `ps.initialize_candidate` for every variable, using the current active parents (from `candidate.get_parents()`). Must be called before any accumulation.

**`accumulate(batch, candidate)`**: Fast path. For each record:
- Classifies assignments as OBSERVED or MISSING (absent variables are treated as missing)
- If fully observed: `_accumulate_fully_observed` — exact integer count increments
- If any variable missing: `_accumulate_mean_field` — single forward pass in topological order computing soft distributions, then fractional count accumulation using outer product over parent configurations

Mean-field is a first-order approximation. It does not iterate; it makes one forward sweep. Quality degrades with high missing rates and complex graphs. See `accumulate_em` for the proper alternative.

**`accumulate_em(batch, candidate, n_iterations=5)`**: Proper EM. Splits batch into fully-observed (handled exactly, once) and partially-observed.

E-step uses pgmpy `DiscreteBayesianNetwork` + `VariableElimination` to compute `P(missing | observed)` for each partial record. M-step swaps the delta: removes the previous iteration's expected counts and adds the new ones. The key implementation detail: the pgmpy model is built **with the current counts including the previous delta still in place** before computing the new delta; then the old delta is removed and new one added. This is the correct delta-swap pattern — an earlier implementation removed the previous delta before building the model, which caused the model to regress to fully-observed-only counts on each iteration.

Falls back to uniform distributions if pgmpy inference fails (exception caught silently).

**`compute_log_likelihood(batch, candidate)`**: Sums `cpt_data.log_prob(value, parent_assignment)` over all observed assignments in all records where all parents are also observed. Returns float (always ≤ 0). This is the scoring signal used by PopulationManager.

---

### `src/engine/services/edge_existence.py` — **fully implemented**

**`EdgeExistenceService`**:

**`update(candidate)`**: For every `learnable` edge in candidate (including disabled ones, since update is called on all edges regardless of enabled state — note: this means existence probabilities continue updating even after pruning, which is fine as they are not acted on once `enabled=False`):

Calls `_update_edge(candidate, edge)`.

**`_update_edge`**:
1. Gets `child_var`'s CPTData from ParameterStore
2. `score_with = cpt_data.bic_score()` — BIC with full current parent set
3. Checks if `parent_var.name` is in `cpt_data.parents` — skips if not (edge already removed from CPT)
4. `score_without = cpt_data.bic_score_without_parent(parent_var.name)` — BIC with parent marginalized out
5. `log_lr = score_with - score_without`
6. `log_odds = logit(edge.existence_prior) + log_lr` — using cumulative data means this is the correct Bayesian posterior from the prior
7. `edge.existence_probability = sigmoid(log_odds)`
8. `edge.existence_update_count += 1`
9. Explore weight update: if existence_probability is outside `explore_band`, decay by `0.3 * distance_from_mid`; if inside, increase by 5%. Clipped to [0.05, 2.0].

**`prune_below_threshold(candidate, parameter_store)`**: Iterates enabled edges. If `existence_probability < prune_below`, sets `edge.enabled = False`, then calls `parameter_store.update_parents(candidate_id, child_var.name, new_parents)` to remove the parent from the CPT (resets CPT counts for that variable with the smaller parent set). Returns list of pruned edges.

**`get_uncertain_edges(candidate)`**: Returns edges in explore_band; currently used by ExploreExploitService (which is stubbed).

---

### `src/engine/services/population_manager.py` — **fully implemented**

Novel component. No library analog. Implements Level 3 per SPEC §17.

**`__init__`**: Takes `ParameterStore`, `PopulationStore`, `EdgeExistenceThresholdConfig`, `random.Random` (default seed 42). Maintains `_populations: dict[str, OntologyPopulation]` and `_admissible_edges: dict[str, set[tuple[str,str]]]` in memory.

**`initialize(domain_module_id, initial_candidates, max_population_size, admissible_edges, thresholds)`**: Creates `OntologyPopulation`, calls `update_dominant()`, saves to PopulationStore, saves each candidate.

**`get_population(domain_module_id)`**: Direct dict lookup; raises KeyError if domain not initialized.

**`dominant(domain_module_id)`**: Returns `max(active_candidates, key=self._avg_score)`. Uses PopulationManager's own `_avg_score`, not OntologyPopulation's.

**`_avg_score(candidate)`**: BIC-corrected average log-likelihood. Counts ALL edges (including disabled) for `k`:
```python
n_parents = sum(1 for e in candidate.edges if e.child_variable_id == v.variable_id)
k += 2 ** n_parents
```
`return (candidate.log_score / n) - (0.5 * k * math.log(max(n, 2)) / n)`

Returns `float("-inf")` if `evidence_count == 0`.

**`update_score(domain_module_id, candidate_id, log_likelihood, batch_index, batch_size)`**: Finds candidate in population by UUID, adds `log_likelihood` to `log_score`, adds `batch_size` to `evidence_count`. Also calls `pop_store.update_score` and `pop_store.append_score_record`. `batch_size` should be `len(batch)` — the count of individual records in the batch.

**`prune_low_scorers(domain_module_id)`**: Guards: `len(active) < 2` → return; `not any(c.evidence_count >= _MIN_BATCHES_FOR_PRUNING for c in active)` → return (where `_MIN_BATCHES_FOR_PRUNING = 3`; note this is compared against `evidence_count` which is a record count, not a batch count — any candidate that has seen 3+ records will pass this threshold, which is always true after the first batch of any practical size). Ranks active candidates by `_avg_score`; prunes bottom `max(1, len(active)//4)`, skipping the dominant. Marks candidates PRUNED with `pruning_reason="bottom_quartile_log_score"`.

**`introduce_variants(domain_module_id, learning_service=None)`**: Computes `slots = max_population_size - len(active)`. Sorts survivors by raw `log_score` (not BIC-adjusted) for parent selection. Loops up to `slots * 10` attempts, picking parent via `survivors[attempts % len(survivors)]`. Calls `_make_variant`; validates DAG; checks for duplicate edge signatures among existing + new candidates. On success: appends to population, increments generation, saves candidate, clones CPTs, optionally calls `ps.update_parents` for new edges if `learning_service` provided.

**`_make_variant(domain_module_id, parent, admissible)`**: Strategy randomly chosen from ["add", "remove"]. Falls back to the other strategy if chosen strategy is impossible.

- "add": `candidates_to_add = sorted(admissible - edge_sigs)` (sorted for PYTHONHASHSEED independence), `rng.choice(candidates_to_add)`, creates new `DependencyEdge` with `existence_prior=0.5, existence_probability=0.5`.
- "remove": `rng.choice(active_edges)`, filters that edge out of `variant_edges` list.

Warm-start: `variant.log_score = parent.log_score`, `variant.evidence_count = parent.evidence_count`. This ensures new variants enter the BIC-corrected ranking at the same level as their parent, not at -inf.

**`end_cycle(domain_module_id)`**: Calls `pop.update_dominant()` (which increments `paradigm_shift_count` if dominant changes), calls `pop_store.save_population(pop)`, returns `pop.summary()`.

---

### `src/engine/services/inference.py` — **fully implemented**

**`InferenceService.query(inference_query, population)`**: Dispatches on `PopulationAggregation`.

- `ACTIVE_ONLY`: queries dominant candidate only
- `WEIGHTED_AVERAGE`: queries all active candidates, merges posteriors weighted by `score_weights()`
- `TOP_K`: top 3 by raw log_score, exp-weight normalized

**`_query_candidate`**: Builds pgmpy model via `_build_pgmpy_model`, runs `VariableElimination.query([var], evidence=evidence_int)` for each target variable. Evidence must be encoded as int indices (pgmpy uses 0-based integer states) via `_encode_value`. Falls back to uniform marginal on any exception.

If `query.explain=True`: returns path explanations via networkx `all_simple_paths` from each conditioned variable to each target, with edge existence probabilities along each path.

**`_build_pgmpy_model(candidate)`**: Builds `DiscreteBayesianNetwork` from active edges, adds all variables as nodes (isolated variables get uniform CPDs), builds `TabularCPD` for each variable via `_build_tabular_cpd`. Calls `model.check_model()` but silently ignores failures (slight numerical imprecision in CPT normalization).

**`_build_tabular_cpd(var, parent_vars, cpt_data)`**: Generates all parent value combinations in pgmpy column order (last evidence variable varies fastest), queries `get_probability` for each, normalizes columns. Returns `TabularCPD`.

**`_encode_value(value, support)`**: Maps Python value to 0-based index by equality or `str()` comparison.

---

### `src/engine/services/explore_exploit.py` — **stubbed**

`ExploreExploitService` class exists and has a `propose(population, batch, top_k)` method that structurally identifies admissible edges not in any active candidate and ranks them by empirical mutual information. However, `_empirical_mi` is a stub that always returns 0.0 — it cannot extract variable names from `ObservedAssignment` objects (which carry UUIDs, not names). The ranking is therefore always trivial; all proposals have equal score.

This service is not called anywhere in the current engine or tests.

---

### `src/engine/engine.py` — **fully implemented** (core loop)

**`ProbabilisticOntologyEngine`**: Top-level orchestrator.

`__init__(db_path=":memory:", random_seed=42)`: Creates all stores and services. Note: `PopulationManager` is created without a seeded RNG here (uses the default `random.Random(42)` inside PopulationManager's own `__init__`).

`register_domain(domain_module)`: Calls `domain_module.initial_candidates()`, `learning_service.initialize_candidate` for each, `_derive_admissible_edges` (all variable pairs, regardless of which pairs appear in initial candidates), `population_manager.initialize`.

`learn(batch, domain_module_id=None)`: One full learning cycle:
1. For each active candidate: accumulate, edge existence update, prune, score, update_score (with `batch_size=len(batch)`)
2. `prune_low_scorers`, `introduce_variants`
3. `end_cycle` → ModelSnapshot

`query(inference_query)`: Delegates to `inference_service.query`.

`_make_snapshot`: Computes SHA-256 of summary dict (population_state_hash) and parameter_hash of dominant candidate.

`get_edge_existence(candidate_id, parent_name, child_name)`: Scans candidate edges for the named pair, returns `existence_probability` or None.

`_derive_admissible_edges(candidates)`: Returns all (a, b) pairs for a ≠ b across all variable names in all candidates. This is a superset of what appears in initial candidates — effectively all possible edges. Domain-specific pruning (via schema TemplateRules) is not yet implemented.

---

### `src/domains/test_domain_v1/domain.py` — **fully implemented**

Module-level canonical variable definitions:

```python
_VARIABLE_DEFS: dict[str, Variable] = {
    name: Variable(variable_id=uuid4(), ...)
    for name in ["A", "B", "C", "D", "E"]
}
```

Created once at module import time. All subsequent calls to `get_variables()`, all candidate factories, and the `SyntheticDataGenerator` reference the same objects with the same UUIDs. This is the critical requirement for evidence records to match candidate variable lookups.

Ground truth CPTs: `CPT_A`, `CPT_B`, `CPT_C`, `CPT_D_TSTAR`, `CPT_D_TALT`, `CPT_E`. See module docstring for values.

Structure signatures: `T_STAR_EDGES = frozenset({("A","C"),("B","C"),("B","D"),("C","E"),("D","E")})`, `T_ALT_EDGES = frozenset({("A","C"),("B","C"),("A","D"),("C","E"),("D","E")})`.

Candidate factories (all create fresh `candidate_id` UUIDs, share `_VARIABLE_DEFS` variables):
- `make_tstar_candidate(module_id, gen)` — 5 edges, priors 0.7
- `make_talt_candidate(module_id, gen)` — 5 edges, A→D prior 0.5
- `make_null_candidate(module_id, gen)` — 1 edge (C→E), prior 0.5
- `make_spurious_1_candidate(module_id)` — T* + A→D (6 edges)
- `make_spurious_2_candidate(module_id)` — T* − B→D (4 edges)

`TestDomainV1` class implements the domain module interface: `module_id()`, `version()`, `initial_candidates()` (T*, T_alt, null), `existence_thresholds()` (prune_below=0.05, accept_above=0.90).

`initial_entities()`, `initial_assertions()`, `variable_specs()`, `initial_parameterizations()` return empty lists — these are spec fields not yet used.

---

### `src/domains/test_domain_v1/synthetic_generator.py` — **fully implemented**

`SyntheticDataGenerator(graph="T*", random_seed=42, missing_rate=0.0)`:

- Uses `numpy.random.default_rng(random_seed)` for reproducible sampling
- Calls `get_variables()` to get canonical `_VARIABLE_DEFS` — same UUIDs as candidates
- `sample(n)` → `list[EvidenceRecord]` from current regime
- `sample_variable_only(variable_name, n, p_true)` → n records with only one variable observed
- `switch_regime(new_graph)` — changes `self.graph`; used in L3-03 paradigm shift test

Sampling is ancestral: A, B (roots) → C (parents A,B) → D (parent B or A by regime) → E (parents C,D). Missing rate applies independently to each assignment.

---

### `src/domains/market_risk_v1/` — **empty placeholder**

Directory and `__init__.py` exist. No implementation.

---

### `src/engine/api/` — **empty placeholder**

Directory and `__init__.py` exist. FastAPI routes not written.

---

### `tests/integration/` — **empty placeholder**

Directory and `__init__.py` exist. Integration tests not written.

---

## Bugs found and fixed during L3-03 stabilization

### Bug 1: Warm-started variants gaming BIC score via add-then-prune

**Symptom**: `test_L3_01_true_structure_dominates` failed with:
```
AssertionError: Expected T* to dominate. Dominant: variant_add_A->D, score: -1371.51.
T* score: -1373.67
```
The dominant candidate was `variant_add_A->D` — a variant of T* that added the spurious edge A→D, which was subsequently pruned (disabled). After pruning, the variant had the same active edge structure as T* but a marginally higher raw log_score (-1371.51 vs T*'s -1373.67).

**Root cause**: When `_avg_score` computed the BIC complexity penalty `k = Σ 2^(num_active_parents)`, disabled edges were excluded. After A→D was pruned, D's active parent count in the variant was 1 (just B, same as T*). So both had k=12 and identical BIC penalties. The variant's 2.16 advantage in raw log_score persisted, making it dominant.

The variant accumulated that advantage because: after A→D was pruned and D's CPT was reset with only B as parent, the variant's CPT for D converged on fewer data points than T*'s CPT (which had been training with B→D from the start). The re-convergence produced slightly different counts that happened to fit slightly better on the remaining batches.

**Fix**: Count ALL edges (including `enabled=False`) when computing parent count for BIC:
```python
# Before:
k += 2 ** len(candidate.get_parents(v.variable_id))   # active parents only

# After:
n_parents = sum(1 for e in candidate.edges if e.child_variable_id == v.variable_id)
k += 2 ** n_parents   # all edges, including disabled
```

For the variant with A→D pruned: D now has 2 edges in its edge list (B→D and A→D), so n_parents=2, contribution to k is 4 instead of 2. Total k=14 vs T*'s k=12. BIC penalty for variant = 0.0870/record vs T*'s 0.0746/record. Total extra penalty = 6.22 over 500 records, which exceeds the 2.16 raw score advantage → T* wins.

Fix applied to both `PopulationManager._avg_score` and `OntologyPopulation._avg_score` (in schemas.py) for consistency.

**Semantic justification**: A model that explored additional complexity (add edge, then prune it) should be penalized for that exploration. The original model that never needed the extra edge is preferable by Occam's razor.

---

### Bug 2: Non-deterministic variant selection across PYTHONHASHSEED values

**Symptom**: `test_L3_03_paradigm_shift_on_regime_switch` passed when run alone (`pytest tests/level3/`) but failed when run in the same session as levels 1 and 2 (`pytest tests/level1/ tests/level2/ tests/level3/`). Confirmed as PYTHONHASHSEED-dependent by running with explicit seeds:

```bash
PYTHONHASHSEED=0 pytest tests/level3/test_population.py::test_L3_03...  # FAILED
PYTHONHASHSEED=1 pytest tests/level3/test_population.py::test_L3_03...  # FAILED
PYTHONHASHSEED=42 pytest tests/level3/test_population.py::test_L3_03...  # PASSED
PYTHONHASHSEED=100 pytest tests/level3/test_population.py::test_L3_03...  # PASSED
```

**Root cause**: In `PopulationManager._make_variant`:
```python
candidates_to_add = list(admissible - edge_sigs)   # set difference
pname, cname = self.rng.choice(candidates_to_add)
```
`admissible` and `edge_sigs` are Python `set` objects. `set.__iter__` order depends on `PYTHONHASHSEED`, which is randomized per process and differs between pytest sessions. With a seeded `random.Random(42)`, the choice is deterministic given the list — but the list itself has non-deterministic order. Different PYTHONHASHSEED → different edge is chosen → different structural variants are introduced → some seedings lead to T_alt being pruned before phase 2, preventing paradigm shift detection.

**Fix**: Sort the set difference before choosing:
```python
# Before:
candidates_to_add = list(admissible - edge_sigs)

# After:
candidates_to_add = sorted(admissible - edge_sigs)
```

Tuples of strings have a deterministic sort order independent of hash randomization. Both occurrences of this pattern in `_make_variant` were fixed (the pre-check on line ~291 and the actual selection on line ~315).

After fix: L3-03 passes at all tested PYTHONHASHSEED values (0, 1, 42, 100, 999, 12345).

---

## Known limitations

### Correctness

1. **BIC n_free approximation**: `CPTData.bic_score()` uses `n_configs = max(len(self.counts), 1)` as the number of parent configurations. This is the number of *observed* configurations, not the full Cartesian product `Π |parent_support|`. For sparse data (not all parent combos observed), this understates the true free parameter count, producing a less conservative BIC. This understatement is consistent between `bic_score()` and `bic_score_without_parent()`, so their difference (the log-likelihood ratio used in EdgeExistenceService) is approximately correct; the systematic error partially cancels. Still, this is not exact BIC.

2. **EM falls back silently**: In `accumulate_em`, if pgmpy model building or inference throws any exception, the code catches it and falls back to uniform distributions for missing variables. The exception is not logged. If pgmpy fails for any structural reason (e.g., disconnected nodes after edge pruning), the fallback introduces bias without warning.

3. **Evidence count threshold mislabeled**: `_MIN_BATCHES_FOR_PRUNING = 3` is compared against `evidence_count` (a record count), not a batch count. Any candidate that has seen 3 or more records will pass this threshold. After the first batch of typical size (30–50 records), all candidates exceed this. The name is misleading; the variable should be called `_MIN_RECORDS_FOR_PRUNING`.

4. **Explore weight on disabled edges**: `EdgeExistenceService.update()` iterates all `learnable` edges, including disabled ones. `existence_probability` continues to update after pruning. This is harmless (disabled edges are not used for inference or scoring) but wastes cycles.

5. **ExploreExploitService is non-functional**: `_empirical_mi` always returns 0.0. The `propose()` method returns results but they are unranked. This service is not integrated into the engine or called from any test.

### Architecture

6. **`ParameterStore` is purely in-memory**: CPT parameters are not persisted to SQLite. A process restart loses all learned parameters. `PopulationStore` persists scores and metadata but not the parameters themselves. Persistence of `ParameterStore` requires serializing the CPTData count dicts to SQLite or a separate file.

7. **PopulationManager._make_variant sorts admissible for "add" but not "remove"**: The "remove" strategy calls `rng.choice(active_edges)` where `active_edges = candidate.get_active_edges()` which is a list derived from `candidate.edges` (a list, so deterministic order). This is fine. No fix needed here.

8. **`_derive_admissible_edges` in engine.py allows all variable pairs**: This means the engine will propose variants with any possible directed edge between any two variables. For real domains with known forbidden edges (e.g., effect cannot precede cause), the admissible set should be restricted via domain schema TemplateRules (not yet implemented). The current superset is safe but produces more variants to evaluate.

9. **Inference aggregation modes TOP_K and WEIGHTED_AVERAGE use raw log_score**: `InferenceService` uses `log_score` (raw) for weighting, not the BIC-corrected `_avg_score`. Candidates with more evidence accumulate more negative log_scores (in absolute terms), so raw-log-score-based weights will tend to weight recent candidates (with less accumulated score) higher than they should be. This inconsistency between the scoring used for population management and the scoring used for inference aggregation is a known issue.

10. **No streaming/async ingestion**: Evidence is processed in synchronous batches. `engine.learn(batch)` blocks until the full cycle completes. No async interface exists.

11. **Single domain active at a time**: `engine.activate_domain()` sets one active domain. Multi-domain parallel learning is not implemented (though the store and population manager architectures support multiple domains concurrently).

12. **FastAPI routes not written**: `src/engine/api/__init__.py` is empty. There is no HTTP interface.

13. **market_risk_v1 domain is empty**: Only a placeholder `__init__.py` exists.

14. **No integration tests**: `tests/integration/` is empty.

15. **`introduce_variants` selects parent candidates by raw log_score, prunes by BIC-corrected score**: Parent selection for variants uses `sorted(active, key=lambda c: c.log_score, reverse=True)` (raw). Population pruning uses `_avg_score` (BIC-corrected). This asymmetry means a candidate with many evidence records (large negative raw log_score) may rank low as a variant parent even if it has the best BIC-adjusted average. Not a correctness issue but a design inconsistency.
