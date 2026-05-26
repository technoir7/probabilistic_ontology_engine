# Next Steps

Priority order for the next development session.

---

## 1. Run ZC/ZS backfill with VPN active

NASS API access is blocked by IP, the same class of issue as FRED. ProtonVPN Switzerland resolves it.

Run corn and soybean backfills with ProtonVPN Switzerland active.

Expected outcome:
- ZC and ZS weekly evidence stores populate with valid NASS-derived agricultural records.
- Evidence geometry should show weekly cadence rather than daily oversampling for new data.
- Agriculture graphs can then be evaluated against meaningful weekly state transitions.

---

## 2. Add sovereign debt stress domain or credit cycle domain

Next major domain expansion should target macro-financial stress outside the current MR variable set.

Good candidates:
- sovereign debt stress
- credit cycle

Keep the scope narrow enough to preserve interpretability and avoid a large ontology redesign.

---

## 3. Run 1095-day MR backfill

Run a 1095-day, three-year MR backfill to capture the full 2022 tightening cycle more clearly.

Why:
- 730 days gives a useful recent window.
- 1095 days should cover a fuller tightening/regime-shift arc.
- More shift history should make MR a better flagship demo for ontology evolution.

Requirement: ProtonVPN Switzerland active and `FRED_API_KEY` valid.

---

## 4. Crypto domain

Consider a crypto regime domain using Glassnode and/or Dune APIs.

Likely focus:
- liquidity/risk-on behavior
- stablecoin flows
- exchange reserves
- funding/open interest where available
- on-chain stress proxies

---

## 5. AI regime domain

Consider an AI regime domain using earnings NLP, semiconductor data, and job postings.

Likely focus:
- earnings-call AI intensity
- semiconductor demand/supply proxies
- capex announcements
- AI labor demand
- equity market risk-on effects

---

## 6. Geopolitics domain

Consider a geopolitics domain using GDELT and trade-flow data.

Likely focus:
- conflict/event intensity
- trade disruption
- sanctions/export controls
- commodity/geographic exposure
- policy uncertainty

---

## 7. TemplateRules not implemented in `_derive_admissible_edges`

`_derive_admissible_edges` still admits broad all-pairs candidate edges.

This is acceptable for experimentation, but real domains need TemplateRules or domain-level admissibility constraints so variants do not explore impossible causal directions.

Examples:
- price should not cause planting delay
- unemployment should not retroactively cause past CPI
- exogenous macro state variables may need directional constraints

---

## 8. API regression tests: `tests/integration/test_api.py` not written

Many endpoint-specific tests exist, but there is still no consolidated API regression file.

Add `tests/integration/test_api.py` covering:
- route schema shape
- domain map for `mr`, `ng`, `zc`, `zs`
- population status
- candidates
- inference query fuzzy target resolution
- lineage cross-domain fallback
- shifts endpoint
- narrative snapshot export endpoint
- evidence recent
- debug endpoints
- unknown domain errors

---

## 9. ParameterStore: save on `learn()` only

Parameter persistence exists, but it is still tied to learn/update cycles rather than continuous flushing.

Risk:
- a process crash between state changes and persistence can lose newest CPT count changes.

Potential fix:
- make save semantics explicit at the end of every successful `learn()` cycle
- add a crash/restart regression around partially completed learn cycles

---

## 10. Inference aggregation uses raw `log_score`, not BIC-corrected score

`InferenceService` still uses raw `log_score` in aggregation paths.

Population management ranks with BIC-corrected average score. This mismatch can overweight candidates that have accumulated raw likelihood differently from the BIC-corrected population ranking.

Fix direction:
- expose a population scoring helper
- use the same score basis for inference aggregation and candidate ranking
- add tests where raw score and BIC-corrected score disagree

---

## 11. Consider inline LLM interpretation in dashboard

The current export workflow intentionally downloads prompt + JSON for offline LLM interpretation.

Inline interpretation could improve UX, but it adds API cost and product-surface complexity. Keep this as a later dashboard decision rather than a backend prerequisite.
