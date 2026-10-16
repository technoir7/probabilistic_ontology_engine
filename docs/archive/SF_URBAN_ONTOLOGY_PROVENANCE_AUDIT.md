# SF Urban Ontology Provenance Audit

**Date**: 2026-05-31  
**Auditor**: Code analysis (no inference)  
**Status**: Complete

---

## Executive Verdict

**SF Urban is primarily a STRUCTURE-LEARNING domain.**

All 8 ontology variables are hand-authored, apriori, and fixed. The engine learns edge probabilities and explores alternative edge structures between these fixed concepts, but performs **zero concept induction, discovery, or generation**.

---

## Concept Provenance Table

| Concept | Origin Type | Source File | Lines | Data Source | Assignment Method |
|---------|-------------|-------------|-------|-------------|-------------------|
| TechHiringAccelerating | A (hand-authored/apriori) | domain.py | 12-14 | FRED SANF806INFO | YoY z-score → sigmoid |
| OfficeVacancyFalling | A (hand-authored/apriori) | domain.py | 16-18 | SF permits (commercial fraction) | Inverted z-score → sigmoid |
| RetailClosureElevated | A (hand-authored/apriori) | domain.py | 20-22 | SF business registrations (expirations) | Monthly z-score → sigmoid |
| PermitActivityRising | A (hand-authored/apriori) | domain.py | 24-26 | SF building permits (total count) | Monthly z-score → sigmoid |
| CrimeIndexElevated | A (hand-authored/apriori) | domain.py | 28-30 | SF police incidents | Monthly z-score → sigmoid |
| StartupFormationRising | A (hand-authored/apriori) | domain.py | 32-34 | SF business registrations (new registrations) | Monthly z-score → sigmoid |
| FootTrafficRecovering | A (hand-authored/apriori) | domain.py | 36-38 | FRED SANF806LEIH | YoY z-score → sigmoid |
| PopulationFlowPositive | A (hand-authored/apriori) | domain.py | 40-42 | FRED SANF806NA | YoY z-score → sigmoid |

---

## Complete Evidence Path: Each Concept

### 1. TechHiringAccelerating

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:12-14`
- **Type**: Hand-authored Boolean variable
- **ID**: Stable UUID via `stable_variable_id("sf-urban-v1", "TechHiringAccelerating")`

**Raw Data Source**:
```
FRED API
  └─ Series: SANF806INFO
  └─ Meaning: All Employees: Information in SF-Oakland-Fremont, CA (thousands)
  └─ Frequency: Monthly, seasonally adjusted
  └─ Source File: src/domains/sf_urban_v1/ingestion/fred_client.py:32
```

**Assignment Logic**:
```
Raw FRED observations (monthly employment levels)
  ↓
FRED Client fetches 24-month history [src/domains/sf_urban_v1/ingestion/fred_client.py:79-148]
  ↓
Pipeline computes YoY (year-over-year) percentage change [pipeline.py:152-179]
  ↓
YoY change is z-scored against historical YoY changes [pipeline.py:152-179]
  ↓
Z-score passed through sigmoid(x) → [0, 1] probability [pipeline.py:99-103]
  ↓
Clamped to [0.01, 0.99] [pipeline.py:61-62]
  ↓
Result stored as p_tech_hiring_accelerating, thresholded at 0.5 for Boolean [pipeline.py:186-188, 307-309]
  ↓
ObservedAssignment with SOFT_OBSERVED missingness [pipeline.py:388-396]
```

**Function Implementations**:
- Fetch: `FREDClient.fetch_series()` [fred_client.py:79-148]
- Compute: `_compute_tech_hiring()` [pipeline.py:186-188]
- Aggregate: `_fred_yoy_zscore()` [pipeline.py:152-179]
- Apply: `compute_snapshot()` [pipeline.py:320-322]
- Build Evidence: `build_evidence_record()` [pipeline.py:398]

**When was it created?**
- **Commit**: 0a41892a "now has crypto, geopolitics, and sf urban"
- **Date**: 2026-05-27 06:22 UTC
- **Before first evidence**: YES — variable definition predates domain registration and ingestion
- **Evidence record count**: 8 (from 8-week backfill spanning 2026-04-03 to 2026-05-22)

**Is this variable induced or discovered?**
- NO. Explicitly hand-authored in domain definition.
- Described in docstring at domain.py:12-14.
- No LLM involvement.
- No unsupervised variable discovery.

---

### 2. OfficeVacancyFalling

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:16-18`
- **Type**: Hand-authored Boolean variable (inverted signal)

**Raw Data Source**:
```
SF Open Data (Socrata) — Building Permits
  └─ Dataset: i98e-djp9
  └─ Meaning: Permit applications with permit_type, filed_date
  └─ Transformation: Extract permit_type, classify as commercial/office vs. other
  └─ Source File: pipeline.py:191-233
```

