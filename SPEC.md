# Probabilistic Ontology Engine — Technical Specification v2

## 1. Purpose

This document specifies a domain-agnostic probabilistic ontology engine whose primary purpose is the computational encoding of epistemology: a formal, inspectable, updatable belief system that can be instantiated over any domain by loading a domain module.

The system is not principally a prediction engine, though prediction is a natural byproduct. Its core concern is representing *how beliefs are formed, how they are revised in light of evidence, and how whole belief structures compete and are discarded.* Bayesian probability theory is adopted as the epistemological foundation — beliefs are probability distributions, and rational belief update is conditioning on evidence.

The architecture is motivated by the observation that epistemology operates at three distinct levels, each requiring its own representation and update mechanism:

1. **Parameter level** — how strongly do I believe in a known relationship?
2. **Edge level** — do I believe this relationship exists at all?
3. **Structure level** — which whole belief system do I currently inhabit?

All three levels are first-class objects in this engine.

---

## 2. System goals

### 2.1 Functional goals

- Represent entities, variables, relations, and conditional dependencies in a machine-operable graph form.
- Treat edge existence as a probabilistic quantity, not a Boolean design decision.
- Maintain a population of competing ontologies (whole belief structures) and score them against evidence.
- Support continual parameter update from streaming or batch observations.
- Support explore-exploit-driven candidate edge proposal for discovering previously unknown relationships.
- Discard low-scoring ontologies from the population when evidence mass collapses below threshold.
- Expose a stable domain module interface so any domain can be plugged into the same engine.
- Produce inspectable, human-readable explanations of current beliefs and their evidential basis.

### 2.2 Non-functional goals

- Domain independence at the engine layer.
- Deterministic serialization and reproducible runs given the same evidence sequence and random seed.
- Explainable outputs: posterior traces, edge existence probabilities, active path contributions, evidence lineage.
- The system should be legible as a philosophical artifact — its structure should be readable as an argument about how beliefs work, not just as engineering.

---

## 3. Conceptual model

### 3.1 Three levels of belief

The engine separates belief into three levels that interact but update by distinct mechanisms.

```
Level 3: Structure   — a population of competing whole ontologies (OntologyCandidate[])
                         each scored by cumulative evidence fit
                         low-scoring candidates discarded; variants of high-scoring candidates introduced

Level 2: Edge        — within each ontology, every dependency edge carries an existence probability
                         P(edge exists) in [0,1], updated as evidence arrives
                         edges with existence probability below threshold are pruned

Level 1: Parameter   — within each edge that exists, the conditional probability table or factor
                         is updated continuously as evidence arrives
                         this is standard Bayesian parameter learning
```

A Kuhnian paradigm shift corresponds to a Level 3 event: the dominant ontology candidate loses probability mass rapidly and a previously minority candidate rises to dominance. Parameter updates within a stable ontology correspond to normal science.

### 3.2 Five architectural layers

1. **Ontology layer** — type system, entity classes, relation classes, schema constraints, admissible dependency templates.
2. **Probabilistic layer** — random variables, priors, CPTs, edge existence distributions, factor weights.
3. **Inference layer** — posterior computation, query answering, evidence propagation, explanation extraction, weighted aggregation across ontology population.
4. **Learning layer** — parameter estimation, edge existence update, structure scoring, candidate introduction and pruning.
5. **Domain adapter layer** — maps raw domain observations into canonical evidence records; defines domain tasks, priors, and initial ontology candidates.

---

## 4. Core abstractions

### 4.1 Ontology primitives

#### Class

```text
Class {
  class_id: UUID
  name: string
  parent_classes: list[ClassRef]
  attributes: list[AttributeDef]
  constraints: list[ConstraintDef]
}
```

#### RelationType

```text
RelationType {
  relation_type_id: UUID
  name: string
  subject_class: ClassRef
  object_class: ClassRef
  cardinality: enum{ONE_ONE, ONE_MANY, MANY_ONE, MANY_MANY}
  semantics: enum{CAUSAL, CORRELATIONAL, TAXONOMIC, TEMPORAL, COMPOSITIONAL, OBSERVATIONAL}
  constraints: list[ConstraintDef]
}
```

#### Entity

```text
Entity {
  entity_id: UUID
  class_ref: ClassRef
  static_attributes: map[string, Scalar|Categorical|Vector|Distribution]
  provenance: ProvenanceRef
}
```

#### Assertion / Triple

```text
Assertion {
  assertion_id: UUID
  subject_entity_id: UUID
  relation_type_id: UUID
  object_entity_id: UUID
  validity_interval: TimeRange?
  confidence: float in [0,1]
  provenance: ProvenanceRef
}
```

### 4.2 Probabilistic primitives

#### Variable

```text
Variable {
  variable_id: UUID
  name: string
  domain_type: enum{BOOLEAN, CATEGORICAL, ORDINAL, CONTINUOUS, COUNT}
  support: list[value] | interval
  associated_entity_class: ClassRef?
  associated_relation_type: RelationTypeRef?
  time_indexed: bool
  hidden: bool
}
```

#### DependencyEdge

The key change from v1: `existence_probability` and `existence_prior` are now first-class fields. An edge is not simply present or absent — it has a probability of existing that is updated from evidence.

```text
DependencyEdge {
  edge_id: UUID
  parent_variable_id: UUID
  child_variable_id: UUID
  dependency_kind: enum{DIRECTED_CONDITIONAL, FACTOR_LINK, AGGREGATION_LINK}

  existence_prior: float in [0,1]       -- prior belief that this edge exists at all
  existence_probability: float in [0,1] -- current posterior belief that this edge exists
  existence_update_count: int           -- how many evidence batches have touched this edge

  strength_prior: Distribution          -- prior over CPT parameters, conditional on edge existing
  explanatory_label: string
  learnable: bool
  explore_weight: float                 -- exploration allocation; higher = more evidence assigned
                                        -- to resolving this edge's existence uncertainty
}
```

#### Parameterization

```text
Parameterization {
  parameterization_id: UUID
  variable_id: UUID
  family: enum{TABULAR_CPT, GAUSSIAN_CPD, CONDITIONAL_LINEAR_GAUSSIAN, LOGISTIC_FACTOR, NOISY_OR, CUSTOM_FACTOR}
  parameter_blob: bytes | JSON
  smoothing_config: map[string, number]
  last_fit_timestamp: datetime
}
```

