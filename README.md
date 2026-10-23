# Probabilistic Ontology Engine

A working argument about how beliefs should be held, revised and given up,
written as software. The engine keeps several rival explanations of a domain
(how inflation, credit, the dollar and the rest of the macro economy bear on
each other, for instance), weighs each against the evidence as it arrives
week by week, and changes its mind when the evidence says to. It is not a
forecaster, and is not tuned to be one; it is meant to be legible as
epistemology, and its forecasts are watched only as a check on its honesty.

It runs live over eleven domains fed by public data (FRED, EIA, SEC EDGAR,
GDELT, CoinGecko, SF Open Data and others), behind the Epistemic State
Monitor dashboard.

## How it holds beliefs

Belief lives at three levels (SPEC §3), each revised by Bayesian updating:

- **How strong is a relationship?** Each explanation's conditional
  probability tables, learned from the evidence.
- **Does a relationship exist at all?** Every link carries a probability
  of existing, raised or lowered by how much it helps explain the evidence.
- **Which whole explanation do I hold?** A population of rival
  explanations, scored on recent evidence; the best leads, the worst are
  dropped, and variants of the survivors are tried. A change of leader is
  recorded as a paradigm shift.

Four rules, each added after a replay showed the engine needed it
([what each replay found](evals/README.md)):

- **Rivals live until refuted.** Every explanation belongs to a research
  programme (the seed it grew from). A programme's best is kept until the
  evidence for the leader over it is decisive, a Bayes factor above 100,
  and programmes take turns to propose variants, so a rival gets to revise
  itself before it is judged (Lakatos).
- **Doubt in a crisis.** When the leading explanation is far more surprised
  by a week than it usually is, everything learned so far counts for half,
  so a world that has broken (COVID) loosens old certainties without making
  calm years fickle.
- **Beliefs about change.** Each signal's value last week is available as a
  cause, and one programme holds that things simply persist.
- **Know your own confidence.** Each week the engine records whether its
  70% beliefs come true 70% of the time, and whether its whole population,
  weighted by belief, explains the week better than its favourite.

## What 23 years of evidence did to it

Replayed week by week through 2003–2026 of real FRED data (macro domain,
five seeds, each replay planned in writing before it ran):

- **Its rival worldviews were refuted, not just outranked.** Of five
  starting explanations (monetary, credit-first, AI boom, recession, and a
  sparse baseline), the baseline's line came to lead in most seeds and the
  AI-boom line in the rest. Given protection until refuted and a fair turn
  at revising themselves, the others still fell to evidence of 100 to 1,
  most by 2005–08.
- **Persistence won by being absorbed.** Offered as a rival, "things stay
  as they were" led for five weeks; then every surviving explanation took
  last week's values as causes and it fell. With them, the leader explains
  each week far better, and forecasts it from last week alone better than
  base rates (−3.9 against −4.8 nats a week).
- **Doubt fixed COVID.** Without it, the relationships learned over
  seventeen years outlasted the world that produced them, and through
  2020–21 the engine did worse than believing nothing connects; with it,
  every seed did better.
- **It is timid.** When it says 15% the signal comes true 3% of the time;
  when it says 84%, 97%. It holds its beliefs more weakly than its evidence
  warrants.
- **Its paradigm shifts do not follow the headlines.** No change of leading
  programme followed 2008, COVID or the 2022 hikes within six months.
- **The replays found three bugs, now fixed**: an inverted dollar signal, a
  CPI lookback that dropped inflation in about half of all weeks, and an
  engine seed that never reached the code it was meant to seed.

![The rival explanations die out; leader changes; the fit gap year by year](docs/replay6.svg)

## Active Domains

Eleven domains are live and registered in the API:

| Key | Module ID | Cadence | Data Sources |
|-----|-----------|---------|-------------|
| `mr` | `macro-regime-v1` | Weekly | FRED |
| `ng` | `natural-gas-v1` | Daily | NOAA + EIA |
| `ai` | `ai-regime-v1` | Weekly | SEC EDGAR + yfinance + FRED |
| `sd` | `sovereign-debt-v1` | Weekly | FRED |
| `cc` | `credit-cycle-v1` | Weekly | FRED |
| `er` | `energy-regime-v1` | Weekly | yfinance + FRED |
| `lm` | `labor-market-v1` | Weekly | FRED |
| `cr` | `crypto-regime-v1` | Weekly | CoinGecko + yfinance + FRED |
| `gp` | `geopolitics-v1` | Weekly | GDELT + FRED |
| `sf` | `sf-urban-v1` | Weekly | SF Open Data + FRED |
| `art` | `art_prestige_regime_v1` | Monthly | GDELT news coverage, Art Institute of Chicago acquisitions, hand-labelled reports |

