# Export Narrative Snapshot Mode Bug Audit

**Date**: 2026-05-30  
**Repository**: probabilistic_ontology_engine  
**Endpoint**: `GET /v1/export/narrative-snapshot`  
**Status**: Root cause identified, fix design required

---

## Executive Summary

The `/v1/export/narrative-snapshot` endpoint **ignores the `ontology_mode` query parameter** and always returns apriori (old POE) data, even when `ontology_mode=dynamic` is requested.

**Verdict**: **A. Export endpoint ignores ontology_mode** (parameter not parsed in function signature)

---

## Root Cause Analysis

### 1. Request Handler
- **File**: `src/engine/api/app.py`
- **Line**: 1706
- **Function**: `narrative_snapshot()`

### 2. Function Signature (THE BUG)

```python
@app.get("/v1/export/narrative-snapshot", response_model=NarrativeSnapshotOut)
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
```

**Problem**: The function signature declares only `domain` as a query parameter. It does NOT declare `ontology_mode`.

When a client sends: `GET /v1/export/narrative-snapshot?domain=art&ontology_mode=dynamic`

FastAPI:
- Parses `domain=art` ✓ (matches declared parameter)
- Ignores `ontology_mode=dynamic` ✗ (not in signature)
- Calls `narrative_snapshot(domain="art")`

### 3. Comparison: Correct Pattern

Other endpoints that properly support `ontology_mode`:

```python
# /v1/population/candidates (CORRECT)
@app.get("/v1/population/candidates", response_model=CandidatesOut)
async def population_candidates(
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),  # ← PRESENT
) -> CandidatesOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_candidates(display_name)
        if data is not None:
            return CandidatesOut.model_validate(data)
    # ... rest of apriori implementation ...
```

### 4. Mode Dispatch: MISSING

The `narrative_snapshot` function contains **no dispatch logic**. It immediately resolves to the old POE backend:

```python
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
    """..."""
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    pop = engine.get_population(domain_id)
    # All subsequent lines build from old POE: engine, pop, inference_service, etc.
```

There is no check for `ontology_mode == "dynamic"`.

### 5. Data Source Selection

**What actually happens** (apriori-only):
- Line 1714: `engine, domain_id, display_name = _resolve_domain(domain, app.state)`
- Line 1715: `pop = engine.get_population(domain_id)` — loads old POE population
- Line 1721: `evidence_count = engine.evidence_store.count(domain_id)` — queries old POE evidence store
- Line 1752: `engine.inference_service.query(iq, pop)` — runs old POE inference
- Line 1836: `engine.population_store.load_shift_events(domain_id)` — loads old POE shift events
- Line 1857: `thresholds = engine._modules[domain_id].existence_thresholds()` — old POE thresholds

**What should happen** (dynamic mode):
- Would need to load POE-A artifacts from `poea_dynamic._load_graph()`, etc.
- Would need POE-A snapshot builder function (currently does not exist)
- Would dispatch via `poea_dynamic.build_narrative_snapshot(display_name, domain_id)`

### 6. POE-A Builder Function Status

Checked `src/engine/api/poea_dynamic.py` for snapshot builder:

**Existing public builders**:
- ✓ `build_population_status(display_name)`
- ✓ `build_candidates(display_name)`
- ✓ `build_inference(target_variable)`
- ✓ `build_lineage(candidate_id, display_name)`
- ✓ `build_shifts(display_name, domain_module_id)` — returns empty for POE-A
- ✓ `build_recent_evidence(display_name, limit)`

**Missing**:
- ✗ `build_narrative_snapshot()` — **DOES NOT EXIST**

---

## Execution Path Comparison

### Current (Broken) Behavior