#### EvidenceRecord

```text
EvidenceRecord {
  evidence_id: UUID
  timestamp: datetime
  observed_assignments: list[ObservedAssignment]
  source_type: enum{STREAM, BATCH, MANUAL, SIMULATION, API, FILE}
  source_ref: string
  confidence: float in [0,1]
}

ObservedAssignment {
  variable_id: UUID
  observed_value: value
  missingness: enum{OBSERVED, MISSING, IMPUTED, REDACTED}
  confidence: float in [0,1]
}
```

### 4.3 OntologyCandidate — the Level 3 primitive

This is the key addition in v2. The engine maintains a population of OntologyCandidates. Each is a complete belief structure: a set of variables, a dependency graph with edge existence probabilities, and a parameterization. Candidates are scored against evidence and compete for survival.

```text
OntologyCandidate {
  candidate_id: UUID
  domain_module_id: string
  generation: int                        -- increments each time a new candidate is derived
  parent_candidate_id: UUID?             -- lineage tracking

  variables: list[Variable]
  edges: list[DependencyEdge]
  parameterizations: list[Parameterization]

  log_score: float                       -- cumulative log-likelihood under observed evidence
  score_window: [timestamp, timestamp]   -- evidence window used for current score
  evidence_count: int                    -- total evidence records processed

  status: enum{ACTIVE, PRUNED, ARCHIVED}
  introduced_at: timestamp
  pruned_at: timestamp?
  pruning_reason: string?
}
```

#### Population

```text
OntologyPopulation {
  population_id: UUID
  domain_module_id: string
  max_population_size: int               -- recommended 5–20 for tractability
  candidates: list[OntologyCandidate]
  active_candidate_id: UUID              -- highest-scoring candidate; used for primary queries
  generation: int
}
```

### 4.4 Query primitives

```text
InferenceQuery {
  query_id: UUID
  target_variables: list[variable_id]
  conditioned_on: list[ObservedAssignment]
  query_type: enum{MARGINAL, MAP, CONDITIONAL, INTERVENTION, EXPLANATION, FORECAST}
  population_aggregation: enum{ACTIVE_ONLY, WEIGHTED_AVERAGE, TOP_K}
  horizon: int?
  top_k: int?
}
```

`population_aggregation` controls whether the query is answered by the single highest-scoring ontology (ACTIVE_ONLY), by a weighted average across all active candidates (WEIGHTED_AVERAGE), or by the top K candidates (TOP_K). Weighted average is the epistemologically honest choice when structure uncertainty is high.

---

## 5. Formal semantics

### 5.1 Three-level belief update

**Level 1 — Parameter update:**
Given edge e exists (existence_probability > threshold), update the CPT parameters for that edge using the incoming evidence batch. Standard Bayesian conjugate update or MLE depending on family.

**Level 2 — Edge existence update:**
For each edge e, treat existence as a latent boolean variable with a Beta prior. After observing evidence, compute the marginal likelihood of the evidence under the model with e active vs. the model with e inactive. Update existence_probability by Bayes' rule:

```
P(e exists | evidence) ∝ P(evidence | e exists) * P(e exists)
```

Edges whose existence_probability falls below a domain-configurable threshold are pruned. Edges near 0.5 (maximum existence uncertainty) receive elevated explore_weight.

**Level 3 — Ontology candidate scoring and replacement:**
Each OntologyCandidate accumulates a log_score as evidence arrives:

```
log_score += log P(evidence | candidate_graph, candidate_params)
```

After each learning cycle, candidates are ranked by log_score. Candidates in the bottom quartile (or below a minimum threshold) are marked PRUNED. New candidates are introduced as variants of the highest-scoring survivors — typically by proposing one or two edge additions or removals, constrained by the ontology schema templates. Population size is held bounded.

### 5.2 Explore-exploit for edge discovery

The engine allocates attention to candidate edges it has not yet resolved. An unresolved edge is one whose existence_probability is near 0.5 — the engine does not yet have a confident belief about whether this relationship is real.

The explore_weight field on DependencyEdge controls how much of each evidence batch is used to evaluate that edge's existence. High explore_weight edges receive more focused statistical testing. As existence_probability converges toward 0 or 1, explore_weight decays.

New candidate edges are proposed from the set of ontology-admissible pairs not yet in the active graph. Proposal strategies:

- Mutual information screening over recent evidence
- Temporal precedence screening for time-indexed variables
- Residual-error driven proposals (variables with high unexplained variance)
- LLM-assisted hypothesis proposal, followed by hard validation against schema constraints

### 5.3 Graph semantics

The ontology graph encodes admissible object types and relation types. The probabilistic graph encodes statistical or causal dependencies among variables derived from entities, relations, or aggregates. The two graphs are distinct but linked: the ontology graph constrains which edges are admissible in the probabilistic graph via TemplateRules.

### 5.4 Ontology-to-probability alignment

```text
TemplateRule:
  IF relation_type.semantics == CAUSAL
  THEN allow directed dependency from subject-derived variable to object-derived variable
```

This prevents arbitrary graph induction that violates domain type constraints. All candidate edges proposed during explore-exploit must pass schema template validation before being introduced into any OntologyCandidate.

---

## 6. Architecture

### 6.1 Modules

```text
+--------------------------------------------------------------+
| ProbabilisticOntologyEngine                                  |
|--------------------------------------------------------------|
| SchemaRegistry                                               |
| DomainModuleRegistry                                         |
| OntologyStore                                                |
| VariableStore                                                |
| ParameterStore                                               |
| EvidenceStore                                                |
| PopulationManager          <-- new in v2                     |
| InferenceService                                             |
| LearningService                                              |
| EdgeExistenceService       <-- new in v2                     |
| ExploreExploitService      <-- new in v2                     |
| StructureSearchService                                       |
| PruningService                                               |
| ExplanationService                                           |
| EvaluationService                                            |
| SerializationService                                         |
+--------------------------------------------------------------+
```

### 6.2 New services in v2

