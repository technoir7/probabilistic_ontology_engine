# Probabilistic Ontology Engine

A working argument about how beliefs should be held, revised and given up,
written as software. The engine keeps several rival explanations of a domain
(how inflation, credit, the dollar and the rest of the macro economy bear on
each other, for instance), weighs each against the evidence as it arrives
week by week, and changes its mind when the evidence says to. It is not a
forecaster, and is not tuned to be one; it is meant to be legible as
epistemology, and its forecasts are watched only as a check on its honesty.

It runs live over eleven domains fed by public data (FRED, EIA, SEC EDGAR,
GDELT, CoinGecko, SF Open Data and others), behind the
[Epistemic State Monitor](https://epistemic-monitor-production.up.railway.app)
dashboard ([source](https://github.com/technoir7/epistemic-monitor)).

![The Epistemic State Monitor: the macro domain's leading explanation, its belief graph, current regime and paradigm-shift history](docs/dashboard.png)

**What's here.** About 19,000 lines of Python (FastAPI, SQLite, pgmpy) and
14,000 of tests: 660 tests (18 of them against the live APIs), including 38 golden snapshots that pin the API,
domains and engine behaviour, with real network calls blocked. The layering
below is enforced by import-linter in CI. Eleven domains learn from public
data on a schedule, deployed on Railway from `main`. Every finding below
comes from a replay planned in writing before it ran, and reruns offline
from data committed here.

## Try it

No API keys needed:

```bash
uv sync
uv run pytest                     # ~40 s, no network
uv run python -m evals.replay --seed 0 --as-published --out /tmp/poe/seed0.jsonl.gz
uv run python -m evals.programmes /tmp/poe
```

The replay feeds 23 years of weekly FRED data (2003–2026, as first
published) through a fresh engine in about 40 seconds; the last command
prints how long each rival worldview survived and led. It reproduces
seed 0 of replay 10 below exactly.

## How it holds beliefs

Belief lives at three levels, each revised by Bayesian updating
([SPEC.md](SPEC.md) §3):

- **How strong is a relationship?** Each explanation's conditional
  probability tables, learned from the evidence.
- **Does a relationship exist at all?** Every link carries a probability
  of existing, raised or lowered by how much it helps explain the evidence.
- **Which whole explanation do I hold?** A population of rival
  explanations, scored on recent evidence; the best leads, the worst are
  dropped, and variants of the survivors are tried. A change of leader is
  recorded as a paradigm shift, dated by the evidence that caused it, and
  marked as a change of worldview when the new leader comes from another
  research programme or as a revision when it is a variant of the same one.

Four rules, each added after a replay showed the engine needed it
([what each replay found](evals/README.md)):

- **Rivals live until refuted.** Every explanation belongs to a research
  programme (the seed it grew from). A programme's best is kept until the
  evidence for the leader over it is decisive, a Bayes factor above 100
  from fit alone (simplicity ranks explanations but refutes none),
  and programmes take turns to propose variants, so a rival gets to revise
  itself before it is judged (Lakatos).
- **Doubt in a crisis.** When the leading explanation is far more surprised
  by a week than it usually is, everything learned so far counts for half,
  so a world that has broken (COVID) loosens old certainties without making
  calm years fickle.
- **Beliefs about change.** Each signal's value last week is available as a
  cause. Every causal programme assumes signals persist, so they compete on
  what else they claim; one programme claims nothing else.
- **Know your own confidence.** Each week the engine records whether its
  70% beliefs come true 70% of the time, judged both against each signal
  rounded and against the probability the evidence gave it, and whether its
  whole population, weighted by belief, explains the week better than its
  favourite.

## What 23 years of evidence did to it

Replayed week by week through 2003–2026 of real FRED data (macro domain,
five seeds, each replay planned in writing before it ran). Fit is measured
in nats, the log of how surprised the engine was by a week's evidence: one
nat less surprise means it gave what happened about 2.7 times the
probability. A Bayes factor above 100 is the conventional threshold for
"decisive".

- **Its rivals were first refuted unfairly.** Through replay 9 every rival
  worldview (monetary, credit-first, AI boom, recession) died by 2005–08,
  most within weeks, none ever revised. Replay 10 found why: the complexity
  penalty was charged twice, a week with no "last week" was scored as a
  free pass, and the rivals were judged on persistence, which none of them
  denies. With refutation by evidence alone, missing values averaged over,
  and persistence a shared assumption, they live until the evidence
  refutes them: monetary and recession to 2010, credit to 2016, AI boom
  and the sparse baseline to 2014–2026, most revising themselves first.
- **No causal story beats persistence.** Given that every signal follows
  its own last week, none of the four worldviews explained the weeks better
  than persistence alone, in any seed, in 23 years. Persistence explains
  each week 0.56 nats better than "nothing connects" and forecasts it from
  last week alone at −3.4 nats against −4.8 for base rates.
- **Doubt fixed COVID.** Without it, the relationships learned over
  seventeen years outlasted the world that produced them, and through
  2020–21 the engine did worse than believing nothing connects; with it,
  every seed did better.
- **It believes as firmly as its evidence, no more.** Judged against each
  signal rounded to true or false, it looked timid: when it said 15%, the
  signal came true 3% of the time. But the evidence itself is soft (on weeks
  that round to true, it puts the signal at 0.75 on average), and judged
  against what the evidence said, it was calibrated to within 1 to 1.4
  points (replay 9). The timidity was in the measure. Leading with
  persistence (replay 10) it is within 4.7 points, slightly unsure in the
  middle: it says 56% where the evidence says 65%.
- **Its paradigm shifts do not follow the headlines.** No change of leading
  programme followed 2008, COVID or the 2022 hikes within six months.
- **Nothing rests on hindsight.** Replayed again with each figure as it was
  first published (ALFRED vintages, before revisions), the beliefs barely
  moved: inflation read differently in 37 of 1,229 weeks, and the same
  programme led.
- **Finer evidence bought fewer beliefs.** Reading each signal in five
  ordered levels instead of yes/no made the engine better calibrated, but a
  five-level relationship costs ten times the parameters, and Occam's razor
  (BIC) left the leader 2–3 links where it had held 8–13. The engine went
  back to yes/no; ordinal tables, which price a relationship by its order,
  are the next thing to try.
- **The replays found six bugs, now fixed**: an inverted dollar signal, a
  CPI lookback that dropped inflation in about half of all weeks, an engine
  seed that never reached the code it was meant to seed, the double
  complexity charge and the free first week above, and a replay measure that
  scored the leader without last week's values, which overstated replays
  6–9's fit gap.

![Rival explanations surviving; leader changes against the events; the fit gap year by year](docs/replay10.svg)

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

Variable identity is deterministic via `stable_variable_id(domain_module_id, variable_name)`, preserving evidence continuity across restarts.

Code layout (layers import downward only; enforced by `uv run lint-imports`):

```
api/        HTTP routers, response models, view logic
runtime/    domain registry, settings, ingest/backfill/scheduler
engine.py   the facade over services + stores
services/   learning, edge existence, population, inference
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
POST /v1/ingest/rebuild?domain=cc&days=730  # forget a domain and relearn it from its sources, in the background; admin token
GET  /v1/ingest/rebuild?domain=cc           # progress, records learned, and any weeks it could not fetch; admin token
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
POE_CORS_ORIGINS=https://your-dashboard.example,http://localhost:3000   # default "*"; read before .env loads, so set it in the real environment
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

Open problems, and what the replays suggest about each: [NEXT.md](NEXT.md). Design decisions
and their reasons: `REFACTOR_SPEC.md` §8.
