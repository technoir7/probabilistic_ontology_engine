# Snapshot: what this is, how it works, what is open

Read this first. It is the one-page map of three repositories that make one
project, written so a new contributor (person or model) can start work
without reading everything. As of 2026-11-02. For depth, follow the links;
each named document is current as of this date.

## 1. The project in one paragraph

A working argument about how beliefs should be held, revised and given up,
written as software. The **Probabilistic Ontology Engine (POE)** starts each
domain with concepts and no hypotheses, forms rival explanations from the
evidence, judges them only on evidence that arrives after they are formed,
and changes its mind when the evidence is decisive. It runs live on eleven
domains (the macro economy, credit, energy, crypto, labour, SF and others,
and art). It is not a forecaster; it is meant to be legible as epistemology,
and its forecasts are watched only as a check on its honesty. Art, a
humanities domain, grew its own method: the **abductive engine** reads 26
years of art criticism into claims, and POE judges what those claims
predict across thousands of artists. A public **dashboard** shows both.

**The method is primary.** Every rule is chosen for an epistemic reason,
stated in EPISTEMOLOGY.md, and tested by a replay planned in writing before
it runs. When a change would make output nicer but the method weaker, the
method wins.

## 2. The three repositories

| Repo | What | Where | Remote / deploy |
|---|---|---|---|
| `probabilistic_ontology_engine` (this one) | The engine and its API (Python, FastAPI, SQLite, pgmpy) | `~/Documents/code/probabilistic_ontology_engine` | GitHub `technoir7/probabilistic_ontology_engine`; Railway deploys `main` to https://epistemic-monitor-suite-production.up.railway.app |
| `epistemic-monitor` | The dashboard (Next.js 14, TypeScript, SWR, D3) | `~/Documents/code/epistemic-monitor` | GitHub `technoir7/epistemic-monitor`; Railway deploys `main` to https://epistemic-monitor-production.up.railway.app |
| `abductive_engine` | Reads the art press into claims; forms concepts and trends; exports art's case data to POE. Also an unfinished macro engine that forms its own concepts | `~/Documents/code/abductive_engine` | **Local only, no remote.** Commit, never push |

Art's raw data lives outside git in `~/Documents/art-press-texts/` (about
1.4 GB: Guardian and NYT texts, the model's readings, grounded claims,
vectors, concepts, trends, success runs, life readings) and
`~/Documents/art-market-reports/` (Artprice and Art Basel reports).
`art-press-texts/HANDOFF.md` is a historical note from 2026-10-28.

## 3. How it holds beliefs (the epistemology)

Full account: [EPISTEMOLOGY.md](EPISTEMOLOGY.md). The decisions and their
reasons: [REFACTOR_SPEC.md](REFACTOR_SPEC.md) §8, D1–D32. The
replays that tested them: [evals/README.md](evals/README.md).

- **No given hypotheses (D24).** A domain gives concepts only. Each period
  the engine forms, for each research programme, the connection the last
  100 records most support beyond chance (BIC). A new hypothesis is judged
  only on evidence after it was formed, so it never grades its own homework.
- **Three levels of belief.** How strong a relation is (conditional
  probability tables), whether it exists at all (a probability per link),
  and which whole explanation to hold (a population of rivals, scored
  prequentially on recent evidence, two-year half-life).
- **Rivals live until refuted (Lakatos).** An explanation is refuted only by
  a rival ahead by a Bayes factor above 100, on fit and on fit less
  complexity both (D22, D27). A rival can always be founded from a
  connection the leader lacks (D26). When nothing challenges the leader, its
  defining link is put on trial (Popper; D27).
- **Degree is not doubt (D25).** A measured signal is read as low, middle or
  high, observed exactly, not as a probability of "true".
- **Doubt in a crisis.** A week far more surprising than usual halves what
  was learned before.
- **Know your own confidence.** Calibration is tracked against what the
  evidence said, level by level.
- **What the replays found** (macro, 23 years of weekly FRED data as first
  published): no causal worldview beats each signal's own persistence;
  doubt fixed COVID; the engine is about as confident as its evidence. An
  engine that forms its own conjectures and tries to refute them reaches
  the same verdict (replay 14).

### Art: the humanities rules

- **Discourse is the evidence.** What critics wrote is itself the object,
  not a noisy sample of a hidden truth. No noise or agreement filters; two
  papers are two voices, not two witnesses who must agree (D28).