#### PopulationManager
- Maintains the OntologyPopulation for each active domain.
- Scores candidates after each learning cycle.
- Introduces new candidates as variants of high-scoring survivors.
- Prunes low-scoring candidates and archives them with their lineage.
- Enforces max_population_size.
- Tracks which candidate is currently ACTIVE (highest scoring).

#### EdgeExistenceService
- Maintains existence_probability for every edge in every candidate.
- Runs Bayesian existence update after each evidence batch.
- Triggers pruning of edges whose existence_probability falls below threshold.
- Reports edges near 0.5 to ExploreExploitService.

#### ExploreExploitService
- Maintains explore_weight for all edges, including candidate edges not yet in any graph.
- Proposes new candidate edges from the ontology-admissible space.
- Allocates evidence attention across existing uncertain edges and new proposals.
- Hands accepted candidates to StructureSearchService for scoring.

---

## 7. Storage model

### 7.1 Logical stores

- Relational store for parameters, evidence records, metrics, population state, and job metadata.
- Graph database or adjacency tables for ontology assertions and relation traversal.
- Columnar or object store for large observation batches.

### 7.2 Canonical relational schema additions (v2)

The v1 schema is preserved. The following tables are added or modified.

```text
TABLE ontology_candidates(
  candidate_id UUID PRIMARY KEY,
  domain_module_id TEXT NOT NULL,
  generation INT NOT NULL,
  parent_candidate_id UUID NULL,
  log_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  evidence_count INT NOT NULL DEFAULT 0,
  score_window_start TIMESTAMP NULL,
  score_window_end TIMESTAMP NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  introduced_at TIMESTAMP NOT NULL,
  pruned_at TIMESTAMP NULL,
  pruning_reason TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'
)

TABLE ontology_populations(
  population_id UUID PRIMARY KEY,
  domain_module_id TEXT NOT NULL UNIQUE,
  max_population_size INT NOT NULL DEFAULT 10,
  active_candidate_id UUID NOT NULL,
  generation INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL
)

-- Modified: dependency_edges now scoped to a candidate
TABLE dependency_edges(
  edge_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL,             -- FK -> ontology_candidates
  parent_variable_id UUID NOT NULL,
  child_variable_id UUID NOT NULL,
  dependency_kind TEXT NOT NULL,
  existence_prior DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  existence_probability DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  existence_update_count INT NOT NULL DEFAULT 0,
  explore_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  strength_prior JSONB NOT NULL,
  explanatory_label TEXT NOT NULL DEFAULT '',
  learnable BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'
)

TABLE candidate_scores(
  score_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL,
  ts TIMESTAMP NOT NULL,
  log_likelihood DOUBLE PRECISION NOT NULL,
  evidence_batch_id UUID NOT NULL,
  context JSONB NOT NULL DEFAULT '{}'
)
```

---

## 8. Domain module contract

Every domain module SHALL implement the following interface. v2 adds `initial_candidates()` which provides the seed population of ontology candidates.

```text
interface DomainModule {
  module_id(): string
  version(): SemVer
  schema(): DomainSchema
  initial_entities(): list[Entity]
  initial_assertions(): list[Assertion]
  variable_specs(): list[VariableSpec]
  initial_parameterizations(): list[Parameterization]
  initial_candidates(): list[OntologyCandidateSpec]   -- new in v2
  evidence_mapper(raw_observation: bytes|JSON|Row): EvidenceRecord
  target_queries(): list[InferenceQueryTemplate]
  evaluation_targets(): list[EvaluationTarget]
  structure_constraints(): list[StructureConstraint]
  explanation_templates(): list[ExplanationTemplate]
  existence_thresholds(): EdgeExistenceThresholdConfig  -- new in v2
}
```

#### EdgeExistenceThresholdConfig

```text
EdgeExistenceThresholdConfig {
  prune_below: float          -- edges pruned when existence_probability < this (e.g. 0.05)
  accept_above: float         -- edges considered established when existence_probability > this (e.g. 0.90)
  explore_band: [float,float] -- existence uncertainty band triggering exploration (e.g. [0.3, 0.7])
}
```

---

## 9. Inference specification

### 9.1 Supported inference modes

- Exact inference for small DAGs via variable elimination or junction tree.
- Approximate inference via ancestral sampling, importance sampling, or loopy belief propagation for larger graphs.
- Population-weighted inference: posteriors aggregated across OntologyCandidates weighted by exp(log_score).
- Active-only inference: query answered by the single highest-scoring candidate for speed.
- Explanation extraction: active path tracing and edge existence contribution reporting.

### 9.2 Inference API

```text
POST /v1/inference/query
{
  "domain_module": "market-risk-v1",
  "targets": ["MarketDrop"],
  "conditioned_on": [
    {"variable": "BadWeather", "value": true, "confidence": 1.0},
    {"variable": "EnergyPriceUp", "value": true, "confidence": 0.85}
  ],
  "query_type": "MARGINAL",
  "population_aggregation": "WEIGHTED_AVERAGE",
  "explain": true
}
```

Response:

```json
{
  "query_id": "...",
  "posteriors": [
    {"variable": "MarketDrop", "distribution": {"true": 0.73, "false": 0.27}}
  ],
  "population_summary": {
    "active_candidates": 8,
    "dominant_candidate": "cand-004",
    "dominant_score": -12.4,
    "structure_entropy": 0.61
  },
  "explanations": [
    {
      "path": ["BadWeather", "SupplyShock", "MarketDrop"],
      "contribution": 0.41,
      "edge_existence_probabilities": [0.92, 0.87],
      "evidence_support": ["ev-102", "ev-212"]
    }
  ],
  "model_version": "market-risk-v1@gen-7"
}
```

`structure_entropy` is a new field: it measures how spread out probability mass is across the ontology population. High entropy means the engine is genuinely uncertain which belief structure is correct — a legible signal of epistemic humility.

---

## 10. Learning specification

### 10.1 Update algorithm