**Assignment Logic**:
```
Raw permit records (filed_date, permit_type)
  ↓
Group by year-month [pipeline.py:210-214]
  ↓
Classify permit as commercial if permit_type matches keywords:
  {"commercial", "office", "tenant improvement", "ti", "t.i.", "commercial alteration"}
  [pipeline.py:199-204]
  ↓
Compute monthly fraction: commercial_count / total_count [pipeline.py:220-226]
  ↓
Z-score current fraction against recent months [pipeline.py:232]
  ↓
INVERT: rising commercial fraction = vacancy falling = positive signal [pipeline.py:191]
  ↓
Sigmoid transform → [0, 1] probability [pipeline.py:307-309]
  ↓
Result stored as p_office_vacancy_falling [pipeline.py:325-326]
```

**Function Implementations**:
- Fetch: `SFGovClient.fetch_all()` [sfgov_client.py]
- Compute: `_compute_office_vacancy_falling()` [pipeline.py:191-233]
- Apply: `compute_snapshot()` [pipeline.py:324-326]

**When was it created?**
- Same commit and date as TechHiringAccelerating (2026-05-27)
- Before first evidence: YES

---

### 3. RetailClosureElevated

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:20-22`

**Raw Data Source**:
```
SF Open Data (Socrata) — Active Businesses
  └─ Dataset: g8m3-pdis
  └─ Meaning: Business registrations with location_start_date, location_end_date
  └─ Signal: End dates = business closures/expirations
  └─ Source File: pipeline.py:236-247
```

**Assignment Logic**:
```
Raw business records (location_end_date)
  ↓
Extract closure dates (non-null location_end_date) [pipeline.py:238-241]
  ↓
Group by year-month [pipeline.py:134-149]
  ↓
Compute z-score of most recent month's closures vs. preceding 12 months [pipeline.py:134-149]
  ↓
Sigmoid transform → [0, 1] probability [pipeline.py:307-309]
  ↓
Result stored as p_retail_closure_elevated [pipeline.py:329-330]
```

**When was it created?**
- 2026-05-27 (same as all variables)
- Before first evidence: YES

---

### 4. PermitActivityRising

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:24-26`

**Raw Data Source**:
```
SF Open Data (Socrata) — Building Permits
  └─ Dataset: i98e-djp9
  └─ Signal: Total permit count (all types) by month
  └─ Source File: pipeline.py:250-258
```

**Assignment Logic**:
```
Raw permit records (filed_date)
  ↓
Group by year-month [pipeline.py:254]
  ↓
Count permits per month [pipeline.py:255]
  ↓
Z-score recent month vs. 12-month history [pipeline.py:255]
  ↓
Sigmoid transform → [0, 1] probability
  ↓
Result stored as p_permit_activity_rising [pipeline.py:333-334]
```

---

### 5. CrimeIndexElevated

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:28-30`

**Raw Data Source**:
```
SF Open Data (Socrata) — Police Incidents
  └─ Dataset: wg3w-h783
  └─ Signal: Incident count by month
  └─ Source File: pipeline.py:261-269
```

**Assignment Logic**:
```
Raw incident records (incident_date)
  ↓
Group by year-month [pipeline.py:265]
  ↓
Count incidents per month [pipeline.py:266]
  ↓
Z-score recent month vs. 12-month history
  ↓
Sigmoid transform → [0, 1] probability
  ↓
Result stored as p_crime_index_elevated [pipeline.py:337-338]
```

---

### 6. StartupFormationRising

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:32-34`

**Raw Data Source**:
```
SF Open Data (Socrata) — Active Businesses
  └─ Dataset: g8m3-pdis
  └─ Signal: New business registrations (location_start_date)
  └─ Source File: pipeline.py:272-280
```

**Assignment Logic**:
```
Raw business records (location_start_date)
  ↓
Extract startup dates [pipeline.py:274]
  ↓
Group by year-month [pipeline.py:277]
  ↓
Count new registrations per month [pipeline.py:277]
  ↓
Z-score recent month vs. 12-month history [pipeline.py:277]
  ↓
Sigmoid transform → [0, 1] probability
  ↓
Result stored as p_startup_formation_rising [pipeline.py:341-342]
```

---

### 7. FootTrafficRecovering

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:36-38`

**Raw Data Source**:
```
FRED API
  └─ Series: SANF806LEIH
  └─ Meaning: All Employees: Leisure and Hospitality in SF-Oakland-Fremont, CA (thousands)
  └─ Frequency: Monthly, seasonally adjusted
  └─ Proxy: Foot traffic via consumer-facing employment
  └─ Source File: fred_client.py:33