```
Client: GET /v1/export/narrative-snapshot?domain=art&ontology_mode=dynamic

FastAPI URL parsing:
  ↓ domain="art" (parsed)
  ↓ ontology_mode="dynamic" (IGNORED — not in signature)

narrative_snapshot(domain="art")
  ↓ _resolve_domain("art", app.state) → old POE engine
  ↓ engine.get_population(domain_id) → old POE population
  ↓ pop.dominant() → old POE candidates
  ↓ engine.inference_service.query() → old POE posterior inference
  ↓ engine.population_store.load_shift_events() → old POE shift history
  ↓ engine._modules[domain_id].existence_thresholds() → old POE thresholds

Return: NarrativeSnapshotOut
  ├─ metadata: old POE evidence_count, generation
  ├─ current_regime_state: old POE variables + posteriors
  ├─ dominant_hypothesis: old POE edges
  ├─ competing_candidates: old POE candidates
  ├─ ontology_competition: old POE entropy, shifts
  └─ frontier: old POE frontier edges

Result: APRIORI data returned regardless of requested mode ✗
```

### Expected (Correct) Behavior

```
Client: GET /v1/export/narrative-snapshot?domain=art&ontology_mode=dynamic

FastAPI URL parsing:
  ↓ domain="art" (parsed)
  ↓ ontology_mode="dynamic" (parsed)

narrative_snapshot(domain="art", ontology_mode="dynamic")
  ↓ if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available("art"):
  ↓     data = poea_dynamic.build_narrative_snapshot(display_name, domain_id)
  ↓     if data is not None:
  ↓         return NarrativeSnapshotOut.model_validate(data)
  ↓ (fallthrough to apriori for other domains)
  
  poea_dynamic.build_narrative_snapshot():
    ├─ _load_graph() → poea_graph.json (POE-A candidates, edges, metadata)
    ├─ _load_canonical_concepts() → canonical_concepts.json (POE-A variables)
    ├─ _load_scored_evidence() → scored_evidence.json (POE-A assignments)
    └─ Construct NarrativeSnapshotOut from POE-A artifacts

Result: DYNAMIC data returned when requested ✓
```

---

## Why Both Requests Return Identical Output

| Aspect | GET with ontology_mode=dynamic | GET with ontology_mode=apriori |
|--------|--------|--------|
| Query param in URL | `?domain=art&ontology_mode=dynamic` | `?domain=art&ontology_mode=apriori` |
| Function signature accepts param | ✗ NO | ✗ NO |
| FastAPI parses & passes param | ✗ NO | ✗ NO |
| Function receives ontology_mode | ✗ NO | ✗ NO |
| Data source loaded | old POE engine | old POE engine |
| Snapshot built from | old POE data | old POE data |
| Response identical | **YES** | **YES** |

---

## Evidence: Proof of Ignored Parameter

### How we know ontology_mode is ignored:

1. **User observation**: Both requests return identical apriori-looking output
   - `dynamic` request returns generation=0, old POE hypothesis names (H1, H2, ...) not POE-A names
   - `apriori` request returns generation=0, same old POE hypothesis names
   - `evidence_count` is from old POE store, not from POE-A

2. **Code inspection**: Function signature does not declare `ontology_mode`
   - Other endpoints (candidates, shifts, status) DO declare it
   - narrative_snapshot does NOT

3. **No dispatch logic exists**
   - Other endpoints have: `if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(...)`
   - narrative_snapshot has: no such check

4. **No POE-A builder exists**
   - poea_dynamic.py has 6 public `build_*` functions
   - None of them are for narrative snapshots
   - build_shifts() explicitly returns empty (apriori-only data)

---

## Minimal Fix Required

This is **NOT a small, obvious, localized fix**. It requires two interdependent changes:

### Fix Part 1: Add Parameter & Dispatch (Small)
**File**: `src/engine/api/app.py`, line 1707  
**Change**: ~4 lines

```python
# CURRENT:
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
    """..."""
    engine, domain_id, display_name = _resolve_domain(domain, app.state)

# PROPOSED:
async def narrative_snapshot(
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> NarrativeSnapshotOut:
    """..."""
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_narrative_snapshot(display_name, domain_id)
        if data is not None:
            return NarrativeSnapshotOut.model_validate(data)
    
    # ... rest of apriori implementation (unchanged) ...
```