```text
function LEARN(evidence_batch):
  validate(evidence_batch)
  map batch into canonical EvidenceRecords

  for each active OntologyCandidate:
    update Level 1 (CPT parameters) given edge existence posteriors
    update Level 2 (edge existence probabilities) via Bayesian marginal likelihood
    compute log P(evidence | candidate) and update candidate.log_score
    prune edges below existence threshold
    update explore_weights for uncertain edges

  PopulationManager:
    rank candidates by log_score
    prune bottom-quartile candidates (mark PRUNED, archive with lineage)
    if population_size < max:
      propose new candidates as variants of top survivors
      validate proposed candidates against schema constraints
      introduce accepted candidates with existence priors from parent

  ExploreExploitService:
    propose new candidate edges from admissible space
    score proposals against recent evidence
    introduce high-scoring proposals into candidate graphs

  version model snapshot
  emit audit log and evaluation report
```

### 10.2 Parameter learning

- Bayesian updating with conjugate priors where supported.
- Maximum likelihood estimation for complete data.
- EM-style estimation for missing or latent variables.
- Online sufficient-statistics updates for streaming evidence.

### 10.3 Candidate introduction strategies

When the PopulationManager introduces a new candidate as a variant of a survivor, the variation is one of:

- Add one ontology-admissible edge with existence_prior = 0.5 (unexplored relationship)
- Remove one edge with low existence_probability from parent
- Swap one edge's direction (where schema permits)
- Introduce one new latent variable with admissible connections

All variants must pass schema template validation before entering the population.

### 10.4 Pruning rules

**Edge pruning (Level 2):**
- existence_probability < domain prune_below threshold for N consecutive windows
- Strong redundancy with a sparser alternative path

**Candidate pruning (Level 3):**
- log_score in bottom quartile of population after minimum evidence_count threshold reached
- Candidate has not improved relative rank in K consecutive learning cycles

---

## 11. Explanation specification

### 11.1 Explanation contract

The explanation subsystem SHALL provide:

- Influential variables in the active inference path
- Active dependency paths with per-edge existence probabilities
- Evidence lineage (which evidence records influenced which edges)
- Sensitivity summary (how much would the posterior change if a given edge were removed)
- Population state summary (structure_entropy, dominant candidate, lineage of dominant candidate)
- Calibration notes

The population state summary is new in v2 and makes the epistemological layer visible: a user can inspect not just what the system believes, but how confident it is in the structure of its beliefs and how that structure has evolved over generations.

---

## 12. Versioning and reproducibility

Each model snapshot MUST include:

```text
ModelSnapshot {
  snapshot_id: UUID
  engine_version: SemVer
  domain_module_version: SemVer
  schema_hash: SHA256
  population_state_hash: SHA256        -- hash of all active candidate graphs and scores
  parameter_hash: SHA256
  evidence_window: [timestamp, timestamp]
  random_seed: uint64
  fit_config: JSON
  metrics: JSON
  created_at: timestamp
}
```

Snapshots SHALL be immutable and replayable from source evidence.

---

## 13. Evaluation specification

### 13.1 Predictive metrics

- Log loss, Brier score, AUROC/AUPRC for binary targets
- Calibration error
- Forecast sharpness

### 13.2 Structural metrics

- Edge existence entropy (average H(existence_probability) across all edges — high means more unresolved relationships)
- Population structure_entropy (spread of probability mass across competing ontologies)
- Template compliance rate
- Pruned-candidate rate per generation
- Mean candidate lifetime (generations survived before pruning)
- Dominant candidate stability (how many generations has the current leader held top rank)

### 13.3 Epistemological health metrics

These are new in v2 and reflect the system's epistemic state rather than just its predictive performance:

- **Paradigm shift rate**: frequency of dominant candidate changes per evidence window
- **Edge resolution rate**: rate at which edges are converging toward 0 or 1 existence probability
- **Exploration frontier size**: number of candidate edges with existence_probability near 0.5
- **Structural consensus**: fraction of population sharing the same top-K edges

---

## 14. API specification

### 14.1 Lifecycle

```text
POST   /v1/domains/register
POST   /v1/domains/{id}/activate
POST   /v1/evidence/ingest
POST   /v1/inference/query
POST   /v1/learning/update
POST   /v1/population/status          -- new in v2
POST   /v1/population/candidates      -- new in v2
GET    /v1/population/lineage/{id}    -- new in v2
POST   /v1/explanations/query
GET    /v1/models/{snapshot_id}
GET    /v1/metrics
POST   /v1/export
POST   /v1/import
```

### 14.2 Population status response

```json
{
  "domain_module": "market-risk-v1",
  "generation": 7,
  "active_candidates": 8,
  "dominant_candidate": {
    "candidate_id": "cand-004",
    "generation": 3,
    "parent_candidate_id": "cand-001",
    "log_score": -12.4,
    "evidence_count": 842,
    "edge_count": 5,
    "edges": [
      {"label": "BadWeather->SupplyShock", "existence_probability": 0.93},
      {"label": "BadWeather->EnergyPriceUp", "existence_probability": 0.87},
      {"label": "SupplyShock->MarketDrop", "existence_probability": 0.78},
      {"label": "EnergyPriceUp->MarketDrop", "existence_probability": 0.71},
      {"label": "InterestRate->MarketDrop", "existence_probability": 0.54}
    ]
  },
  "structure_entropy": 0.61,
  "paradigm_shift_count": 2,
  "exploration_frontier_size": 3
}
```

---

## 15. LLM integration specification

The engine MAY expose an LLM-facing semantic layer that converts natural-language requests into structured queries, constrained domain edits, or candidate hypotheses. The LLM MUST NOT directly mutate the graph or parameters without validation.

```text
LLMRequest -> IntentParser -> SchemaConstrainedIntermediateForm -> Validator -> EngineCommand
```

### 15.1 Allowed LLM-generated artifacts

- Query templates
- Candidate ontology labels
- Candidate evidence extraction mappings
- Candidate edge hypotheses (subject to schema validation and existence scoring before introduction)
- Explanation paraphrases
- Natural language summaries of population state and paradigm shifts

### 15.2 Forbidden direct actions

- Unvalidated parameter overwrite
- Direct insertion of type-invalid edges
- Disabling safety constraints
- Destructive pruning without score evidence
- Ontology mutation that violates schema hashes or template policies

---

## 16. Reference implementation guidance

### 16.1 Recommended stack

