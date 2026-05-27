# Next Steps

Priority order for the next development session.

---

## 1. Run initial backfills for the new domains

Eight domains were added since the last backfill pass (ai, sd, cc, er, lm, cr, gp, sf). All have schedulers. Without backfill data the populations have very little training signal and paradigm-shift history is empty.

Suggested backfill depths (via `POST /v1/ingest/backfill?domain=X&days=N`):

| Domain | Key | Suggested days | Notes |
|--------|-----|---------------|-------|
| `sovereign-debt-v1` | `sd` | 730 | FRED only |
| `credit-cycle-v1` | `cc` | 730 | FRED only |
| `labor-market-v1` | `lm` | 730 | FRED only |
| `energy-regime-v1` | `er` | 730 | yfinance + FRED |
| `crypto-regime-v1` | `cr` | 730 | CoinGecko + yfinance |
| `geopolitics-v1` | `gp` | 365 | GDELT (free, rate-limited) |
| `sf-urban-v1` | `sf` | 365 | SF Open Data + FRED |
| `ai-regime-v1` | `ai` | 730 | SEC EDGAR + yfinance + FRED |

Run one at a time and watch evidence geometry (`GET /v1/debug/evidence-geometry?domain=X`) after each to confirm variable ID matching and cadence are clean.

---

## 2. Add live integration tests for the remaining nine domains

`sf-urban-v1` is the only domain with a live test file (`tests/integration/test_sf_urban_live.py`). The sf-urban work revealed two silent ingestion bugs that the mocked tests could not catch (invalid FRED series IDs, wrong Socrata column names). The same class of bug could exist undetected in any other domain.

Add `tests/integration/test_<domain>_live.py` for each domain, all marked `@pytest.mark.live`. Each file should:
- Hit real endpoints for every data source the domain uses.
- Assert HTTP 200 and non-empty observations.
- Spot-check that at least one observation field is non-null and in a plausible range.

Priority order for live test addition (highest bug risk first):
1. `ai` — SEC EDGAR CIK lookups are brittle; yfinance `^SOX` and `^VIX` tickers can silently return empty.
2. `cr` — CoinGecko public API has aggressive rate limits and occasionally changes endpoint shape.
3. `gp` — GDELT query format and available fields have changed before.
4. `er` — yfinance energy futures tickers (`CL=F`, `NG=F`) roll quarterly.
5. `mr`, `ng`, `sd`, `cc`, `lm` — all FRED or EIA only; lower churn risk but still worth covering.

---

## 3. Run 1095-day MR backfill

A 730-day MR backfill is in place. Extending to 1095 days (three years) would capture the full 2022 tightening cycle and give more paradigm-shift history for the flagship domain.

Requirement: `FRED_API_KEY` set.

```bash
curl -X POST "http://localhost:8000/v1/ingest/backfill?domain=mr&days=1095"
```

---

## 4. TemplateRules not implemented in `_derive_admissible_edges`

`_derive_admissible_edges` still admits broad all-pairs candidate edges. This is acceptable for exploration but real domains need directional constraints so variants do not explore impossible causal directions.

Examples of constraints that should be enforced:
- Price should not cause an employment reading that predates it.
- Exogenous macro variables (e.g., `FedBalanceSheetShrinking`) should not have parents inside the domain.
- `CrimeIndexElevated` should not be a parent of `USYieldSpiking` across domains.

Design direction: a per-domain `admissible_edges()` method returning an explicit allow-set, used by `_derive_admissible_edges` instead of all-pairs.

---

## 5. API regression tests: `tests/integration/test_api.py` not written

Many endpoint-specific tests exist but there is no consolidated API regression file. Add `tests/integration/test_api.py` covering:

- Route schema shape for all ten domain keys.
- Population status and candidates for each domain.
- Inference query fuzzy target resolution.
- Lineage cross-domain fallback.
- Shifts endpoint (empty is valid before backfill).
- Narrative snapshot export structure.
- Evidence recent.
- Debug endpoints (`entropy`, `evidence-geometry`, `learning`, `structure`).
- Unknown domain key → 404.
- Missing environment variable for a domain → 503 with useful message.

---

## 6. ParameterStore: save on `learn()` only

Parameter persistence is tied to learn/update cycles. A process crash between state changes and disk flush loses the newest CPT count changes.

Fix direction:
- Make save semantics explicit at the end of every successful `learn()` call.
- Add a crash/restart regression that confirms CPT counts survive a mid-cycle kill.

---

## 7. Inference aggregation uses raw `log_score`, not BIC-corrected score

`InferenceService` uses raw `log_score` in aggregation paths. Population management ranks with BIC-corrected average score. This mismatch can overweight candidates that have accumulated raw likelihood differently from the BIC-corrected population ranking.

Fix direction:
- Expose a population scoring helper that returns the BIC-corrected score.
- Use the same score basis for inference aggregation and candidate ranking.
- Add tests where raw score and BIC-corrected score produce different candidate orderings to confirm the fix matters.

---

## 8. Consider inline LLM interpretation in dashboard

The current workflow downloads prompt + JSON for offline LLM interpretation. Inline interpretation would shorten the loop but adds API cost and UX surface area.

Keep as a deferred dashboard decision; it is not a backend prerequisite.