### Fix Part 2: Create Dynamic Snapshot Builder (Medium)
**File**: `src/engine/api/poea_dynamic.py`  
**Add**: `build_narrative_snapshot(display_name: str, domain_id: str) -> dict[str, Any] | None`

This function must construct a `NarrativeSnapshotOut`-compatible dict from:
- `poea_graph.json` — candidates, edges, metadata
- `canonical_concepts.json` — variables
- `scored_evidence.json` — assignment data
- Internal POE-A data structures

The builder would need to map:
```
NarrativeSnapshotOut fields:
├─ metadata → from poea_graph.metadata + scored_evidence.metadata
├─ current_regime_state → from canonical_concepts + candidate confidence
├─ dominant_hypothesis → from poea_graph.candidate_summaries[0] + edges
├─ competing_candidates → from poea_graph.candidate_summaries[1:]
├─ ontology_competition → from entropy calculation + no shifts (POE-A doesn't generate shifts)
├─ frontier → from edges in explore band [0.3, 0.7]
└─ interpretation_hints → generated dynamically
```

---

## Why Fix Part 2 is Non-Trivial

1. **Data structure mapping**: POE-A artifacts must be transformed into old POE model representations
2. **Threshold calculation**: Frontier edge band (explore_lo, explore_hi) needs definition for POE-A
3. **Inference analogues**: Regime state probabilities — POE-A doesn't compute posteriors; need confidence scores or direct assignment data
4. **Entropy calculation**: Already exists in poea_dynamic as `_compute_entropy()`; can reuse
5. **Testing**: New builder must be tested against both domains (art dynamic + art apriori fallback)

---

## Classification

| Criterion | Assessment |
|-----------|-----------|
| Size | Medium (4 lines + ~150 lines) |
| Architectural impact | Localized to export endpoint + dynamic builder |
| Risk | Low (read-only dispatch, new code path) |
| Certainty | High (clear pattern from other endpoints) |
| Testing burden | Medium (new function + endpoint + regression test) |

---

## Recommendation

**Do NOT implement without design approval.**

While the fix is structurally clear and follows the existing pattern, creating `build_narrative_snapshot()` requires:
1. Reverse-engineering POE-A artifact layout to match `NarrativeSnapshotOut`
2. Defining sensible POE-A analogues for old POE concepts (posteriors, shifts, thresholds)
3. Testing edge cases (missing artifacts, empty candidates, no evidence)

**Required before implementation**:
- [ ] Design: How should POE-A map to NarrativeSnapshotOut fields?
- [ ] Threshold definition: What are explore_lo/explore_hi for POE-A edges?
- [ ] Confidence mapping: Should regime_state use candidate confidence or assignment confidence?
- [ ] Empty state: How to handle when poea_graph.json is missing/empty?
- [ ] Test plan: coverage for both dynamic and apriori modes

---

## Files Affected

| File | Lines | Change |
|------|-------|--------|
| `src/engine/api/app.py` | 1707–1710 | Add ontology_mode param + dispatch (4 lines) |
| `src/engine/api/poea_dynamic.py` | end of file | Add build_narrative_snapshot (~150 lines) |
| `tests/integration/test_api_*.py` | new | Test both modes return different data |

---

## Appendix: Data Source References

### Old POE Data Sources (Always Used Now)
- `engine.get_population(domain_id)` → old POE Bayesian network population
- `engine.evidence_store.count(domain_id)` → PostgreSQL evidence table
- `engine.inference_service.query()` → pgmpy VariableElimination posterior
- `engine.population_store.load_shift_events()` → SQLite paradigm_shifts table
- `engine._modules[domain_id].existence_thresholds()` → old POE config thresholds

### POE-A Data Sources (Never Used Now)
- `poea_dynamic._load_graph()` → poea_graph.json (candidates, edges, metadata)
- `poea_dynamic._load_canonical_concepts()` → canonical_concepts.json (variable registry)
- `poea_dynamic._load_scored_evidence()` → scored_evidence.json (assignment records)
- `poea_dynamic._load_evidence()` → evidence.json (raw evidence units)