- Language: Python 3.12+
- Storage: PostgreSQL + adjacency tables (PostgreSQL-only MVP; Neo4j/Memgraph for scale)
- Probabilistic computation: pgmpy for Bayesian network inference; NumPy for edge existence updates
- Population management: custom; no existing library handles this directly
- Queueing: Celery or lightweight job runner for learning cycles
- Serialization: Pydantic + JSON Schema
- API: FastAPI

### 16.2 MVP scope

A minimum viable implementation SHOULD support:

- Boolean and categorical variables only
- DAG constraint enforced globally
- Tabular CPTs only
- Batch evidence ingestion
- Exact inference for small graphs (< ~20 variables)
- Edge existence probability tracked per edge, updated via marginal likelihood ratio
- Population of 3–5 ontology candidates
- Candidate scoring by cumulative log-likelihood
- Simple candidate introduction: add or remove one edge per variant
- JSON domain module packaging
- Posterior explanation via active path listing with edge existence probabilities
- Population status endpoint

### 16.3 Expansion path

Phase 2:
- Continuous variables
- Online learning and streaming evidence
- Dynamic Bayesian networks (time-sliced variables)
- Larger populations (up to 20 candidates)
- Explore-exploit edge allocation

Phase 3:
- Factor-graph mode for non-DAG dependencies
- Counterfactual interventions
- Multi-domain shared upper ontology
- LLM-assisted hypothesis generation with evaluation sandbox
- Coherentist extensions (undirected consistency constraints layered on top of Bayesian core)

---

## 17. Pseudocode end-to-end

```text
class ProbabilisticOntologyEngine:
    def __init__(self, schema_registry, stores, services):
        self.schema_registry = schema_registry
        self.ontology_store = stores.ontology_store
        self.variable_store = stores.variable_store
        self.parameter_store = stores.parameter_store
        self.evidence_store = stores.evidence_store
        self.population_manager = services.population_manager
        self.inference = services.inference
        self.learning = services.learning
        self.edge_existence = services.edge_existence
        self.explore_exploit = services.explore_exploit
        self.explanations = services.explanations
        self.active_domain = None

    def register_domain(self, module):
        validate_module_against_meta_schema(module)
        self.schema_registry.put(module.schema())
        self.ontology_store.load_entities(module.initial_entities())
        self.ontology_store.load_assertions(module.initial_assertions())
        self.variable_store.load_specs(module.variable_specs())
        self.parameter_store.load(module.initial_parameterizations())
        self.population_manager.initialize(
            module.initial_candidates(),
            module.existence_thresholds()
        )

    def activate_domain(self, module_id):
        self.active_domain = module_id

    def ingest(self, raw_observation):
        module = get_module(self.active_domain)
        ev = module.evidence_mapper(raw_observation)
        validate_evidence(ev)
        self.evidence_store.append(ev)
        return ev.evidence_id

    def query(self, inference_query):
        population = self.population_manager.get_population(self.active_domain)
        if inference_query.population_aggregation == ACTIVE_ONLY:
            candidate = population.active_candidate()
            posterior = self.inference.run(candidate, inference_query)
            explanation = self.explanations.generate(candidate, inference_query, posterior)
        else:
            posteriors = [self.inference.run(c, inference_query) for c in population.active_candidates()]
            weights = population.score_weights()
            posterior = weighted_average(posteriors, weights)
            explanation = self.explanations.generate_population(population, inference_query, posterior)
        return {
            "posterior": posterior,
            "explanation": explanation,
            "population_summary": population.summary()
        }

    def learn(self, evidence_window):
        batch = self.evidence_store.load_window(evidence_window)
        population = self.population_manager.get_population(self.active_domain)

        for candidate in population.active_candidates():
            # Level 1: parameter update
            sufficient_stats = self.learning.accumulate(batch, candidate)
            fitted = self.learning.fit(candidate, sufficient_stats)
            self.parameter_store.commit(candidate.candidate_id, fitted)

            # Level 2: edge existence update
            self.edge_existence.update(candidate, batch)
            self.edge_existence.prune_below_threshold(candidate)

            # Score candidate
            log_lik = self.learning.score(candidate, batch)
            self.population_manager.update_score(candidate, log_lik)

        # Level 3: population management
        self.population_manager.prune_low_scorers()
        new_candidates = self.population_manager.introduce_variants()
        for c in new_candidates:
            if valid_under_schema(c):
                population.add(c)

        # Explore-exploit: propose new edges
        proposals = self.explore_exploit.propose(population, batch)
        for p in proposals:
            if valid_under_schema(p) and improves_score(p, batch):
                population.add_edge_to_candidate(p)

        snapshot = snapshot_population(population, evidence_window)
        return snapshot
```

---

## 18. Example domain package (market-risk-v1)

```json
{
  "module_id": "market-risk-v1",
  "version": "1.0.0",
  "classes": [
    {"name": "WeatherEvent"},
    {"name": "SupplyState"},
    {"name": "EnergyState"},
    {"name": "MarketState"},
    {"name": "MonetaryState"}
  ],
  "relation_types": [
    {"name": "affects_supply", "subject_class": "WeatherEvent", "object_class": "SupplyState", "semantics": "CAUSAL"},
    {"name": "affects_energy", "subject_class": "WeatherEvent", "object_class": "EnergyState", "semantics": "CAUSAL"},
    {"name": "affects_market", "subject_class": "SupplyState", "object_class": "MarketState", "semantics": "CAUSAL"},
    {"name": "affects_market", "subject_class": "EnergyState", "object_class": "MarketState", "semantics": "CAUSAL"},
    {"name": "affects_market", "subject_class": "MonetaryState", "object_class": "MarketState", "semantics": "CAUSAL"}
  ],
  "variables": [
    {"name": "BadWeather", "domain_type": "BOOLEAN"},
    {"name": "SupplyShock", "domain_type": "BOOLEAN"},
    {"name": "EnergyPriceUp", "domain_type": "BOOLEAN"},
    {"name": "InterestRateRise", "domain_type": "BOOLEAN"},
    {"name": "MarketDrop", "domain_type": "BOOLEAN"}
  ],
  "initial_candidates": [
    {
      "candidate_id": "cand-001",
      "description": "Weather-supply chain hypothesis",
      "edges": [
        {"from": "BadWeather", "to": "SupplyShock", "existence_prior": 0.7},
        {"from": "BadWeather", "to": "EnergyPriceUp", "existence_prior": 0.6},
        {"from": "SupplyShock", "to": "MarketDrop", "existence_prior": 0.65},
        {"from": "EnergyPriceUp", "to": "MarketDrop", "existence_prior": 0.6}
      ]
    },
    {
      "candidate_id": "cand-002",
      "description": "Monetary policy dominance hypothesis",
      "edges": [
        {"from": "InterestRateRise", "to": "MarketDrop", "existence_prior": 0.8},
        {"from": "EnergyPriceUp", "to": "MarketDrop", "existence_prior": 0.5},
        {"from": "BadWeather", "to": "EnergyPriceUp", "existence_prior": 0.4}
      ]
    },
    {
      "candidate_id": "cand-003",
      "description": "Null hypothesis — minimal structure",
      "edges": [
        {"from": "SupplyShock", "to": "MarketDrop", "existence_prior": 0.5}
      ]
    }
  ],
  "existence_thresholds": {
    "prune_below": 0.05,
    "accept_above": 0.90,
    "explore_band": [0.3, 0.7]
  }
}
```