```

**Assignment Logic**:
```
Same as TechHiringAccelerating:
FRED series (monthly employment)
  ↓
YoY percentage change z-scored against historical YoY changes [pipeline.py:283-285]
  ↓
Sigmoid transform → [0, 1] probability
  ↓
Result stored as p_foot_traffic_recovering [pipeline.py:345-346]
```

---

### 8. PopulationFlowPositive

**Definition**:
- **File**: `src/domains/sf_urban_v1/domain.py:40-42`

**Raw Data Source**:
```
FRED API
  └─ Series: SANF806NA
  └─ Meaning: All Employees: Total Nonfarm in SF-Oakland-Fremont, CA (thousands)
  └─ Frequency: Monthly, seasonally adjusted
  └─ Proxy: Population flow via total employment
  └─ Source File: fred_client.py:34
```

**Assignment Logic**:
```
Same as TechHiringAccelerating and FootTrafficRecovering:
FRED series (monthly employment)
  ↓
YoY percentage change z-scored against historical YoY changes [pipeline.py:288-290]
  ↓
Sigmoid transform → [0, 1] probability
  ↓
Result stored as p_population_flow_positive [pipeline.py:349-350]
```

---

## Dynamic Ontology Audit: What is Actually Learned?

### Question 1: Does SF Urban perform concept induction?

**Answer: NO**

**Evidence**:
- No new variables are created at runtime
- `PopulationManager.introduce_variants()` [population_manager.py:215-389] **ONLY modifies edges**:
  - Line 300: `strategy = self.rng.choice(["add", "remove"])`
  - Line 338-359: Can ADD edges between existing variables
  - Line 361-371: Can REMOVE edges from existing structure
  - **CRITICAL LINE 382**: `variables=parent.variables` — variants inherit parent's variable set unchanged
- No method in the codebase creates new Variable objects after domain initialization
- `get_variables()` in domain.py always returns the same 8 variables (lines 90-98)

---

### Question 2: Does SF Urban perform ontology discovery?

**Answer: NO**

**Evidence**:
- No graph or variable discovery algorithm exists
- Codebase search for "discovery", "induce", "induce_concept" returns zero results in sf_urban_v1
- All variables are registered at domain initialization time [domain.py:79-88, 90-98]
- All variables are BOOLEAN type (line 94: `domain_type=DomainType.BOOLEAN`)
- No runtime class instantiation for variables (variables are frozen at module load time)

---

### Question 3: Does SF Urban generate new concepts at runtime?

**Answer: NO**

**Evidence**:
- Initial candidates defined statically in domain.py (lines 141-301)
- Each candidate references the same variable set: `variables=_var_list()` (lines 157, 186, 215, 244, 270)
- Variant generation only adds/removes edges (line 300)
- No candidate ever has different variables than the original seed candidates
- Variables are immutable after initialization (no Variable constructor called in pipeline or learning services)

---

### Question 4: If not, what exactly is being learned?

**Answer: Edge existence probabilities and structure.**

**What IS learned:**
1. **Edge existence probabilities** via `LearningService.accumulate()` [learning.py:54-100+]
   - Maintains conditional probability tables (CPTs) for each variable given its parents
   - Updates CPT counts as evidence is ingested
   - Computes posterior edge probabilities via BIC-corrected log-likelihood

2. **Structural variants** via `PopulationManager.introduce_variants()` [population_manager.py:215-389]
   - Proposes edge additions/removals between fixed variables
   - Maintains a population of competing structures
   - Scores structures via log-likelihood (BIC-corrected)
   - Prunes low-scoring structures, keeps high-scoring ones

3. **Dominant hypothesis** via `PopulationManager.dominant()` [population_manager.py:98-104]
   - Tracks which edge structure is currently highest-scoring
   - Updates when a new structure outperforms all active candidates

**What is NOT learned:**
- No new variables
- No new variable types
- No new classes of variables
- No new domains
- No new data modalities

---

## Architecture Classification

### SF Urban vs. Other Domains

**SF Urban (STRUCTURE-LEARNING)**
- Fixed variables: 8 (all hand-authored)
- Fixed variable types: BOOLEAN only
- Learned elements: Edge structure, edge probabilities
- Concept discovery: NONE
- Variable induction: NONE
- Baseline: 5 seed candidates with manually-designed causal structures
- Exploration: Add/remove edges between existing variables only

**Macro Regime (STRUCTURE-LEARNING, similar architecture)**
- Fixed variables: 8 (all hand-authored)
- Fixed variable types: BOOLEAN only
- Learned elements: Edge structure, edge probabilities
- Concept discovery: NONE
- Variable induction: NONE
- Baseline: 5 seed candidates with manually-designed causal structures
- Exploration: Add/remove edges between existing variables only

**Art Market / POE-A (HYPOTHETICAL DYNAMIC ONTOLOGY)**
- Would have concept induction, variable discovery
- Would generate new variables at runtime
- Would maintain a dynamic variable set
- Implementation: NOT FOUND in this codebase (may exist elsewhere)

**Summary**: SF Urban and Macro Regime follow the SAME architecture: fixed concepts, learned structures.

---

## Repository-Wide Search Results

### Query 1: Concept Induction
```bash
grep -r "class.*Induction\|def.*induct\|induce_concept" src/
```
**Result**: ZERO matches (except in comments/docs)

### Query 2: Ontology Discovery
```bash
grep -r "ontology.*discover\|discover.*concept\|discovery" src/engine/
```
**Result**: ZERO matches in code

### Query 3: Dynamic Ontology
```bash
grep -r "dynamic.*ontolog\|canon.*concept\|induced.*concept" src/
```
**Result**: ZERO matches (only comments refer to "canonical")

### Query 4: Concept Generation
```bash
grep -r "class Variable\|new Variable\|Variable(" src/engine/
```
**Result**: All Variable construction happens in domain.py at module load time, zero at runtime

---

## Exact Code Citations

### Where concepts are defined (immutable):

**File**: `src/domains/sf_urban_v1/domain.py`

```python
# Lines 79-88: Canonical variable names
_VAR_NAMES = [
    "TechHiringAccelerating",
    "OfficeVacancyFalling",
    "RetailClosureElevated",
    "PermitActivityRising",
    "CrimeIndexElevated",
    "StartupFormationRising",
    "FootTrafficRecovering",
    "PopulationFlowPositive",
]

