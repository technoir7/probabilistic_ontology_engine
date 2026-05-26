# Next Steps

Priority order for the next development session.

---

## 1. Get a new NASS API key and run ZC/ZS backfill

The current `NASS_API_KEY` is invalid. Get a new key from:

```text
https://quickstats.nass.usda.gov
```

Then update `.env` and run corn/soybean backfills.

Expected outcome:
- ZC and ZS weekly evidence stores populate with valid NASS-derived agricultural records.
- Evidence geometry should show weekly cadence rather than daily oversampling for new data.
- Agriculture graphs should be evaluated after valid weekly NASS evidence exists.

---

## 2. Run longer MR backfills periodically to accumulate shift history

MR has a 730-day backfill completed and FRED is working through ProtonVPN.

Keep running longer periodic MR backfills while the paradigm-shift event log matures. This gives the frontend `ParadigmShiftTimeline` more real events to display and gives the ontology population more regime transitions to score.

Operational note: ProtonVPN must be active for FRED API calls.

---

## 3. TemplateRules not implemented in `_derive_admissible_edges`

`_derive_admissible_edges` still admits broad all-pairs candidate edges.

This is acceptable for experimentation, but real domains need TemplateRules or domain-level admissibility constraints so variants do not explore impossible causal directions.

Examples:
- price should not cause planting delay
- unemployment should not retroactively cause past CPI
- exogenous macro state variables may need directional constraints

---

## 4. API regression tests: `tests/integration/test_api.py` not written

Many endpoint-specific tests exist, but there is still no consolidated API regression file.

Add `tests/integration/test_api.py` covering:
- route schema shape
- domain map for `mr`, `ng`, `zc`, `zs`
- population status
- candidates
- inference query fuzzy target resolution
- lineage cross-domain fallback
- shifts endpoint
- evidence recent
- debug endpoints
- unknown domain errors

---

## 5. ParameterStore: save on `learn()` only

Parameter persistence exists, but it is still tied to learn/update cycles rather than continuous flushing.

Risk:
- a process crash between state changes and persistence can lose newest CPT count changes.

Potential fix:
- make save semantics explicit at the end of every successful `learn()` cycle
- add a crash/restart regression around partially completed learn cycles

---

## 6. Inference aggregation uses raw `log_score`, not BIC-corrected score

`InferenceService` still uses raw `log_score` in aggregation paths.

Population management ranks with BIC-corrected average score. This mismatch can overweight candidates that have accumulated raw likelihood differently from the BIC-corrected population ranking.

Fix direction:
- expose a population scoring helper
- use the same score basis for inference aggregation and candidate ranking
- add tests where raw score and BIC-corrected score disagree

---

## 7. Frontend lineage timeline is still sparse

`ParadigmShiftTimeline` is wired to the live shifts endpoint, but history only accumulates going forward from when the event log exists.

Options:
- accept sparsity until enough live/backfilled shifts accumulate
- reconstruct historical shifts from score history if feasible
- annotate UI when the shift log starts after the evidence window

---

## 8. Consider 1095-day MR backfill

Run a 1095-day, three-year MR backfill to capture the 2022 tightening cycle more fully.

Why:
- 730 days gives a useful recent window.
- 1095 days should cover a fuller tightening/regime-shift arc.
- More shift history should make MR a better flagship demo for ontology evolution.

Requirement: ProtonVPN active and `FRED_API_KEY` valid.