---

## 19. Implementation note for code-generation tools

To maximize usefulness with Claude Code, Codex, or similar tools, the recommended prompt payload should include:

- This specification
- The desired implementation language and stack
- The selected MVP scope (recommend starting with 3 candidates, boolean variables, exact inference)
- The first domain module to implement
- Required tests and evaluation metrics
- Desired API surface
- Expected serialization format

The most efficient initial build target is a Python MVP with:

- Pydantic schemas for all primitives including OntologyCandidate and OntologyPopulation
- PostgreSQL or SQLite for metadata, evidence, and population state
- NetworkX for graph operations within each candidate
- pgmpy for Bayesian network inference
- NumPy for edge existence probability updates
- FastAPI for the engine API
- pytest for verification

The PopulationManager is the novel component with no existing library analog. Build it first as a simple scored list with threshold-based pruning before adding variant introduction.

---

## 20. Testing specification

Testing a learning system requires a different strategy than testing a standard API. Outputs change as evidence accumulates, so tests must control ground truth synthetically and verify convergence behavior rather than fixed return values. The testing strategy is organized by the three belief levels, plus integration tests that exercise the full learning loop.

### 20.1 Synthetic test domain

All non-trivial tests operate against a synthetic domain module `test-domain-v1` whose ground truth is fully known and controlled. This module is a first-class deliverable alongside the market-risk module.

#### Ground truth graph (T*)

```text
Variables (all BOOLEAN):
  A, B, C, D, E

True dependency structure T*:
  A → C   (CPT: P(C=true|A=true)=0.8, P(C=true|A=false)=0.1)
  B → C   (CPT: P(C=true|A=true,B=true)=0.95, P(C=true|A=false,B=false)=0.05)
  B → D   (CPT: P(D=true|B=true)=0.7, P(D=true|B=false)=0.2)
  C → E   (CPT: P(E=true|C=true)=0.85, P(E=true|C=false)=0.15)
  D → E   (CPT: P(E=true|D=true,C=true)=0.9, P(E=true|D=false,C=false)=0.1)

Spurious edges (NOT in T*, must be rejected):
  A → D
  A → E
  B → E  (indirect only via C and D)
```

#### Synthetic data generator

```python
class SyntheticDataGenerator:
    """
    Samples EvidenceRecords from the ground truth graph T*.
    Supports regime switching for paradigm shift tests.
    """
    def __init__(self, graph: str = "T*", random_seed: int = 42):
        self.graph = graph   # "T*" | "T_alt" for regime switch tests
        self.rng = np.random.default_rng(random_seed)

    def sample(self, n: int) -> list[EvidenceRecord]:
        ...

    def switch_regime(self, new_graph: str):
        """Switch generating distribution mid-stream for paradigm shift tests."""
        self.graph = new_graph
```

#### Alternative graph T_alt (for paradigm shift tests)

```text
T_alt differs from T* in two ways:
  - Removes edge B → D
  - Adds edge A → D  (was spurious in T*)
  - P(D=true|A=true)=0.75, P(D=true|A=false)=0.15
```

---

### 20.2 Level 1 tests — parameter learning

These tests fix graph structure and verify CPT parameter convergence.

#### TEST-L1-01: Conjugate prior update — single variable

```python
def test_parameter_update_single_variable():
    """
    Given: variable C with known prior Beta(2,2) over P(C=true)
    When: 100 evidence records are ingested with true P(C=true) = 0.7
    Then: posterior mean of P(C=true) converges within 0.05 of 0.7
    """
    engine = make_engine_with_fixed_graph("T*")
    evidence = generator.sample_variable_only("C", n=100, p_true=0.7)
    engine.ingest_batch(evidence)
    posterior = engine.parameter_store.get("C")
    assert abs(posterior.mean - 0.7) < 0.05
```

#### TEST-L1-02: CPT convergence under full graph

```python
def test_cpt_convergence_full_graph():
    """
    Given: fixed graph T*, all edges enabled, uniform priors
    When: 500 evidence records sampled from T* ground truth CPTs
    Then: all learned CPT entries within 0.08 of ground truth values
    """
    engine = make_engine_with_fixed_graph("T*")
    evidence = generator.sample(n=500)
    engine.ingest_batch(evidence)
    for variable in ["A", "B", "C", "D", "E"]:
        learned = engine.parameter_store.get_cpt(variable)
        ground_truth = T_STAR_CPTS[variable]
        for key in ground_truth:
            assert abs(learned[key] - ground_truth[key]) < 0.08, \
                f"CPT mismatch for {variable}[{key}]"
```

#### TEST-L1-03: Reproducibility

```python
def test_parameter_reproducibility():
    """
    Given: identical evidence sequence and random seed
    When: learning is run twice
    Then: parameter blobs are bitwise identical
    """
    e1 = run_learning_cycle(evidence, seed=42)
    e2 = run_learning_cycle(evidence, seed=42)
    assert e1.parameter_hash == e2.parameter_hash
```