Most domains track eight Boolean variables across five seed candidate DAGs; the macro domain also holds each one's value last week and a sixth, persistence, programme. The art domain tracks 25 Boolean variables. Every domain's variables and sources: [docs/domains.md](docs/domains.md).

## Architecture

The engine has three belief levels:

```
Level 3 - Structure:  population of candidate DAGs; dominant hypothesis and paradigm shifts
Level 2 - Edges:      edge existence probabilities updated from evidence
Level 1 - Parameters: CPT counts learned from hard, missing, and soft evidence
```

Core services:
- `LearningService`: CPT updates, soft evidence (`SOFT_OBSERVED`), likelihood scoring.
- `EdgeExistenceService`: BIC-style edge existence updates and pruning.
- `PopulationManager`: candidate scoring, pruning, mutation, paradigm-shift tracking.
- `InferenceService`: pgmpy-backed Bayesian inference.
- `ExploreExploitService`: empirical mutual information — implemented and tested, not yet used by the learning loop (REFACTOR_SPEC D3).

Variable identity is deterministic via `stable_variable_id(domain_module_id, variable_name)`, preserving evidence continuity across restarts.

Code layout (layers import downward only; enforced by `uv run lint-imports`):

```
api/        HTTP routers, response models, view logic
runtime/    domain registry, settings, ingest/backfill/scheduler
engine.py   the facade over services + stores
services/   learning, edge existence, population, inference (pure)
stores/     SQLite repositories, migrations/*.sql, one transaction per learning cycle
model/      CPTs, the candidate score, cadence, domain contract, errors
domains/    one package per domain + sources/ (shared FRED/yfinance clients, helpers)
```

Adding a domain: give its package a `DomainModule` (`domain.py`) and a
`source.open_source(env)`, then add one `DomainRegistration` in
`src/engine/runtime/registry.py`. Nothing else names domains.

## API

All routes accept a `?domain=` query parameter using the domain key (e.g., `mr`, `sf`, `art`):

```
GET  /v1/population/status
GET  /v1/population/candidates
POST /v1/inference/query
GET  /v1/population/lineage/{candidate_id}
GET  /v1/population/shifts
GET  /v1/evidence/recent
POST /v1/ingest/trigger
POST /v1/ingest/backfill?days=N             # needs Authorization: Bearer $POE_ADMIN_TOKEN
POST /v1/ingest/art/manual?path=...          # learn new report files; needs Authorization: Bearer $POE_ADMIN_TOKEN
POST /v1/ingest/art/rebuild?months=36        # start forgetting art and relearning fetched months + reports, in the background; admin token
GET  /v1/ingest/art/rebuild                  # progress of the latest rebuild (idle / running / done / failed); admin token
GET  /v1/export/narrative-snapshot
GET  /v1/report/{domain}                     # read cached report (no LLM call)
POST /v1/report/{domain}/refresh             # regenerate if snapshot changed (Fireworks)
GET  /v1/debug/entropy
GET  /v1/debug/evidence-geometry
GET  /v1/debug/learning
GET  /v1/debug/structure
```

## Narrative Export Workflow

```
1. Open the dashboard, select any domain tab.
2. Click [ EXPORT SNAPSHOT ].
3. Browser downloads prompt + JSON state as a .txt file.
4. Paste into an LLM session for offline epistemic interpretation.
```

Exported regime state uses BN inference posteriors, not soft priors.

## Running

```bash
cd probabilistic_ontology_engine
uv sync            # creates .venv from uv.lock
uv run uvicorn src.engine.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Environment (`.env`):

```bash
FRED_API_KEY=...                    # required for MR, AI, SD, CC, ER, LM, CR, GP, SF
EIA_API_KEY=...                     # required for NG
FIREWORKS_API_KEY=...               # required for POST /v1/report/{domain}/refresh
EVIDENCE_SCHEDULER_ENABLED=true
POE_DATA_DIR=/data                  # Railway: persistent volume mount; default "." loses reports on redeploy
POE_ADMIN_TOKEN=...                 # enables backfill and the art routes; unset = those routes return 503
POE_CORS_ORIGINS=https://x.vercel.app,http://localhost:3000   # default "*"; read before .env loads, so set it in the real environment
```

No key required for SF Open Data, CoinGecko public endpoints, or GDELT. SEC EDGAR requires only a valid `User-Agent` header.

## Tests

```bash
# Standard suite (live tests excluded automatically; real HTTP is blocked):
uv run pytest

# Live tests only (hit real external APIs):
uv run pytest -m live

# Regenerate golden snapshots after an intentional behaviour change,
# then review the snapshot diff before committing:
POE_UPDATE_GOLDEN=1 uv run pytest tests/golden
```

`tests/golden/` pins engine, API, domain and calendar behaviour as committed
JSON snapshots; see `REFACTOR_SPEC.md` §7 Phase 0.

See `SNAPSHOT.md` for the full current-state handoff and `NEXT.md` for the active priority queue.