- **Never hard-code a thesis into the inputs.** Signals and features are
  chosen by a rule (the papers' own most-used tags, all of a set), never to
  test a hypothesis someone favours.
- **The model reads or writes; the engine judges.** A language model may
  read text into a fixed form, or write prose; code, and readers giving
  verdicts in a fixed form, decide what stands. Verdicts on strength are
  fixed by code and stated by the writer as given. Nothing a model writes is
  learned from. Contributors must not inject their own knowledge into
  outputs: findings come from the data.
- **Plan before running.** Every art step is planned in
  `abductive_engine/ART-PLAN.md` before it is built or run, with
  predictions; results, failed predictions and dated deviations are recorded
  there after. ART-PLAN is the plan of record for art.
- **Description is not prediction.** Trend lists, the market's image and
  the lives are said to describe; only what beats each case's own past in
  the case engine is said to predict.

## 4. How it works under the hood

### POE (this repo)

Layers import downward only (import-linter, `uv run lint-imports`):

```
api/        FastAPI routers, DTOs, presenters, narrative snapshots, LLM reports
runtime/    domain registry (the one list of domains), settings, ingestion, scheduler;
            art's cases / trends / success, computed once per process
engine.py   the facade over services + stores
services/   learning, edge_existence, population_manager, synthesis, programmes,
            inference (pgmpy), cases (the case engine)
stores/     SQLite, migrations/*.sql, one transaction per learning cycle
model/      CPTs, scoring, cadence, the domain contract, errors; cases, trends, success
domains/    one package per domain; sources/ (FRED, yfinance, GDELT, grades)
```

- **A domain** gives a `DomainModule` (`domain.py`) and `source.open_source`,
  and one `DomainRegistration` in `src/engine/runtime/registry.py`. Nothing
  else names domains. Variables and sources: [docs/domains.md](docs/domains.md).
- **The weekly loop.** The scheduler fetches each domain's latest period,
  builds a graded record, and runs one learning cycle: update tables, update
  link existence, score and prune the population, form hypotheses, found
  rivals or a trial, and log any change of leader as a paradigm shift.
- **Cases mode (art only, D29).** `services/cases.py`. A case is an artist,
  a concept or a trend. Every subset of a small pool of features is a rival
  scheme: a multinomial logistic model with one term per own-past grade and
  one per feature level (L2 priors), fitted by L-BFGS on earlier years only
  and scored on the next. Scores decay with a five-year half-life; the
  leader changes when a rival stands 3 nats ahead, and a combination must
  also beat each of its parts by 3. The cases ship as JSON snapshots in
  `src/domains/art_prestige_regime_v1/{case_data,trend_data,success_data}/`,
  rebuilt locally about once a year; the server never reads the press.
- **Success (D31)**, **themes**, **lives (D32)**: the case engine run
  offline on four kinds of success (critics approve, more press, a museum
  buys, a place in Artprice's Top 500) plus market movers, with two
  controls: each leading feature dealt at random among the year's artists,
  and the features of the year after. Verdicts by rule in
  `api/success_narrative.py` (under 10 nats: too small to claim; 100 or
  more: overwhelming). Results now: being written about in an argued-over
  trend adds most for three of the four kinds; coverage goes *with* a market
  place or rise rather than ahead of it; theme records help only museum
  buys; life stories add nothing to forecasting any kind.
- **LLM reports.** `api/report.py`. Every report is hash-gated: a refresh
  calls Fireworks only when the snapshot's hash (plus a prompt version) has
  changed; GETs read the cache only. Writer: `FIREWORKS_REPORT_MODEL`
  (default `accounts/fireworks/models/deepseek-v4p1-flash`). Prompts in
  `prompts/`. To force regeneration after a prompt change, bump the
  matching `*_PROMPT_VERSION` in `api/report.py`.
- **The imagined artist** (end of each success report): an image prompt, a
  wall text, an artist statement and a life, labelled fiction. The life is
  checked: every sentence cites its claims; the word rule
  (`api/life_words.py`) cuts any word its claims lack; two readers
  (GLM-5.3 Flash and the writer's model, `prompts/life_check.md`) must both
  say yes; fewer than three kept sentences has the writer write again (up to
  three writes, fullest kept); then an edit to read well
  (`prompts/life_edit.md`) is rechecked and kept only if it loses no claim.
  Rough joins and run-on sentences are accepted as how art writers write.

### The abductive engine

`src/abductive/` (see its DESIGN.md, EPISTEMOLOGY.md and ART-PLAN.md):

- `press.py` fetches every Guardian `artanddesign` and NYT "Art" article,
  2000-01 to 2026-09. `reading.py` / `read_press.py`: Claude Haiku (through
  `claude -p` on a subscription, offline) reads each article into claims in
  a fixed form: who, about what, asserts what, with what force (reports,
  judges, predicts, doubts) and stance (approval, disapproval, neither).
  An answer outside the form is refused, never repaired. `reading_life.py`
  adds each claim's subject and whether it is about an artist's life.
- `ground.py` keeps only claims whose every name and number is in their
  article (about 98%): 561,133 grounded claims.
- `embed.py` (local nomic-embed-text), `synthesis.py` (concepts formed in
  publishing order by nearness), `names.py` (proper names removed),
  `trends.py` (claims grouped by idea, followed across years; a local
  qwen3.6 names them, `evals/name_trends.py`).
- `cases.py`, `case_engine.py`: the first case engine (backoff tables; POE's
  additive engine superseded it for what ships).
- `evals/export_*.py` write the files POE's `evals/*_snapshot.py` turn into
  the shipped snapshots. POE's `evals/artist_records.py` and
  `evals/success_run.py`, `themes_run.py`, `lives_run.py`,
  `life_graph_run.py`, `champions.py` do the success work.
- The macro side (`scheme.py`, `population.py`, `weeks.py`) is paused after
  build step 4: it is meant to form concepts as well as links, and compare
  with POE.

### The dashboard

`app/page.tsx` holds the tabs and the layout; one component per panel in
`components/`; pure logic with tests in `lib/`. Only the selected domain's
panels mount. Every panel reads the live engine and shows an error rather
than placeholder data. Art's tab shows the case engine, trends, success,
movers, themes and lives panels; each report opens in place. The page is
rendered on every visit so a Home Screen copy picks up new builds.

## 5. Working on it

- **POE:** `uv sync`; `uv run pytest` (about 80 s; 811 pass, live-API tests
  excluded, network blocked); `uv run ruff check src`; `uv run lint-imports`.
  CI runs all three on push. No source file may pass 600 lines
  (`tests/test_guardrails.py`). Golden snapshots pin behaviour:
  `POE_UPDATE_GOLDEN=1 uv run pytest tests/golden`, then review the diff.
  Run locally with `POE_LOAD_DOTENV=0 EVIDENCE_SCHEDULER_ENABLED=false`.
- **Dashboard:** `npm install`; `npx tsc --noEmit`, `npm run lint`,
  `npm test`, `npm run build`. Point `NEXT_PUBLIC_API_BASE_URL` at an engine.
- **Abductive engine:** `uv run pytest` (146 tests, under a second).
- **Practice:** test first; delete dead code; small commits whose message
  says why. Plans go in ART-PLAN before art runs. Don't push POE during an
  art snapshot rebuild. Keep a 20 GB free-disk floor for art data work
  (`abductive/disk.py`). Keep Fireworks calls cheap: a report regeneration
  should cost under a cent.
- **Secrets:** API keys are in `.env` files (FRED, EIA, Guardian, NYT,
  Fireworks, the admin token). Don't read or print them.
- **Deploys:** Railway builds `main` on push. One deploy failed with no
  logs and a redeploy from source fixed it; redeploys are for the owner to
  run.

## 6. What needs work

Ordered roughly by how much each matters to the project as epistemology.

1. **No worldview beats persistence** (NEXT.md 1). Whether the cause is the
   concepts, the weekly clock or the method is open. The abductive engine's
   macro side, which forms its own concepts, is the planned test; it is
   paused at step 4 (hidden concepts, anomaly-occasioned formation and its
   first replay are unbuilt; DESIGN.md §10).
2. **The engine's open problems** (NEXT.md): weak dependences go unfound in
   a 100-record memory; any link is admissible; some links are true by
   definition; finer evidence costs too much structure (ordinal tables are
   the next try); a worldview can lose its core and keep its name; only
   macro's history is as first published.
3. **Only macro has been replayed** of the ten measured domains (replays
   1–14); art's monthly signals form no links (replays 15–16), which is why
   art moved to cases (replays 17–18).
4. **Art data limits:** two newspapers (the NYT archive gives lead
   paragraphs only), two museums, museum-collected artists only, the Top
   500 only; features come from a model's reading; life claims cover one
   year's championed artists. Snapshots must be rebuilt by hand each year.
5. **Abductive engine open items** (DESIGN.md §12): MIN_CASES tuned for
   weeks; catch-all concepts; its own case engine still on backoff tables;
   source trust planned, not built.
6. **Open write routes:** `POST /v1/ingest/trigger` and every
   `report/refresh` take no token, because the public dashboard calls them,
   and a refresh can call a paid model. Fine for a demo; a real deployment
   needs the admin token or a rate limit.
7. **Model-written prose is checked, not proven.** The life readers are
   models; a faithful synonym can be cut and a join can set two real
   people's claims side by side. Accepted for now (ART-PLAN 15.19).