#### TEST-L1-04: Missing evidence handling

```python
def test_missing_evidence_em():
    """
    Given: 30% of observed_assignments have missingness=MISSING
    When: EM parameter fitting runs
    Then: CPT convergence still achieved within 0.12 of ground truth
          (wider tolerance than full-observation test)
    """
```

---

### 20.3 Level 2 tests — edge existence

These tests verify that the system correctly identifies which edges are real and which are spurious given sufficient evidence.

#### TEST-L2-01: True edge existence rises

```python
def test_true_edge_existence_rises():
    """
    Given: edge A→C initialized with existence_prior=0.5
    When: 300 evidence records sampled from T* (where A→C is real)
    Then: existence_probability(A→C) > 0.85 after 300 records
    """
    engine = make_engine_with_population(["T*_candidate"])
    evidence = generator.sample(n=300)
    for batch in chunk(evidence, size=30):
        engine.learn(batch)
    p = engine.edge_existence.get("A", "C")
    assert p > 0.85, f"Expected >0.85, got {p}"
```

#### TEST-L2-02: Spurious edge existence falls

```python
def test_spurious_edge_existence_falls():
    """
    Given: edge A→D initialized with existence_prior=0.5
           (A→D is spurious in T* — not in ground truth)
    When: 300 evidence records sampled from T*
    Then: existence_probability(A→D) < 0.15 after 300 records
    """
    candidate = make_candidate_with_extra_edge("A", "D")
    engine = make_engine_with_candidate(candidate)
    evidence = generator.sample(n=300)
    for batch in chunk(evidence, size=30):
        engine.learn(batch)
    p = engine.edge_existence.get("A", "D")
    assert p < 0.15, f"Expected <0.15, got {p}"
```

#### TEST-L2-03: Existence update is monotone in expectation

```python
def test_existence_update_direction():
    """
    Given: a true edge and a spurious edge, both at prior=0.5
    When: evidence batches arrive sequentially from T*
    Then: true edge existence probability is strictly increasing
          in expectation across batches (may fluctuate per batch,
          but rolling mean must trend upward)
          spurious edge existence probability trends downward
    """
```

#### TEST-L2-04: Edge pruning fires at threshold

```python
def test_edge_pruned_at_threshold():
    """
    Given: existence_thresholds.prune_below = 0.05
           spurious edge A→D initialized at prior=0.5
    When: 500 evidence records from T* are ingested
    Then: edge A→D is marked as pruned (enabled=False)
          and pruning is logged with reason "existence_below_threshold"
    """
```

#### TEST-L2-05: Explore weight decays as existence resolves

```python
def test_explore_weight_decay():
    """
    Given: edge C→E at existence_prior=0.5, explore_weight=1.0
    When: existence_probability converges above accept_above threshold (0.90)
    Then: explore_weight has decayed below 0.2
    """
```

---

### 20.4 Level 3 tests — ontology population

These tests verify that the population management layer correctly identifies the true generating structure and discards false ones.

#### TEST-L3-01: True structure becomes dominant

```python
def test_true_structure_dominates():
    """
    Given: population of 5 candidates:
           - cand_true: matches T* exactly
           - cand_spurious_1: T* + edge A→D
           - cand_spurious_2: T* − edge B→D
           - cand_alt: T_alt structure
           - cand_null: single edge C→E only
    When: 500 evidence records from T* are ingested
    Then: cand_true has highest log_score
          cand_true is marked as dominant (active_candidate)
    """
    population = make_population([
        cand_true, cand_spurious_1, cand_spurious_2, cand_alt, cand_null
    ])
    evidence = generator.sample(n=500)
    for batch in chunk(evidence, size=50):
        engine.learn(batch)
    assert engine.population_manager.dominant().candidate_id == cand_true.candidate_id
```

#### TEST-L3-02: Low-scoring candidates are pruned

```python
def test_low_scorers_pruned():
    """
    Given: same 5-candidate population as TEST-L3-01
    When: 500 evidence records from T* are ingested
    Then: cand_null is marked PRUNED (lowest log_score by large margin)
          pruned_at timestamp is set
          pruning_reason is recorded
    """
```

#### TEST-L3-03: Paradigm shift — regime switch detection

```python
def test_paradigm_shift_on_regime_switch():
    """
    This is the most important integration test for Level 3.

    Given: population seeded with T* as dominant (after 300 records from T*)
    When: data generator switches to T_alt regime at record 301
          300 more records are ingested from T_alt
    Then: within 200 records of the switch:
          - a candidate matching T_alt structure rises to dominance
          - the previously dominant T* candidate loses top rank
          - paradigm_shift_count increments in population summary
    """
    # Phase 1: establish T* dominance
    evidence_phase1 = generator.sample(n=300)
    for batch in chunk(evidence_phase1, size=30):
        engine.learn(batch)
    assert engine.population_manager.dominant_matches_structure("T*")

    # Phase 2: switch regime
    generator.switch_regime("T_alt")
    evidence_phase2 = generator.sample(n=300)
    for batch in chunk(evidence_phase2, size=30):
        engine.learn(batch)

    # Allow up to 200 records for detection
    summary = engine.population_manager.summary()
    assert summary["paradigm_shift_count"] >= 1
    # T* should no longer dominate
    assert not engine.population_manager.dominant_matches_structure("T*")
```

#### TEST-L3-04: Variant introduction preserves schema validity

```python
def test_variant_introduction_schema_valid():
    """
    Given: dominant candidate cand_true after learning
    When: PopulationManager introduces N variants of cand_true
    Then: all introduced variants pass schema template validation
          no variant introduces a cycle (DAG constraint preserved)
          all introduced edges are ontology-admissible pairs
    """
```

#### TEST-L3-05: Population size stays bounded

```python
def test_population_size_bounded():
    """
    Given: max_population_size = 5
    When: 20 learning cycles run (each may introduce variants)
    Then: len(active_candidates) never exceeds 5 at any point
    """
```

#### TEST-L3-06: Lineage tracking

```python
def test_candidate_lineage_tracked():
    """
    Given: a new variant is introduced from cand_true
    Then: variant.parent_candidate_id == cand_true.candidate_id
          variant.generation == cand_true.generation + 1
          lineage is recoverable via GET /v1/population/lineage/{id}
    """
```