# Lines 90-98: Variable definitions (frozen at module load)
_VARIABLE_DEFS: dict[str, Variable] = {
    name: Variable(
        variable_id=stable_variable_id(_MODULE_ID, name),
        name=name,
        domain_type=DomainType.BOOLEAN,
        support=[True, False],
    )
    for name in _VAR_NAMES
}
```

### Where concepts are assigned evidence:

**File**: `src/domains/sf_urban_v1/ingestion/pipeline.py`

```python
# Lines 297-353: compute_snapshot() assigns values to all 8 variables
def compute_snapshot(sfgov_data, fred_data, target_date):
    snap = SFUrbanSnapshot(target_date=target_date)
    # ... (8 _apply() calls, one per variable) ...
    # Line 320: TechHiringAccelerating
    # Line 324: OfficeVacancyFalling
    # ... etc
```

### Where structures (edges) are learned:

**File**: `src/engine/services/population_manager.py`

```python
# Line 215-225: introduce_variants() creates edge variants
def introduce_variants(self, domain_module_id, learning_service=None):
    """
    Introduce new candidates as variants of the top survivors.
    Variants are: add one edge OR remove one edge.
    """
    # Line 300: only decision point
    strategy = self.rng.choice(["add", "remove"])

    # Line 382: CRITICAL — variables do NOT change
    variant = OntologyCandidate(
        ...
        variables=parent.variables,  # <-- IMMUTABLE
        edges=variant_edges,         # <-- MUTABLE
        ...
    )
```

---

## Final Determination

### SF Urban is a **STRUCTURE-LEARNING DOMAIN**.

| Aspect | Status | Code Evidence |
|--------|--------|----------------|
| **Fixed concepts** | YES | domain.py:79-98 (immutable _VAR_NAMES, _VARIABLE_DEFS) |
| **Hand-authored variables** | YES | domain.py:12-42 (docstring describes each variable) |
| **Runtime variable induction** | NO | population_manager.py:382 (`variables=parent.variables`) |
| **Dynamic concept discovery** | NO | Zero results for "induce", "discover" in sf_urban_v1/ |
| **Learned edge structure** | YES | population_manager.py:215-389 (add/remove edges) |
| **Learned edge probabilities** | YES | learning.py:54-100+ (accumulate CPT counts) |
| **LLM-based concept generation** | NO | Zero OpenAI/Anthropic/Claude imports in sf_urban_v1/ |
| **Apriori seed hypotheses** | YES | domain.py:141-301 (5 hand-designed candidates) |

---

## Conclusion

SF Urban's entire ontology is **hand-authored, apriori, and immutable**. The system learns which relationships (edges) exist between these fixed concepts, not what the concepts themselves are. This is fundamentally a **structure-learning problem**, not a **concept-discovery problem**.

All 8 variables are defined in `/src/domains/sf_urban_v1/domain.py` and never change. Evidence assignment logic is deterministic (raw data → z-score → sigmoid). The engine's learning loop optimizes edge probabilities and explores alternative edge structures, but operates within the boundary of these 8 fixed Boolean variables at all times.
