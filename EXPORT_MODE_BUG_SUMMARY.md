# Export Narrative Snapshot: Mode Bug Summary

**Status**: Root cause identified | Design approval needed before implementation

---

## The Bug

Both of these requests return **identical apriori (old POE) data**:

```bash
GET /v1/export/narrative-snapshot?domain=art&ontology_mode=dynamic
GET /v1/export/narrative-snapshot?domain=art&ontology_mode=apriori
```

Expected: `dynamic` returns POE-A snapshot, `apriori` returns old POE snapshot.  
Actual: Both return old POE snapshot.

---

## Root Cause: Missing Parameter

The function signature does NOT declare `ontology_mode`:

```python
# BROKEN (current)
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
```

Compare with working endpoint:

```python
# CORRECT (population_candidates)
async def population_candidates(
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),  # ← PRESENT
) -> CandidatesOut:
```

**Result**: When clients send `?ontology_mode=dynamic`, FastAPI ignores it because it's not in the declared signature.

---

## Why This Happens

FastAPI URL query parameter parsing is **strict**: it only parses parameters that are declared in the function signature. Unknown parameters are silently discarded.

| Request | Parsed | Ignored |
|---------|--------|---------|
| `?domain=art&ontology_mode=dynamic` | `domain` | `ontology_mode` |
| `?domain=art&ontology_mode=apriori` | `domain` | `ontology_mode` |

Both calls execute identically: `narrative_snapshot(domain="art")` with no mode parameter.

---

## Proof

### Parameter Signature Analysis

```python
# narrative_snapshot (BROKEN)
Parameters: ['domain']
Missing: 'ontology_mode'

# population_candidates (CORRECT)  
Parameters: ['domain', 'ontology_mode']
Default: ontology_mode='apriori'
```

### Dispatch Logic

**narrative_snapshot**: No dispatch for dynamic mode
```python
async def narrative_snapshot(domain: str = Query("ng")) -> NarrativeSnapshotOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    pop = engine.get_population(domain_id)  # ← Always old POE
    # ... rest always uses old POE ...
```

**population_candidates**: Has dynamic dispatch
```python
async def population_candidates(
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),
) -> CandidatesOut:
    engine, domain_id, display_name = _resolve_domain(domain, app.state)
    if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
        data = poea_dynamic.build_candidates(display_name)
        if data is not None:
            return CandidatesOut.model_validate(data)
    # ... fallthrough to apriori ...
```

---

## What Needs to Happen

### Step 1: Add Parameter (Simple ✓)
```python
async def narrative_snapshot(
    domain: str = Query("ng"),
    ontology_mode: str = Query("apriori"),  # ← ADD THIS
) -> NarrativeSnapshotOut:
```

### Step 2: Add Dispatch (Simple ✓)
```python
if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(domain.lower()):
    data = poea_dynamic.build_narrative_snapshot(display_name, domain_id)  # ← CALL THIS
    if data is not None:
        return NarrativeSnapshotOut.model_validate(data)
# fallthrough to apriori (unchanged)
```

### Step 3: Create Builder (Medium ⚠)
Add to `src/engine/api/poea_dynamic.py`:
```python
def build_narrative_snapshot(display_name: str, domain_id: str) -> dict[str, Any] | None:
    """Build NarrativeSnapshotOut from POE-A artifacts."""
    # Load POE-A artifacts
    graph = _load_graph()
    concepts = _load_canonical_concepts()
    scored = _load_scored_evidence()
    
    if not graph:
        return None
    
    # Construct NarrativeSnapshotOut dict from POE-A data
    # ... ~150 lines ...
```

---

## Implementation Status

| Part | Complexity | Certainty | Status |
|------|-----------|-----------|--------|
| Add parameter + dispatch | Simple | High | Ready to implement |
| Create snapshot builder | Medium | Medium | Requires design decisions |

**Blocker**: The builder function requires design approval on:
- How to map POE-A artifacts to `NarrativeSnapshotOut` fields
- How to compute regime state probabilities (POE-A doesn't run inference)
- How to represent competing candidates (POE-A is deterministic)
- Edge explore band thresholds for POE-A

**Cannot proceed without approval on these design questions.**

---

## Files & Locations

| File | Line(s) | Change | Complexity |
|------|---------|--------|-----------|
| `src/engine/api/app.py` | 1706–1714 | Add ontology_mode param, add dispatch | 4 lines |
| `src/engine/api/poea_dynamic.py` | EOF | Add build_narrative_snapshot() | ~150 lines |
| `tests/integration/` | new | Test dynamic vs apriori returns different data | new test |

---

## Next Steps

1. ✅ Root cause documented in `EXPORT_MODE_BUG_AUDIT.md`
2. ⏸ Design discussion: How should POE-A map to NarrativeSnapshotOut?
3. ⏸ Implementation: Awaiting design approval
4. ⏸ Testing: Add regression test for mode dispatch

**See `EXPORT_MODE_BUG_AUDIT.md` for complete analysis and proposed changes.**