---

### 20.5 Integration tests — full learning loop

#### TEST-INT-01: End-to-end convergence

```python
def test_end_to_end_convergence():
    """
    The primary integration test. Exercises the full stack:
    domain registration → evidence ingestion → learning →
    population management → inference query → explanation.

    Given: test-domain-v1 registered with 3 initial candidates
           (one matching T*, two with structural variants)
    When: 600 evidence records from T* ingested in batches of 60
    Then:
      1. T* candidate becomes dominant by record 400 at latest
      2. All CPT parameters within 0.10 of ground truth
      3. True edges all have existence_probability > 0.80
      4. Spurious edges all have existence_probability < 0.20
      5. Inference query P(E=true | A=true, B=true) within 0.08
         of analytically computed ground truth value
      6. Explanation response includes active path A→C→E
      7. Snapshot is reproducible: rerunning with same seed
         produces identical parameter_hash and population_state_hash
    """
```

#### TEST-INT-02: API contract compliance

```python
def test_api_contract():
    """
    Given: running FastAPI instance with test-domain-v1
    When: each endpoint is called with valid payloads
    Then: all responses conform to OpenAPI schema
          /v1/inference/query returns posteriors + explanations
            with edge_existence_probabilities present
          /v1/population/status returns structure_entropy,
            dominant_candidate, paradigm_shift_count
          /v1/learning/update returns snapshot with all
            required hash fields populated
    """
```

#### TEST-INT-03: Evidence replay reproducibility

```python
def test_evidence_replay():
    """
    Given: a completed learning run producing snapshot S1
    When: evidence store is replayed from scratch with same seed
    Then: resulting snapshot S2 has:
          S2.parameter_hash == S1.parameter_hash
          S2.population_state_hash == S1.population_state_hash
          S2.graph_hash == S1.graph_hash
    """
```

#### TEST-INT-04: Domain module isolation

```python
def test_domain_isolation():
    """
    Given: two domain modules registered simultaneously
           (test-domain-v1 and market-risk-v1)
    When: evidence is ingested into test-domain-v1
    Then: market-risk-v1 population state is unchanged
          parameter stores are fully isolated
          evidence stores are fully isolated
    """
```

---

### 20.6 Acceptance criteria summary

A passing test suite requires all of the following:

```text
LEVEL 1 — Parameter learning:
  □ TEST-L1-01: single variable posterior within 0.05 of truth after 100 records
  □ TEST-L1-02: full CPT convergence within 0.08 of truth after 500 records
  □ TEST-L1-03: bitwise reproducibility given same seed
  □ TEST-L1-04: CPT convergence within 0.12 with 30% missing data

LEVEL 2 — Edge existence:
  □ TEST-L2-01: true edge existence > 0.85 after 300 records
  □ TEST-L2-02: spurious edge existence < 0.15 after 300 records
  □ TEST-L2-03: existence update trends in correct direction
  □ TEST-L2-04: pruning fires correctly at threshold
  □ TEST-L2-05: explore weight decays as existence resolves

LEVEL 3 — Population:
  □ TEST-L3-01: true structure dominant after 500 records
  □ TEST-L3-02: null candidate pruned
  □ TEST-L3-03: paradigm shift detected within 200 records of regime switch
  □ TEST-L3-04: all introduced variants are schema-valid DAGs
  □ TEST-L3-05: population size never exceeds max
  □ TEST-L3-06: lineage correctly tracked

INTEGRATION:
  □ TEST-INT-01: end-to-end convergence across all metrics
  □ TEST-INT-02: all API endpoints conform to OpenAPI schema
  □ TEST-INT-03: evidence replay produces identical snapshots
  □ TEST-INT-04: domain modules are fully isolated
```

### 20.7 Performance baselines (MVP targets)

```text
Evidence ingestion:         < 50ms per record (SQLite), < 20ms (PostgreSQL)
Inference query (N≤20 vars): < 200ms exact inference
Learning cycle (batch=50):  < 2s including existence update and population scoring
Snapshot write:             < 500ms
Full test suite runtime:    < 5 minutes
```

---

## 21. Build directive block

```text
IMPLEMENTATION_DIRECTIVE:
Build a domain-agnostic probabilistic ontology engine with three-level belief architecture.

Constraints:
- Python 3.12+
- FastAPI service
- Pydantic models for all schema objects including OntologyCandidate and OntologyPopulation
- PostgreSQL-backed metadata/evidence/population store; permit SQLite fallback
- Pluggable graph backend interface; NetworkX for MVP
- Bayesian-network MVP: boolean/categorical variables, DAG only, tabular CPTs
- Edge existence probability tracked per edge, updated via Bayesian marginal likelihood ratio
- Population of 3–5 ontology candidates for MVP; each scored by cumulative log-likelihood
- Candidate introduction: add or remove one schema-valid edge per variant
- Exact inference for small graphs via pgmpy
- Domain module registration from JSON including initial_candidates and existence_thresholds
- Evidence ingestion endpoint
- Posterior query endpoint with explanation output including edge existence probabilities
- Population status endpoint
- Batch learning endpoint: updates CPT parameters, edge existence probabilities, candidate scores,
  prunes low-scoring candidates, introduces variants
- Full test suite implementing all tests in Section 20, including:
    synthetic test-domain-v1 with ground truth graph T* and T_alt
    SyntheticDataGenerator with regime switching support
    Level 1 parameter convergence tests (tests/level1/)
    Level 2 edge existence tests including spurious edge rejection (tests/level2/)
    Level 3 population tests including paradigm shift detection (tests/level3/)
    Integration tests including end-to-end convergence and replay reproducibility (tests/integration/)
- All acceptance criteria in Section 20.6 must pass
- Performance baselines in Section 20.7 must be met

Deliverables:
- Package layout
- Source code
- OpenAPI API
- Sample market-risk domain module with 3 initial candidates
- Synthetic test-domain-v1 module with ground truth T* and T_alt graphs
- SyntheticDataGenerator utility
- Migration scripts
- Full pytest test suite organized by level
- README with run instructions and test execution guide
```
