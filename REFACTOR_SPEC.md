# Refactor Spec — Probabilistic Ontology Engine

Status: done, merged to `main`. Phases 0–6 are complete except 4.7 and the 5.5 read-model split (see each phase). The milestone passes on 18/20 seeds (D14). Open: B20. The decision log (§8) has continued past the refactor, D1–D23 · Written 2026-10-04, status updated 2026-10-24 · Scope: `src/`, `tests/`, `scripts/`, repo hygiene

This is the plan we follow to refactor the backend. It says what is wrong (with
evidence), what the code should look like afterwards, and the order to get there
without breaking the running service. §0–§2: summary and rules. §3–§4: evidence and bugs.
§5–§6: target design and guardrails. §7: the plan. §8: decisions and their reasons.

---

## 0. Summary

The math core (`engine.py`, `services/`, `stores/`, `schemas.py`, ~4.3k lines) is mostly
sound and readable. The problems are in how it is wired together:

1. **One 2,610-line file runs everything.** `src/engine/api/app.py` imports all
   11 domains by name, builds their engines, holds 11 scheduler runners and 4
   copies of the backfill loop, dispatches ingestion through an 11-branch `if`
   chain, contains the view logic for every endpoint, and reaches into engine
   private fields. Adding a domain means editing ~8 places in this file.
2. **Domains are copy-paste, not plug-ins.** 8 copies of the FRED client
   (1,542 lines, which differ only in a series dict), 10 schedulers (1,452 lines,
   which differ only in names), 3 yfinance clients, and 9–10 copies of each
   pipeline helper. The copies have already drifted: two weekly calendars
   disagree (Friday vs Sunday). Changing FRED retry behavior means editing 8 files.
   Adding a FRED domain means about 1,000 copied lines plus 9 edits to `app.py`.
3. **Abstraction barriers leak in the core.** `LearningService` writes straight
   into `CPTData.counts`; the candidate score is computed in three different ways
   in three places; the API and an external package reach into `engine._modules`,
   `engine._learn_*`, `engine.evidence_store`, and even set `engine._art_causal_prior_result`.
4. **Persistence is not trustworthy.** Three separate SQLite connections per DB,
   no transactions, population tables that are written but never read back. A
   restart silently discards every variant and miscomputes every score (verified,
   §4).
5. **Errors are swallowed.** 73 broad `except Exception` handlers in `src/`, 17 of
   them followed by `pass`. Inference failures come back as `{"error": ...}`
   dicts or uniform 0.5 probabilities.
6. **Repo hygiene.** 18,975 files of a Linux `.venv` and 25 `.pyc` files are
   committed; the committed venv does not run on this Mac.

The refactor is mostly moving and de-duplicating code behind clear interfaces.
It is **not** a rewrite and **not** a performance project (measured: `learn()`
on one record ≈ 59 ms, restart replay of 300 records ≈ 98 ms, 8 inference calls
≈ 8 ms — fine at today's sizes).

Real bugs found along the way are listed in §4. They are fixed in their own
commits, never mixed into a move/rename commit.

---

## 1. Goals and non-goals

### Goals

- **Adding a domain touches one place**: the domain's own package plus one line
  in a registry. No edits to `app.py`.
- **Changing shared behavior touches one file**: e.g. FRED retry policy, the
  weekly backfill calendar, the candidate score, the "rising/falling" label.
- **Each layer uses only the layer below through its public interface.** The
  API never touches stores or private engine fields; services never touch a
  CPT's storage dict; domains never touch the engine.
- **Restart-safe state.** What the engine believes after a restart equals what
  it believed before.
- **Fail loudly.** No silent defaults in the core; boundary code turns failures
  into typed errors and HTTP status codes.
- **Tests pin behavior before code moves**, and test through public seams so
  the refactor does not break them.

### Non-goals

- No new features, no new domains, no algorithm changes beyond the bug fixes in §4.
- No speed work. If something gets slower, a budget test (§6) catches it.
- No plugin framework (entry points, dynamic discovery). An explicit list of
  domains is enough for 11 domains in one repo.
- No PostgreSQL move. We only make the SQL and migrations portable, as
  `CLAUDE.md` already requires.

---

## 2. Ground rules for every refactor PR

1. **Characterization tests first** (Phase 0). No code moves until the golden
   tests in §7 Phase 0 exist and pass.
2. **Move or change, never both.** A commit either moves/renames code with zero
   behavior change, or changes behavior with a test that shows the change. Bug
   fixes from §4 each get their own commit with a failing-first test.
3. **Full suite green before the next step** (`CLAUDE.md` build rule). Run with
   `uv run pytest`.
4. **Keep the HTTP contract.** Routes, query params, and response shapes stay
   identical unless a §4 fix says otherwise. The frontend (`epistemic-monitor`)
   must keep working; Phase 0 snapshots every route's response shape.
5. **Keep env var names.** Railway is configured with them.
6. **Duplication is cheaper than the wrong abstraction.** We extract only where
   three or more copies already prove the shared shape (§3.5 lists which ones
   qualify). Things that only look alike stay separate.
7. Small PRs: one phase step per PR, message says why.

---

## 3. Findings

Each finding has an ID used by the plan in §7.

### 3.1 Repository hygiene

| ID | Finding | Evidence |
|----|---------|----------|
| H1 | `.venv/` (18,975 files, created on Linux at `/home/aaron/...`) is tracked. Its `python3` symlinks to `/usr/bin/python3`, which does not exist on macOS, so `.venv/bin/python -m pytest` fails here. `.gitignore` lists `.venv/` but it was committed before the ignore was added (commit `87628dee`). | `git ls-files \| grep -c '^.venv/'` → 18975; `.venv/pyvenv.cfg` |
| H2 | 25 `__pycache__/*.pyc` files are tracked; every test run dirties the tree. | `git ls-files \| grep -c '\.pyc$'` |
| H3 | No lockfile. `pgmpy>=0.1.20` is unpinned but the code uses `DiscreteBayesianNetwork` (pgmpy ≥1.0) and pgmpy already prints deprecation warnings for v1.3. User standard is `uv`. | `pyproject.toml:10-22` |
| H3b | **Deploy is not reproducible.** `nixpacks.toml` installs `art-market-domain` from the `main` branch tarball with `--no-deps`, plus six packages (spacy, scikit-learn, pandas, …) that appear only in `nixpacks.toml`, not `pyproject.toml`. Any push to that repo's `main` changes production. Locally the package is missing, so 66 tests fail (§3.7). | `nixpacks.toml:6` |
| H4 | Package import name is literally `src` (`packages = ["src"]`, `pythonpath = ["."]`). Works, but every import is `from src.engine...`. | `pyproject.toml:27-31` |
| H5 | `CLAUDE.md` says read `SPECM.md`; the file is `SPEC.md`. | `CLAUDE.md:4` |
| H6 | 9 one-off audit/handoff docs at repo root (`*_AUDIT.md`, `*_VERIFICATION.md`, `SNAPSHOT.md`, `BACKFILL_SF_URBAN.md`, …) mix with live docs. | repo root |
| H7 | Dead or misleading code: `src/domains/agriculture_weekly.py` — corn/soy were removed in `749fe5b8`, so `AGRICULTURE_DOMAIN_IDS` is dead, while `is_agriculture_domain` is still live in 4 places in `app.py` and really means "weekly domain except mr/ai"; empty `src/domains/market_risk_v1/` (SPEC §18 sample domain, never built); 5 stub methods (`version`, `initial_entities`, `initial_assertions`, `variable_specs`, `initial_parameterizations`) × 11 domain classes, never called; `_most_recent_monday` (0 uses); unused imports (`CandidateStatus` ×7, `get_variables` ×7, `_last_friday` ×2 in `app.py`); hard-coded `True` flags in `LearningPipelineStatusOut` (`app.py:1170-1174`); broken standalone entry point `asyncio.run(_main() if False else None)` (`credit_cycle_v1/scheduler.py:77`). | `app.py:767-776, 822, 1294` |

### 3.2 API layer (`src/engine/api/`)

| ID | Finding | Evidence |
|----|---------|----------|
| A1 | **God module.** `app.py` is 2,610 lines: 33 response models, 18 routes, view logic, composition root, 11 scheduler runners, 4 backfill loops, env parsing. | `app.py` |
| A2 | **Domain knowledge hard-coded in the API.** 48 domain-specific imports (`app.py:20-74`); domain table `_DOMAIN_MAP` (`:95`); env-key table `_require_domain_env` (`:675-679`); 11-branch `if` in `_fetch_evidence_record` (`:682-756`); 11 hand-written engine builds and 11 lock entries in `lifespan` (`:860-899`); 10 near-identical scheduler `create_task` blocks (`:903-1016`). | — |
| A3 | **Four copies of the backfill loop**: `_backfill_if_empty` (`:793`), `_backfill_macro_if_empty` (`:2193`), `_backfill_ai_if_empty` (`:2290`), `_backfill_fred_domain_if_empty` (`:2517`). They differ only in the date list and sleep (1.0 vs 2.0 s). Plus the manual `ingest_backfill` route (`:1283`) has a fifth inline copy. | — |
| A4 | **API imports private helpers from domains**: `_weekly_backfill_dates` from `macro_regime_v1.scheduler` (used for *all* FRED domains, `:2529`), `_last_friday` (imported, unused, `:2172, :2266`). | — |
| A5 | **API reaches into engine internals**: `engine._modules[...]` (`:602, :1502, :1869`), `engine._learn_call_count/_learn_last_ts/_learn_records_total` (`:1162-1164`), `engine.evidence_store.*` (~15 call sites), `engine.population_store.load_shift_events` (`:1683, :1848`), `engine.inference_service.query` (`:1495, :1764`), `pop._avg_score` (`:1428, :1801`). | — |
| A6 | **An external package drives the engine from inside.** The art route passes the whole engine to `art_prestige_regime_v1.manual_ingest.rebuild_art_evidence_state(engine, …)` and reads back `getattr(engine, "_art_causal_prior_result", …)` — a domain package setting a private attribute on the engine. The art package (pinned commit `f6327080`) also imports `src.engine.*` directly and touches `engine._batch_index`, `_modules`, `_learn_call_count/_learn_last_ts/_learn_records_total`, `evidence_store` (10 sites), `parameter_store`, `population_store`, `population_manager`, and `learning_service`. It is a second consumer of engine internals, so any rename in Phases 2–5 breaks it unless Phase 5.6 lands first or keeps a compatibility shim. | `app.py:1353-1384`; `art_prestige_regime_v1/manual_ingest.py` |
| A7 | **View logic duplicated.** Candidate status (dominant/rising/falling/neutral) is computed identically in `population_candidates` (`:1436-1444`) and `narrative_snapshot` (`:1808-1816`). "P(True)" extraction `dist.get("True", dist.get("true", …))` at `:1499` and `:1767`. `_time_ago` and score normalization are copied again in `poea_dynamic.py:75, :107`. Explore band `0.3/0.7` is hard-coded in `poea_dynamic.py:20-21` while the apriori path reads it from the domain. | — |
| A8 | **Two read backends selected by `if` in every route.** 7 routes start with `if ontology_mode == "dynamic" and poea_dynamic.is_dynamic_available(...)`. `ontology_mode` is an unvalidated `str`; a typo silently falls back to apriori. | `app.py:1084, 1419, 1469, 1559, 1663, 1723, 2118` |
| A9 | **A route calls another route.** `domain_report_refresh` awaits the `narrative_snapshot` route function (`:2051`). The snapshot builder should be a function both call. | — |
| A10 | **CPU work on the event loop.** `engine.learn()` and pgmpy inference are synchronous and run inside `async def` handlers and scheduler coroutines. ~60 ms per learn today; it blocks every other request while it runs. | `app.py:789, 2234, …` |
| A11 | **Locks don't cover the scheduler.** Per-domain `asyncio.Lock`s guard manual trigger and startup backfill, but the domain schedulers' `run_once` never takes the lock, so a scheduled run can interleave with a manual backfill. | `grep lock src/domains/*/scheduler.py` → none |
| A12 | **Config read everywhere.** `os.environ` is read in `app.py` (lifespan, routes), `report.py`, `poea_dynamic.py`, `config.py`, and domain schedulers. `_data_dir()` creates directories as a side effect and is called per request (`:2016, :2055`). | — |
| A13 | **Startup is all-or-nothing.** If the optional sibling repo `art-market-domain` is missing (it is, on this machine), `_build_art_domain()` raises in `lifespan` and the whole API fails to start. `scheduler_enabled` without `EIA_API_KEY` also crashes startup (`:902`). `_import_art_module` mutates `sys.path` (`:577-580`). | — |
| A14 | **Security.** CORS `allow_origins=["*"]` with `allow_credentials=True` (`:1043-1049`). All POST routes are unauthenticated, including ones that spend money (`/v1/report/{d}/refresh` calls Fireworks) or hammer upstream APIs (`/v1/ingest/backfill?days=N`, no upper bound). `/v1/ingest/art/manual?path=` reads any server path the caller names (`:1327, :1335`). | — |

### 3.3 Engine core (`engine.py`, `services/`, `schemas.py`)

| ID | Finding | Evidence |
|----|---------|----------|
| C1 | **Scoring lives in three places with three rules.** BIC-average score is implemented twice, identically (`schemas.py:263` `OntologyPopulation._avg_score`, `population_manager.py:138` `PopulationManager._avg_score`). `introduce_variants` ranks parents by **raw** `log_score` (`population_manager.py:234`); `InferenceService` TOP_K weights by `exp(raw log_score)` (`inference.py:62-65`); NEXT.md #7 already notes the mismatch. One score function, one place. | — |
| C2 | **Storage representation leaks into learning.** `LearningService._accumulate_mean_field` and `accumulate_em` index and mutate `cpt_data.counts[parent_config][val]` directly and rebuild the parent-config key format `tuple(sorted(pa.items()))` themselves (`learning.py:212-244, 405-447`). The key format is owned by `CPTData` (`parameter_store.py:120-122`). Changing the CPT representation (e.g. to NumPy arrays) today forces edits in learning. | — |
| C3 | **`CPTData` is a model, not storage.** It lives in `stores/parameter_store.py` but is pure math (probabilities, BIC, marginalization) used by learning, edge existence, and inference. It belongs in the core. | — |
| C4 | **Private helpers imported across modules.** `learning.py:321` imports `_build_tabular_cpd`, `_encode_value` from `inference.py`; the pgmpy model build is duplicated (`learning.py:333-358` vs `inference.py:121-169`). | — |
| C5 | **`ProbabilisticOntologyEngine` is multi-domain in shape, single-domain in use.** Every engine in the app holds exactly one domain, but the class keeps `active_domain` mutable state, a `_modules` dict, and `assert self.active_domain` as control flow (`engine.py:67-73, 212, 218, 241`). `get_edge_existence` silently returns `None` when no domain is active. | — |
| C6 | **Thresholds are global and mostly ignored.** `EdgeExistenceService` is built with default thresholds (`engine.py:59`); the domain's `existence_thresholds()` is passed only to `PopulationManager.initialize`, which stores it on `self` (overwritten per domain) and never reads it. So **every domain's `prune_below` is ignored** for edge pruning (SPEC §10.4 says "domain prune_below threshold"). `accept_above` is not read anywhere in `src/`. `StructureModeConfig.thresholds` and `min_evidence_before_pruning` are display-only. | `engine.py:59, 89, 136`; `population_manager.py:75-76` |
| C7 | **Parameter that is only a flag.** `introduce_variants(domain, learning_service=None)` never calls `learning_service`; it only checks `is not None` and then talks to the parameter store (`population_manager.py:269-279`). | — |
| C8 | **Misleading names.** `_MIN_BATCHES_FOR_PRUNING = 3` is compared against `evidence_count`, which counts records, not batches (`population_manager.py:38, 191`). `parent_ids_json` stores parent *names* (`parameter_store.py:43`). `OntologyCandidate.variables` is shared by reference between parent and variant (`population_manager.py:382`). | — |
| C9 | **Scoring happens after learning on the same batch.** `learn()` accumulates counts from a batch, then scores the candidate on that same batch (`engine.py:261-270`). Denser candidates are scored on data they just fitted. SPEC §17 pseudocode should decide the order (prequential = score first, then update). **Decision needed (§8)**; not changed by the refactor. | — |
| C10 | **Legacy-ID compatibility on the hot path.** Every `accumulate` / `compute_log_likelihood` call runs `normalize_evidence_record_variable_ids` over the whole batch, per candidate, copying records (`learning.py:65, 476, 531-539`). `register_domain` also rewrites legacy IDs in the DB (`evidence_store.py:124`). One-time migration, then delete the per-call shim. | — |
| C11 | **Unused production code.** `ExploreExploitService` (only tests use it; SPEC §10.1 wants it in the learn loop), `LearningService.accumulate_em` (only `tests/level1`), `EdgeExistenceService.get_uncertain_edges`, `PopulationManager.dominant_matches_structure` (tests only), `PopulationStore.load_population_id`, `ParameterStore.remove_candidate`, `CPTData.ensure_config/get_cpt_dict`, `ModelSnapshot` fields never consumed. **Decision needed (§8)**: wire up or delete. | grep |
| C12 | Naive datetimes: `datetime.utcnow()` (deprecated) in 11 places; evidence timestamps are naive while API code assumes UTC. | `schemas.py:132`, stores |

### 3.4 Persistence (`stores/`)

| ID | Finding | Evidence |
|----|---------|----------|
| P1 | **No transaction boundary.** Each store opens its own `sqlite3` connection to the same file and commits after every row (`append_score_record` commits once per candidate per batch). A crash mid-`learn()` leaves scores, CPTs and population metadata out of step (NEXT.md #6). | `evidence_store.py:34`, `parameter_store.py:253`, `population_store.py:80` |
| P2 | **Population tables are write-only.** `ontology_candidates` and `ontology_populations` are written every cycle but never loaded. On restart the engine rebuilds from the domain's seed candidates and replays all evidence to recompute scores. Variants, pruning decisions, generation and lineage are lost (verified in §4 B1). | `population_store.py` (no load methods), `engine.py:148` |
| P3 | **CPTs keyed by edge signature, which changes.** `save_candidate` keys parameters by the *current active-edge* signature; after any edge is pruned that signature no longer matches the seed candidate's, so learned CPTs are not restored for pruned candidates, and variant CPTs are never restored. | `engine.py:121-125, 319-325` |
| P4 | **No migrations.** DDL is inline per store; schema changes are `ALTER TABLE` wrapped in `try/except "duplicate column"` (`parameter_store.py:256-264`). `CLAUDE.md` requires shared SQLite/PostgreSQL migration files. | — |
| P5 | **Non-portable SQL.** `INSERT OR REPLACE` / `INSERT OR IGNORE` are SQLite-only. Use `INSERT … ON CONFLICT … DO UPDATE/DO NOTHING` (SQLite ≥ 3.24 and PostgreSQL). | stores |
| P6 | **Unbounded reads on request paths.** `/v1/debug/entropy` and `/v1/debug/evidence-geometry` call `evidence_store.load_all` (full table, deserialized to Pydantic) per request; narrative snapshot loads all shift events to show the last 3; startup replays all evidence. Fine today; unbounded in principle. | `app.py:1099, 1119, 1848` |
| P7 | Docstring says "Thread-safe SQLite evidence store" with `check_same_thread=False` and no lock. | `evidence_store.py:30-34` |

### 3.5 Domain layer (`src/domains/`)

**Measured duplication** (class bodies diffed after normalizing names):

| Group | Copies | Lines | What genuinely varies |
|-------|--------|-------|-----------------------|
| `ingestion/fred_client.py` | 8 (+ ai re-exports macro's) | 1,542 | the `FRED_SERIES` dict, `FETCH_LOOKBACK_DAYS`, default lookback. sf vs crypto/geo/sd: 2 changed lines. |
| `scheduler.py` | 10 | 1,452 | class name, log strings; cadence (ng daily, others weekly-Monday) |
| `ingestion/yfinance_client.py` | 3 (ai, cr, er) | 692 | ticker list, lookback; renamed dataclasses |
| pipeline helpers `_sigmoid`, `_soft_bool`, `_zscore`, `_last_friday`, `_weekly_backfill_dates` | 9–10 each (+1 in `scripts/`) | — | nothing (identical bodies) |
| `build_evidence_record` template | 9 | ~40 each | assignment list, `source_ref` |
| `domain.py` boilerplate (`_edge`, `_var_list`, `_VARIABLE_DEFS`) | 11 | — | variable names, seed candidates, priors |
| ingest-then-learn logic | 16 (10 schedulers, 5 in `app.py`, 1 script) | — | nothing |

**Qualifies for extraction (≥3 proven copies, same reason to change):** FRED
client, yfinance client, cadence/calendar helpers, soft-evidence helpers and
record builder, ingest+learn+backfill+scheduler loop, `domain.py`
variable/edge constructors.

**Does not qualify (looks alike, changes for domain reasons — keep per domain):**
the per-variable `_compute_*` signal functions (windows, scales, absolute
thresholds such as HY > 5.5 differ for domain reasons); seed candidates and
priors; `existence_thresholds()` (identical values today `(0.05, 0.90, (0.25, 0.75))`,
but each is a per-domain tuning knob — offer a `DEFAULT_THRESHOLDS` constant,
keep the method); the six one-off clients (EIA, NOAA, SFGov, GDELT, CoinGecko,
EDGAR) — one each, no generic HTTP base class; the art manual-ingest flow.

| ID | Finding | Evidence |
|----|---------|----------|
| DL1 | **No explicit contract.** `engine.py:85` says "must implement the DomainModule interface"; no Protocol/ABC exists. The engine uses 3 methods; the real contract (pipeline + scheduler + env + cadence) is implicit and lives in `app.py`. | grep `Protocol\|ABC` → none |
| DL2 | **Drift: two weekly calendars disagree.** `agriculture_weekly.py` anchors weeks on **Sunday** and lists sd/cc/er/lm/cr/gp/sf (plus dead corn/soy) but not mr/ai; the schedulers anchor on **Friday** (`_last_friday`). `POST /v1/ingest/trigger?domain=sd` stamps a Sunday while the sd scheduler stamps a Friday → two records for one week. `trigger?domain=mr` uses "yesterday"; `backfill?domain=mr&days=90` writes 90 *daily* records of weekly data, which `macro_regime_v1/scheduler.py:20-21` itself warns against. A test locks in the Sunday behavior (`test_variable_identity_and_weekly_cadence.py:78-88`). | — |
| DL3 | **Drift: scheduler logging.** learn-failure log keeps the traceback (`exc_info=True`) only in mr/ng/ai; the other 7 drop it (e.g. `sf_urban_v1/scheduler.py:55`). | — |
| DL4 | **Drift: SFGov date filters.** `fetch_permits` / `fetch_incidents` drop rows after `end_date` (`sfgov_client.py:128, 170`); `fetch_businesses` does not (`:213-219`), so historical backfills see future business openings. | — |
| DL5 | **I/O mixed with domain math.** `NOAAClient` computes `hdd`/`temp_anom`/`heating_dem` (`noaa_client.py:157-171`); `EIAClient` computes `price_up`/`storage_draw` (`eia_client.py:149-158`). Macro/sf keep fetch → `compute_snapshot` (pure) → `build_evidence_record` (pure) — that is the pattern to standardize on. | — |
| DL6 | **Stringly-typed record building.** The 7 newer pipelines use `_apply(var, sig, conf, "p_attr", "bool_attr")` + `setattr` (e.g. `sf_urban_v1/ingestion/pipeline.py:305`); a typo is never caught. Adding one variable = 5 edits. | — |
| DL7 | **Outages become evidence.** `fetch_all_series._safe_fetch` turns any `IOError` into `[]` (`macro fred_client.py:276-282`, ×8; ai has its own at `ai_regime_v1/ingestion/pipeline.py:705-719`); yfinance, SFGov, GDELT do the same; EDGAR caches failures for 6 h (`edgar_client.py:309-314`). Each missing signal becomes `p=0.5, confidence=0.5`, and no FRED pipeline ever raises — a full FRED outage writes and learns from an all-0.5 record. Soft evidence is injected as the variable's distribution (`learning.py:151-156`), so 0.5 records pull CPTs toward independence. The engine supports `MISSING` but no domain emits it; per-assignment `confidence` is read by no service. | — |
| DL8 | **Errors lose type.** `FREDClient` wraps `HTTPStatusError` into a plain `IOError`, dropping status and `Retry-After`; `scripts/backfill_sf_urban.py:96` detects 429 by searching the message for `"429"`; its docstring claim "Respects Retry-After" (`:16`) is false. | — |
| DL9 | **Script reaches into the store.** `scripts/backfill_sf_urban.py:260` runs raw SQL through `engine.evidence_store._conn`. | — |
| DL10 | **Cross-domain coupling.** ai's FRED client is a re-export of macro's (`ai_regime_v1/ingestion/fred_client.py:44`); `app.py` uses macro's private `_weekly_backfill_dates` for all FRED domains. | — |
| DL11 | **Hidden cost: same series fetched separately per domain.** `BAMLH0A0HYM2` (mr, cc, sd), `DEXUSEU` (mr, cr, sd), `UNRATE` (mr, er, lm), plus `WALCL`, `CPIAUCSL`, `DCOILWTICO`, `INDPRO`, `DTWEXBGS`, `PRS85006092`. Measure request counts before deciding to share; not in scope. | — |
| DL12 | Stale docs referencing removed domains: "Wider explore band than agriculture domains" (`macro_regime_v1/domain.py:369`), "corn NASDAQClient" (ai yfinance `:31`), `CornPriceUp` (`app.py:464`); macro `fetch_evidence` says it raises `IOError` if all series fail (`pipeline.py:592-595`) — it never does. | — |
| DL13 | Crypto's `async with cg, fred:` never enters `yf_client` (`app.py:728, 2471`); harmless only because its `aclose` is a no-op. | — |

**Cost of change today:** FRED retry policy → 8–10 files. New FRED domain →
~1,000 copied lines + 9 edits in `app.py` + `WEEKLY_DOMAIN_IDS` (forgetting the
last silently gives the domain daily manual triggers). Weekly cadence → 9
`_last_friday` + 10 `_weekly_backfill_dates` + 9 Monday loops + `agriculture_weekly` + 1 test.

### 3.6 Error handling

| ID | Finding | Evidence |
|----|---------|----------|
| E1 | 73 broad `except Exception` handlers in `src/` (17 followed by `pass`): app.py 10, sfgov 6, coingecko 6, gdelt 4, every scheduler 2, every FRED client 1, inference 3, learning 2. | `grep -rnE "except( Exception)?( as \w+)?:" src` |
| E2 | Inference returns errors as data: `_query_candidate` catches everything and returns `{"posteriors": {}, "error": str(e)}` (`inference.py:113-118`); per-variable failures fall back to uniform (`:102-104`); `check_model()` failures are ignored (`:164-167`); `_encode_value` maps unknown values to state 0 (`:246-251`). The narrative snapshot then turns any failure into `prob = 0.5` (`app.py:1769-1770`). A broken model looks like "maximally uncertain". | — |
| E3 | `accumulate_em` silently drops to a uniform E-step if the pgmpy build fails (`learning.py:361-362`). | — |
| E4 | `_resolve_query_candidate` returns the dominant candidate when given a malformed ID instead of 400 (`app.py:654-658`); reads a `label` attribute that does not exist (`:650`). **The live frontend depends on this:** `epistemic-monitor` sends `candidate_id: 'cand-004'` (a mock-data label) from `BeliefGraph`, `EdgeExistencePanel`, `ExplorationFrontier`. Making it a 400 needs a matching frontend change first. | `epistemic-monitor/components/BeliefGraph.tsx:101-107` |
| E5 | Report cache read/write failures are logged and ignored (`report.py:107-121`); a failed write means every refresh pays for a new LLM call. | — |

### 3.7 Tests

**Current result on this machine** (fresh Python 3.12 venv, because the
committed one can't run): **345 passed, 26 failed, 40 errors, 9 skipped**, 13 s.
All 66 failures/errors have one cause:
`ModuleNotFoundError: No module named 'art_prestige_regime_v1'`. `lifespan`
always builds the art engine, so **every test that starts the app through
`TestClient` fails**. The README's "370 passed" holds only where the sibling
repo is checked out. The 9 skips need a second sibling directory
(`../probabilistic_ontology_engine_abductive/artifacts`). Speed is fine; the
slowest test takes 1.08 s.

| ID | Finding | Evidence |
|----|---------|----------|
| T1 | **There is no safety net for the API today.** Apart from `/v1/report/*` (tested without lifespan), no route has a passing test on a fresh clone. `/health`, `/runtime`, startup backfill, and scheduler start are never exercised: every test sets `EVIDENCE_SCHEDULER_ENABLED=false`. | — |
| T2 | **The spec tests exist, but L3-03 is weaker than the spec.** TEST-L1-01..04, L2-01..05 and L3-01..06 exist and pass. TEST-L3-03 (`tests/level3/test_population.py:186`) falls short in four ways: it uses a hand-wired service stack, not the engine; `T_alt` is seeded in the starting population, so it tests *picking* the new structure, not *finding* it; it checks after 300 records where the spec says within 200 (`SPEC.md:1377`); and its final assertion is a loose OR (`:248`). **TEST-INT-01..04 (SPEC §20.5) don't exist.** INT-03 (replay is reproducible) is exactly the golden test this refactor needs. | — |
| T3 | **The learn loop is re-implemented in tests.** `level3/test_population.py:51-102` and `integration/test_paradigm_shift_events.py:45,73` each re-implement `engine.learn`'s loop. They won't notice if the refactor changes what `engine.learn` does. | — |
| T4 | **Tests patch module paths, which is brittle.** `monkeypatch.setattr(api_app, "_fetch_evidence_record", …)` appears in 7 files. If the function moves, or a caller imports it by name, the patch silently stops applying and tests hit the network. `test_report_cache.py` patches `src.engine.api.app.narrative_snapshot` and `report.generate_report` by path (11 sites). `app.state.engines[...]` is read directly in 6 files. | `test_api_ingest_trigger.py:52,112`; `test_report_cache.py:193-460` |
| T5 | **Tests reach into private names.** About 60 private imports across 16 files: `_soft_bool`, `_sigmoid`, `_compute_*`, `_empirical_mi`, `_make_edge`, `_candidate_edge_sig`, `store._conn`, `engine._learn_*.clear()`, `client._get_company_facts`. Merging the 10 `_soft_bool` copies breaks about 10 import blocks. | e.g. `test_credit_cycle_ingestion.py:48-53` |
| T6 | **The ingestion tests are copy-paste.** 10 `test_*_ingestion.py` files, 195 tests, 5,160 lines (47% of test code), follow one template of about 13 tests. credit-cycle vs labor-market differ in 315 of 689 lines. The domain-contract checks should be one parametrized test; signal tests stay per domain. | — |
| T7 | **Isolation leaks.** `test_narrative_snapshot.py:67-70` writes `os.environ` in a module fixture and never restores it, so later tests pass only because of the leaked `POE_DATA_DIR` (run alone, they would write 11 `.db` files into the cwd). `lifespan` calls `load_dotenv()`, which loads a developer's `.env` into the test session. NS-11 (`:300-310`) posts `/v1/ingest/trigger` without patching the fetch: it calls real EIA/NOAA if keys exist, and otherwise `pytest.skip`s, which hides the failure. | — |
| T8 | **Gaps.** `services/inference.py`, `structure_diagnostics.py`, `stores/evidence_store.py`, and `api/poea_dynamic.py` have no direct tests; their only coverage is through routes that currently error or skip. 7 of 10 schedulers (~730 lines) are untested. | import analysis |

---

## 4. Correctness bugs found during review

Fix each in its own commit, failing test first, **before** the code it lives in
is moved (so the fix is easy to review) — except where noted.

| ID | Bug | Impact | Evidence |
|----|-----|--------|----------|
| B1 | **Restart loses state and miscomputes scores.** (a) Soft-evidence `probabilities` keys round-trip through `EvidenceStore` as strings: `{True: .64}` → `{"true": .64}` (Pydantic JSON mode). `_restore_candidate_scores` then scores every soft observation against CPT rows keyed by `True`, so it finds zero counts. All 10 live domains emit `SOFT_OBSERVED`. (b) Variants, pruned status and generation are not restored (P2, P3). | Verified with `test-domain-v1`, 30 soft batches → restart: generation 65→0, pruned `T*`/`T_alt` reactivated, `null` score −1034.6 → −7060.5, `T*` and `T_alt` get identical scores. After every Railway redeploy the dominant hypothesis and paradigm-shift history are effectively reset. | `evidence_store.py:41-43, 199-205`; `engine.py:148-198` |
| B2 | **Domain edge-pruning thresholds are ignored** (C6). Every domain prunes at the default 0.05 regardless of its `existence_thresholds()`. | Domain tuning has no effect; API "explore band" display and pruning disagree. | `engine.py:59` |
| B3 | **`POST /v1/inference/query` ignores `candidate_id`, `conditions`, `aggregation`.** The graph is built from the requested candidate but `target_probability` comes from the *dominant* candidate (`InferenceService.query` with `ACTIVE_ONLY` always uses `population.dominant()`). `conditions` and `aggregation` are accepted and never read. | Wrong probability shown when a non-dominant candidate is selected. | `app.py:1478-1499`; `inference.py:43-49` |
| B4 | **TOP_K aggregation underflows.** Weights are `exp(raw log_score)`; at realistic scores (−1000s) every weight is 0.0 and merged posteriors are all zero. Not reachable from the API today. | Latent. | `inference.py:62-65` |
| B5 | ~~Bug~~ **Dead code (corrected in Phase 1):** `{v: 1.0 / 2 for v in pv.support}` (`learning.py:224`) is the fallback of `soft_obs.get(pn, …)`, but the forward pass has already filled `soft_obs` for every variable, so it never runs. Replace with `soft_obs[pn]` in Phase 2.1. | None today. | — |
| B6 | Shift-event write failure is logged and the learn cycle continues (`population_manager.py:467-473`), so the shift log can silently miss events. Becomes moot once learn runs in one transaction (Phase 3). | — | — |
| B7 | **Evidence dedup never fires.** Every pipeline sets `evidence_id=uuid4()`; the store dedups with `INSERT OR IGNORE` on `evidence_id`. So re-running a trigger or backfill for a date that is already stored appends a duplicate and learns it twice. The `after > before` guards in `app.py:784-789, 2230-2235` are always true. | Double-counted evidence after any manual re-run or overlapping backfill. | `evidence_store.py:44-60`; `*/ingestion/pipeline.py` |
| B8 | **Weekly timestamps depend on the entry point** (DL2): Sunday via the API, Friday via the scheduler, any weekday for mr/ai via the API; daily backfill of weekly domains, and of the monthly art domain (G7 snapshot `g7_calendars_api.json`). | Duplicate and oversampled weeks. | `agriculture_weekly.py:36`; `app.py:766-772, 1294-1297` |
| B9 | **Upstream outage is learned as real evidence** (DL7). | CPTs drift toward independence during outages. Fix decided in D10. | — |
| B10 | **Look-ahead in backfills.** FRED is fetched without vintages and monthly series are dated by period start, so a backfill for 2026-09-04 sees September CPI (published in October). EDGAR filters by period end, not filing date. Worst case: `scripts/backfill_sf_urban.py:248` caches every FRED series with `end_date=today` and serves it to every historical week. | Backfilled history uses data that did not exist yet. Out of refactor scope except the script (D11). | — |
| B11 | **`backfill_sf_urban.py` is not idempotent.** Its "already exists" check compares `'<date> 00:00:00'` against stored `isoformat()` (`…T00:00:00+00:00`), so it never matches. | Duplicates on every run. Don't run it until fixed or retired. | `scripts/backfill_sf_urban.py:260-265` |
| B12 | `fetch_businesses` ignores `end_date` (DL4). | Future data in historical SF records. | `sfgov_client.py:213-219` |
| B13 | **Fixed (Phase 4).** **Confirmed live (2026-10-05): SF data truncated.** August 2026 had 8,330 incidents, 1,631 permits and 1,070 business starts. The queries cap at 2,000 / 1,000 / 2,000 rows `ORDER BY … DESC` with **no upper date bound**, so incidents cover ~1 week and permits < 1 month, and `_monthly_zscore` (needs 3 months) returns `None` → 0.5. Historical backfills are worse: the newest rows come back and are then dropped as after `end_date`. Fix in Phase 4 (sf_urban first): server-side monthly aggregation (`$select=date_trunc_ym(...), count(*)`, `$group`, bounded `$where`) instead of raw rows. | Crime, permits, startups signals effectively constant. | `sfgov_client.py` |
| B14 | `credit_cycle_v1/scheduler.py:77` `asyncio.run(_main() if False else None)` raises. | Standalone entry point broken. Deleted in Phase 5 anyway. | — |
| B16 | **Fixed (Phase 1).** SF Open Data moved: `data.sfgov.org` answers every request with 301 → `data.sf.gov`; httpx doesn't follow redirects and the client returns `[]` on error, so all SFGov signals were 0.5. The `-m live` tests caught it; they never run in CI. | All 4 SFGov-based SF signals constant. | `sfgov_client.py` |
| B17 | **Fixed (Phase 1).** GDELT allows 1 request / 5 s and answers faster callers with HTTP 200 + a plain-text notice (not JSON → `[]`). `fetch_all` fired 4 queries concurrently. | Geopolitics GDELT signals mostly 0.5. Live re-check pending (the review's probe tripped GDELT's penalty window). | `gdelt_client.py` |
| B15 | **Fixed (Phase 1).** `_compute_refinancing_stress` pairs DGS5 and HY observations by list index, not by date. | Misaligned series whenever release calendars differ. | `credit_cycle_v1/ingestion/pipeline.py:186-192` |
| B19 | **Fixed (Phase 4), found while fixing B13.** `OfficeVacancyFalling` classified permits by `permit_type`, a numeric code ("8", "3") that never matched the commercial keywords. Now uses `proposed_use` ("office" is ~11% of permits). Signals also compare complete months only; the month in progress biased every count z-score low. | Office-vacancy signal was a constant 0.5. | `sf_urban_v1/ingestion/pipeline.py` |
| B20 | **Open, found 2026-10-13 (D4).** Missing values bias learning toward independence. `accumulate()` imputes a missing variable from its parents only, never from its observed children, so a child's counts are spread across parent rows by the prior. TEST-L1-04, now run on this path, learns C(T\|A=T,B=T) = 0.80 instead of 0.95 with 30% missing (bound 0.12). | Matters more since D10: unavailable inputs are now MISSING. Live weekly records are mostly complete, so the effect there is small. | `learning.py` `_accumulate_mean_field` |
| B21 | **Fixed 2026-10-13, found while doing D6.** `score_weights` softmaxed per-record averages, which differ by hundredths of a nat, so every candidate got about the same weight: `structure_entropy` ≈ ln(10) = 2.30 on every domain (narrative always "not converged"), and TOP_K / WEIGHTED_AVERAGE ≈ a plain mean including the null graph. Now n × score (BIC posterior). | Dashboard entropy and its narrative were meaningless. | `model/scoring.py` |
| B22 | **Fixed 2026-10-13, found while moving art onto GDELT.** GDELT answers `{"timeline": [{"series": "<name>", "data": [...]}]}`; the geopolitics client iterated `"series"` (the name string), so every timeline parsed as empty. Its test mocked the same wrong shape. Also, each client kept its own 5 s timer and every fetch opens a new client, so the per-IP limit was not really respected. Now `domains/sources/gdelt.py` with one process-wide limiter. | Geopolitics' four GDELT signals were 0.5, then MISSING, in production. | `geopolitics_v1/ingestion/gdelt_client.py` |
| B23 | **Art evidence (2026-10-13).** The art domain learned only from hand-picked, LLM-labelled articles (218 True / 6 False; one report counted 25 times; confidence ignored; undated items dated "now"); its live fetch never produced data (JS-rendered auction pages, a `peak < 40` Trends rule that cannot fire, an "AI" keyword that matched "painting"). Now: reports under explicit rules (`reports.py`), plus three fetched series (`ingestion/pipeline.py`): AIImageSaturation (GDELT AI-generated-art coverage share), MuseumAcquisitionMomentum and CraftPrestigeRising (Art Institute of Chicago acquisitions by distinct artist, annual). Considered and left out as too weak: Wikipedia views of the AI tools (peaked 2022–23, falls as they become ordinary), figurative subject-tag shares (tagging campaigns and lag), Wikipedia views of Academic_art / Embodied_cognition / Digital_detox / biennials, top-100 concentration for AttentionFragmentation (25 calls per month), Cleveland acquisitions (needs a 69-page dump; a good second museum to add). No free machine-readable auction data exists, so the 7 market variables are reports-only. | Art beliefs reflected what was collected, not what happened. | `domains/art_prestige_regime_v1/` |
| B24 | **Fixed 2026-10-17, found in the first production art rebuild.** Each month of a rebuild sent its own five-year GDELT request (36 of nearly the same data), and GDELT answered most from Railway with 429 even at one per 5 s; each refusal dropped the month's only fetched variable. The rebuild also outlasted Railway's 5-minute request limit (502). Now: throttled requests back off and retry (30/60/120 s, shared by every client), every month asks the same full-history question so a process-wide timeline cache answers it once, and the rebuild runs in the background (`GET /v1/ingest/art/rebuild` for its state). | The first rebuild learned 10 of 36 months. | `domains/sources/gdelt.py`, `art_prestige_regime_v1/ingestion/pipeline.py`, `api/routers/ingest.py` |

---

## 5. Target architecture

### 5.1 Layers and the dependency rule

Arrows point down only. A layer imports only the public names of the layers
below it. Enforced in CI (§6).

```text
 api/          HTTP: routers, request/response DTOs, presenters (view logic)
   │
 runtime/      composition root: Settings, DomainRegistry, app factory,
   │           ingestion use cases (ingest+learn, backfill), scheduler loop
   │
   ├────────────────────┐
 engine.py   (facade)   domains/<name>/   domain definition + evidence source
   │                        │
 services/   pure logic     sources/        shared external-API clients + calendars
   │                        │
 model/      schemas, CPT ◄─┘   (domains depend on model, never on services/engine)
   │
 stores/     SQLite repositories + migrations (depend on model only)
```

Rules:

- `model/` and `services/` do no I/O and read no env vars. They take data and
  return data. (`pgmpy`, `networkx`, `numpy` are fine.)
- `stores/` is the only code that knows SQL or JSON column layouts.
- `engine.py` is the only code that combines services and stores. Its public
  methods are the only way the outer layers touch engine state.
- `domains/` never imports `engine`, `services`, `stores`, `runtime`, or `api`.
- `api/` never imports `domains/`, `stores/`, or `services/` directly — it gets
  everything through `runtime` and the engine facade.
- Only `runtime/settings.py` reads `os.environ`.

### 5.2 Package layout (after)

Keeps the `src/engine/...` and `src/domains/...` structure that `CLAUDE.md`
prescribes; adds `model/`, `runtime/`, `api/routers/`, and `domains/sources/`.

```text
src/engine/
  model/
    schemas.py            # Pydantic models only — no scoring, no networkx calls in methods beyond graph helpers
    cpt.py                # CPTData (moved from stores/parameter_store.py) + parent-config key, add_fractional()
    domain.py             # DomainModule Protocol, EvidenceSource Protocol
    cadence.py            # Cadence: pure calendar math shared by runtime/scheduler and domains
    errors.py             # EngineError, UnknownVariable, EvidenceUnavailable, ...
  services/
    scoring.py            # NEW: the one candidate score (BIC-average), weights, entropy
    bn_model.py           # NEW: candidate+CPTs → pgmpy model (one copy, used by inference & EM)
    learning.py
    edge_existence.py
    population_manager.py
    inference.py
    explore_exploit.py    # kept only if §8 D3 says wire it up
    diagnostics/          # evidence_diagnostics, evidence_geometry, structure_diagnostics (pure)
  stores/
    database.py           # one connection per DB file, transaction() context manager, migration runner
    migrations/0001_initial.sql, 0002_persist_population.sql, ...
    evidence_repo.py, parameter_repo.py, population_repo.py
  engine.py               # DomainEngine: one domain, one Database
  variable_identity.py    # stable_variable_id only (position-fallback shim deleted after migration)
  runtime/
    settings.py           # Settings dataclass built from env, once
    registry.py           # DomainRegistration list — the ONE place domains are listed
    ingestion.py          # ingest_and_learn(), backfill() — one copy each
    scheduler.py          # one generic scheduler loop driven by Cadence
    app_state.py          # Runtime: engines, locks, read models; built at startup
  api/
    app.py                # create_app(): FastAPI(), CORS, routers, lifespan → runtime  (~100 lines)
    deps.py               # get_domain(), get_read_model() FastAPI dependencies
    dto.py                # response/request models (moved from app.py)
    presenters.py         # candidate status, normalized scores, frontier, P(True), time_ago
    read_models/
      base.py             # PopulationReadModel Protocol
      engine_read_model.py    # apriori: built on DomainEngine
      poea_read_model.py      # dynamic: today's poea_dynamic.py
    routers/population.py, inference.py, evidence.py, ingest.py, debug.py, report.py
    report/               # report.py split: cache.py (I/O), llm.py (Fireworks), sanitize.py (pure)
src/domains/
  sources/                # shared clients, only where ≥3 copies prove the shape (see §3.5)
  <domain>_v1/domain.py, signals.py (pure), source.py (fetch), series.py (data) — see Phase 4
```

### 5.3 Key interfaces

These are the barriers. Everything else is free to change behind them.

```python
# model/domain.py
class DomainModule(Protocol):
    def module_id(self) -> str: ...
    def initial_candidates(self) -> list[OntologyCandidate]: ...
    def existence_thresholds(self) -> EdgeExistenceThresholdConfig: ...
```

Only the three methods the engine actually calls. The stub methods
(`initial_entities`, `initial_assertions`, `variable_specs`,
`initial_parameterizations`) that return `[]` are dropped from the contract —
this is a deliberate, flagged deviation from SPEC §8 (see §8 D5).

```python
# model/cadence.py — one copy of the calendar math
Cadence = Daily | Weekly(anchor: Weekday) | Monthly
    # default_target(now), backfill_targets(window, today), next_run(now, hour)

class EvidenceSource(Protocol):
    cadence: Cadence
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc) -> None: ...
    async def fetch(self, target: date) -> EvidenceRecord:  # raises EvidenceUnavailable
        ...
```

```python
# runtime/registry.py — the single list of domains
@dataclass(frozen=True)
class DomainRegistration:
    key: str                    # "mr"
    display_name: str           # "Macro Regime"
    db_filename: str            # "macro_regime.db"  (keep current names)
    env_prefix: str             # "MACRO_REGIME" → MACRO_REGIME_RUN_HOUR_UTC, _BACKFILL_WEEKS (keep current names)
    required_env: tuple[str, ...]          # ("FRED_API_KEY",)
    build_domain: Callable[[], DomainModule]
    build_source: Callable[[Settings], EvidenceSource]
    optional: bool = False      # art: skip with a warning if its package is missing

REGISTRY: tuple[DomainRegistration, ...] = (...)
```

`_DOMAIN_MAP`, `_require_domain_env`, `_fetch_evidence_record`, the 11
`_run_*_scheduler` functions, the per-domain lock dict, and the lifespan engine
list all collapse into loops over `REGISTRY`.

```python
# engine.py — the facade the outer layers use
class DomainEngine:
    def __init__(self, domain: DomainModule, db: Database, *, seed: int = 42): ...
    # commands
    def ingest(self, records: Sequence[EvidenceRecord]) -> int        # returns newly stored count
    def learn(self, records: Sequence[EvidenceRecord]) -> LearnResult  # one transaction
    # queries
    def population(self) -> PopulationView          # read-only view, scores precomputed via scoring.py
    def thresholds(self) -> EdgeExistenceThresholdConfig
    def query(self, q: InferenceQuery) -> InferenceResult             # raises on failure
    def evidence_count(self) -> int
    def recent_evidence(self, limit: int) -> list[EvidenceRecord]
    def latest_evidence_at(self) -> datetime | None
    def shift_events(self, limit: int | None = None) -> list[ParadigmShiftEvent]
    def learning_stats(self) -> LearningStats       # replaces engine._learn_* access
    def mutation_stats(self) -> MutationStats
```

No `active_domain`, no `_modules`. Methods that hit the database say so in
their docstring (a barrier may hide representation, not a round trip).

```python
# services/scoring.py — the one score
def candidate_score(c: OntologyCandidate, *, bic_multiplier: float = 1.0) -> float
def score_weights(cs: Sequence[OntologyCandidate]) -> list[float]
def structure_entropy(cs: Sequence[OntologyCandidate]) -> float
def dominant(cs: Sequence[OntologyCandidate]) -> OntologyCandidate | None
```

Used by population ranking, variant parent selection, inference aggregation,
diagnostics, and presenters. Moving `introduce_variants` and TOP_K onto it is a
behavior change → its own commit (fixes C1/B4).

```python
# model/cpt.py — learning stops touching .counts
class CPTData:
    def config_key(self, parent_assignment: Mapping[str, Any]) -> ParentConfig
    def add(self, value, parent_assignment, weight: float = 1.0) -> None   # replaces increment + manual dict writes
    def probability(self, value, parent_assignment) -> float
    def row(self, parent_assignment) -> Mapping[Any, float]                # read-only
    ...
```

```python
# api/read_models/base.py — replaces the 7 `if ontology_mode == "dynamic"` branches
class PopulationReadModel(Protocol):
    def status(self) -> PopStatusOut
    def candidates(self) -> CandidatesOut
    def inference(self, body: QueryBodyIn) -> InferenceOut
    def lineage(self, candidate_id: str) -> LineageOut
    def shifts(self) -> ParadigmShiftsOut
    def snapshot(self) -> NarrativeSnapshotOut
    def recent_evidence(self, limit: int) -> EvidenceOut
```

Two implementations exist today (apriori, dynamic), so this abstraction is
earned, not speculative. `ontology_mode` becomes `Literal["apriori","dynamic"]`;
unknown values → 422.

### 5.4 Runtime behavior

- **Startup**: `Settings.from_env()` once → for each registration, build
  domain + engine; an `optional` registration whose import fails logs a warning
  and is absent (404 on its routes) instead of crashing the app. Missing API
  keys disable that domain's scheduler with a log line, never crash startup.
- **Ingestion**: one `ingest_and_learn(engine, source, target)` use case; one
  `backfill(engine, source, dates, sleep)`. Scheduler, startup backfill, manual
  trigger, and manual backfill all call these and **all take the domain lock**
  (fixes A11).
- **CPU work**: `engine.learn` / `engine.query` run via `asyncio.to_thread`
  while holding the domain lock (fixes A10). Safe because one lock serializes
  access to each engine's single connection.
- **Errors**: sources raise `EvidenceUnavailable` (with source + series id);
  core raises `EngineError` subclasses. Only two places catch broadly: the
  backfill/scheduler loop (log per target, continue) and a FastAPI exception
  handler (map to 502/503/422). Everything else propagates.

---

## 6. Guardrails (so it does not regrow)

The refactor is wasted if nothing stops the next feature from re-tangling it.

1. **Import contracts in CI** with `import-linter` (new dev dependency; stdlib
   has no equivalent and a hand-rolled AST check is more code to maintain).
   Contracts: the layer order in §5.1; `domains` independent of `engine.engine`,
   `engine.services`, `engine.stores`, `engine.runtime`, `engine.api`; `api`
   forbidden from `domains`, `engine.stores`, `engine.services`.
2. **No private reach-through**: a ruff rule `SLF001` (private member access)
   enabled for `src/` (ruff is a new dev dependency — it replaces nothing today
   because there is no linter at all).
3. **File size budget**: a test fails if any `src/**/*.py` exceeds 600 lines.
   Today `app.py` is 2,610.
4. **No broad excepts outside the two allowed boundaries**: ruff `BLE001`
   enabled, with `# noqa: BLE001` only in `runtime/ingestion.py` and the API
   exception handler.
5. **Performance budget tests** from SPEC §20.7 (learn batch=50 < 2 s, inference
   ≤20 vars < 200 ms, ingest < 50 ms/record), plus restart replay of 5,000
   records < 2 s. These fail CI rather than relying on someone noticing.
6. **CI**: `uv sync --frozen && uv run ruff check && uv run lint-imports && uv run pytest`
   on every PR. There is no CI today.
7. **Scheduled live checks.** B16 and B17 were silent upstream breakages that
   only `-m live` tests catch, and nothing runs them. Add a weekly CI job
   running `pytest -m live` with the API keys as secrets, and extend live
   tests to every domain (NEXT.md #2).

---

## 7. Plan

Each step is one PR unless noted. "Exit" is what must be true to merge.

### Phase 0 — Safety net (no behavior changes) — **done**

Result: suite 345 passed / 66 failed / 9 skipped → **448 passed, 0 failed,
9 skipped** (POE-A artifacts only). Golden snapshots G1–G7 in `tests/golden/`.
Not verifiable locally: the CI workflow (needs a push) and the Railway build
(only the art tarball URL changed, to the same commit as `main`).

0.1 **Hygiene.** `git rm -r --cached .venv` and all tracked `*.pyc`; add
`uv.lock` (`uv lock`), move `dev` extras to `[dependency-groups]`, pin pgmpy to
the installed major version; fix `CLAUDE.md` SPECM→SPEC; move one-off audit docs
to `docs/archive/` (since deleted; they are in git history). (H1–H3, H5, H6)
Exit: fresh clone → `uv sync && uv run pytest` runs on macOS and Linux (passing is 0.2’s exit).

0.2 **Make the existing suite run on a fresh clone.** Declare `art-market-domain`
as a dependency pinned to a commit (it is already a runtime dependency, just
undeclared), and move the six nixpacks-only packages into `pyproject.toml`.
`nixpacks.toml` then just runs `uv sync --frozen`. Seal the tests: replace the
`os.environ` writes in `test_narrative_snapshot.py` with `monkeypatch`; patch
the fetch in NS-11; skip `load_dotenv` under tests (env flag). (H3b, T1, T7)
Exit: 0 failures, 0 errors; skips only for the POE-A artifacts.

0.3 **Golden tests.** Pin today's behavior at public seams only. They live in
`tests/golden/` and use committed JSON snapshots. Key everything by edge
signature, not UUID (IDs are `uuid4`), and strip wall-clock fields.

- **G1 Engine replay** (= SPEC TEST-INT-03). `ProbabilisticOntologyEngine(":memory:", random_seed=42)`
  on `test_domain_v1`, `SyntheticDataGenerator("T*", seed=42)`. Feed 300 records
  through `engine.learn` in batches of 30, `switch_regime("T_alt")`, then 300
  more. After each batch, snapshot: `population_status()`; per candidate
  `(signature, log_score, evidence_count, status, generation)`; edge existence
  probabilities of the dominant candidate; `parameter_hash` per candidate; a
  marginal query for each variable. Also assert that two runs give identical results.
- **G2 L3-03 through the engine facade**, asserting the shift happens within
  200 records of the switch (SPEC §20.4). Checked during review: through the
  facade, the dominant flips from T* to an A→D structure in the **first** 30-record
  batch after the switch (1 shift). So G2 passes today. It still seeds T_alt, so
  it tests picking, not discovering, the new structure (T2). Keep that scope;
  discovery is a feature, not a refactor.
- **G3 Restart round-trip.** Same run against a temp `db_path`; rebuild the
  engine on that file; snapshot status/scores/hashes. Today this pins the
  **buggy** behavior (B1) on purpose. Phase 3 flips the assertion to "equal
  before and after".
- **G4 API contract.** A fixture builds the app with a fake evidence source
  injected at **one** seam (until Phase 5 that seam is `_fetch_evidence_record`;
  afterwards the registry's `build_source`) and a fixed clock. For every domain
  key, snapshot the response shape plus normalized values of every route:
  population status/candidates/shifts/lineage, evidence/recent,
  narrative-snapshot, all 4 debug routes, inference/query, health, runtime.
  Plus one snapshot of `app.openapi()` (cheapest guard on the contract, SPEC
  TEST-INT-02).
- **G5 Error paths.** Unknown domain → 404; non-UUID candidate id (today:
  silently uses the dominant, see E4); `ontology_mode=dynamic` fallback; report
  502/503.
- **G6 Domain contract**, parametrized over all domain modules: `module_id`,
  stable variable ids, DAG seed candidates, thresholds, and a golden of
  `build_evidence_record(compute_snapshot(fixed_observations))` per domain.
  This pins the pipeline math through public functions, so Phase 4 can merge
  the private helpers without breaking tests (T5).
- **G7 Calendars.** Pure-function goldens of target/backfill dates for every
  domain and every entry point (scheduler, trigger, manual backfill). These
  document B8 before the fix.

Then, so the refactor doesn't trip over them: rewrite the T3 hand-wired loops
to call `engine.learn` — **deferred to Phase 2**: they need a configurable
population size (TEST-L3-05 uses 5; the engine hard-codes 10) and per-domain
thresholds, which the engine ignores (B2), so they can only move once
`DomainEngine` exists; G1/G2 already cover the facade; replace module-path patches (T4) with the G4 injection
fixture; move private-helper imports (T5) onto G6 where they test pipeline
math. Collapse the 10 ingestion test files' shared template into G6 in Phase 4,
not now.

0.4 **CI** runs the suite (§6.6). Linters come in Phase 6, not now, so they
don't block Phase 1–5 PRs with unrelated noise.

### Phase 1 — Bug fixes that must land before code moves

**Done.** Landed: B2, B3, B7, B12, B15, DL3, plus B16 and B17 found during the
phase. Not landed: B5 (dead code, moved to 2.1), the 422 for
`conditions`/`aggregation` (would break the frontend, see D6), B13 (Phase 4).

Original plan: one commit each, failing test first: B2 (thresholds), B3 (inference query uses
the requested candidate; reject unknown `conditions`/`aggregation` with 422
until implemented — see D6), B5, B7 (the ingest path skips a record whose
`(domain, timestamp)` is already stored; Phase 4.5 makes it structural), B12,
B15, DL3 (keep tracebacks). B13 after a live check. B1 is fixed in Phase 3
because it needs the new persistence. B9 is fixed after Phase 4 (D10); B10 depends on D11.

### Phase 2 — Core barriers (pure code, no I/O changes) — **done except 2.3, 2.7**

Landed: 2.1 (`model/cpt.py`; nothing outside it touches `.counts`), 2.2 (one
score — placed in **`model/scoring.py`**, not `services/`, because
`OntologyPopulation.dominant()` needs it and the art package calls that),
2.4 (`services/bn_model.py`), 2.5 (`model/errors.py`; inference raises, API
maps to 422/500), 2.6, and B4 from 2.3. **2.3's variant-parent change is
parked** on `refactor/2.3-variant-parents-parked` (D14). 2.7 waits on D3/D4.
T3 (hand-wired level-3 harness) moves to Phase 5.2, where `DomainEngine`
gains the `max_population_size` it needs. Also found and parked with 2.3:
B18, `introduce_variants` starts at `survivors[1]`, so the first variant
comes from the second-ranked survivor.

2.1 Move `CPTData` to `model/cpt.py`; add `config_key`, `add(weight)`, `row`;
rewrite learning to use them; no direct `.counts` access outside `cpt.py`. (C2, C3)
2.2 Extract `services/scoring.py`; delete both `_avg_score` copies; API and
diagnostics call it. Pure move — keep raw-score sites as they are. (C1)
2.3 Behavior commit: variant parent ranking and TOP_K use `candidate_score`. (C1, B4)
2.4 Extract `services/bn_model.py` (one pgmpy build); inference and EM use it;
no cross-module private imports. (C4)
2.5 Error policy in inference: raise instead of `{"error"}` / uniform fallback;
`_encode_value` raises `UnknownValue`. API maps to 422/500. (E2)
2.6 Name fixes: `_MIN_RECORDS_FOR_PRUNING`, `parent_names_json` (column rename
goes in a migration in Phase 3), stop sharing `variables` by reference, remove
the `learning_service` flag parameter. (C7, C8)
2.7 Act on decision D3/D4: wire up or delete unused services. (C11)
Exit: golden tests unchanged except where a behavior commit says why.

### Phase 3 — Persistence — **done**

Landed: 3.1 (`stores/database.py`, migrations `0001`/`0002`), 3.1b (portable
`ON CONFLICT` upserts), 3.2 (`learn()` is one transaction; B6), 3.3 (whole
population persisted and resumed; B1b), 3.4 (typed soft-evidence keys, legacy
rows read back correctly; B1a), 3.5 (hot-path ID shim removed), 3.6 (bounded
shift/debug reads). G3 now asserts a restart is invisible, including learning
after it. Measured: `learn()` on one record 59 ms → 6 ms (one commit per
cycle instead of one per row); register with 300 cycles of history 260 ms.

Deviation from the plan, for D1: pre-0002 databases are **not** fully
relearned. They take the old restore path once (seed CPTs from the signature
table, scores recomputed from evidence — now correct), then persist. A full
relearn costs ~60 ms per record and could exceed Railway's 300 s health
check. Variants were never stored, so neither path could recover them.
A fixture written by `main`'s code (`tests/fixtures/pre_0002_test_domain.db`)
pins this path.

Before deploying: snapshot the Railway volume (D1). Known growth: pruned
candidates stay in the population (as before) and are now also loaded on
start; and the art package's rebuild leaves orphan `candidate_edges` /
`candidate_parameters` rows until Phase 5.6 gives it a real reset.

3.1 `stores/database.py`: one connection per DB file, `transaction()` context
manager, migration runner with a `schema_version` table; migrations as `.sql`
files using portable `ON CONFLICT` syntax. `0001` reproduces today's schema
exactly. (P1, P4, P5)
3.2 Repositories take `Database`; `DomainEngine.learn` wraps the whole cycle in
one transaction; per-row commits removed. (P1, B6)
3.3 **Persist the population.** Migration `0002` adds `candidate_edges` (SPEC
§7.2 `dependency_edges`) and keys `parameters` by `candidate_id`. Engine loads
population + edges + CPTs on startup; seed candidates are used only when the DB
has no population. Score replay deleted. (P2, P3, B1b)
3.4 Store soft-evidence probabilities with typed keys (encode as a list of
`[value, p]` pairs) and migrate existing rows (`"true"`→`True` for BOOLEAN
variables). (B1a)
3.5 One-time legacy variable-ID migration in a migration file; delete the
per-call `normalize_evidence_record_variable_ids` shim. (C10)
3.6 Bound request-path reads: `recent_evidence(limit)`, `shift_events(limit)`;
debug endpoints get a `limit` (default = all, so output is unchanged). (P6)
Exit: restart golden test (Phase 0) now asserts state is **equal** before/after
restart; an old-DB fixture (copy of a real pre-migration DB) migrates cleanly and replays (D1). Snapshot the Railway volume before deploying 3.3.

### Phase 4 — Domain layer

**Done except 4.7.** Order changed: the shared runtime (5.1–5.3) landed
first, so 4.9 ("delete the schedulers") came for free.

Landed: 4.1 (`model/domain.py` `DomainModule`; 55 stub methods deleted, D5),
4.2 (`model/cadence.py`; Sunday anchor, stored Friday records restamped by
`runtime/data_migrations.py`; `agriculture_weekly.py` deleted), 4.3
(`domains/sources/fred.py`, typed `FredHTTPError`; per-domain clients are
now config subclasses), 4.4 (`domains/sources/yfinance.py`), 4.5
(`soft_evidence.py`: one `build_soft_record`; `evidence_id` is a uuid5 of
domain + timestamp + source_ref, completing B7; snapshots use `slots`, so a
misspelled field raises), 4.6 (`domains/sources/structure.py`), 4.8 and D10
(unavailable signals are `MISSING`; all-missing raises `EvidenceUnavailable`,
nothing stored), 4.9 (schedulers deleted), B13 and B19 (SF, verified live:
all five SF Open Data signals produce values for today and for 2025-06-01).
Goldens G8 (FRED), G9 (yfinance) and G10 (evidence records) pinned each merge.

Deviations: domains got `source.py` (`open_source(env)`) but not separate
`signals.py`/`series.py` files: the signal math stayed in each
`ingestion/pipeline.py`, which keeps diffs small; split it if a pipeline
grows (the size budget caps ai at 778 and macro at 663 lines).

Not done: 4.7 (natural-gas math still lives in its NOAA/EIA clients, and
natural-gas still builds its own records with `uuid4` ids, so its dedup relies
on the ingest path's timestamp check only). `scripts/backfill_sf_urban.py`
still exists and is still unsafe (B11), waiting on D11. GDELT (B17) is still
not re-checked live: GDELT keeps rate-limiting this machine's IP.

Target shape of one domain package (no `scheduler.py`; no per-domain client
copies):

```text
src/domains/<name>_v1/
  domain.py     # DomainModule: variables, seed candidates, thresholds (uses shared constructors)
  signals.py    # pure: raw series → per-variable Signal | Missing  (today's _compute_* + compute_snapshot)
  source.py     # EvidenceSource: owns its clients, fetch → signals → build_record
  series.py     # data: FRED series ids / tickers / lookbacks for this domain
```

4.1 `model/domain.py`: `DomainModule` Protocol (3 methods); delete the 5 stub
methods ×11 (D5); `DEFAULT_THRESHOLDS` constant. (DL1)
4.2 `model/cadence.py`: `Cadence` = `Daily` | `Weekly(anchor)` | `Monthly` with
pure `default_target(now)`, `backfill_targets(window, today)`,
`next_run(now, hour)`. Pure move first (each domain keeps its current anchor).
Then a behavior commit that applies the **Sunday** anchor to every weekly domain
(D12), migrates stored Friday-stamped weekly records to the following Sunday,
updates the scheduler tests, and deletes `agriculture_weekly.py`. (DL2, B8, H7)
4.3 `domains/sources/fred.py`: one client.
`fetch_series(id, end, lookback_days)`,
`fetch_many(specs, end) -> dict[str, list[Obs] | FetchError]`; raises typed
`FredHTTPError(status, retry_after)`; retry policy lives here only. Each domain
keeps its own series dict in `series.py`. Delete 8 copies + ai's re-export. (DL8, DL10)
4.4 `domains/sources/yfinance.py`: one client, tickers + lookback as arguments. Delete 3 copies.
4.5 `domains/sources/soft_evidence.py` (pure): `sigmoid`, `soft_bool(signal, clamp)`
(clamp passed in — geopolitics deliberately uses 0.05/0.95), `zscore`,
`build_record(module_id, variables, signals, timestamp, source_ref)`. Replaces 9
`build_evidence_record` templates and the `_apply`/`setattr` pattern; a typo
in a variable name becomes a `KeyError` at build time. `build_record` derives
`evidence_id = uuid5(module_id, timestamp, source_ref)` so the store's
`ON CONFLICT DO NOTHING` dedups for real (completes B7). (DL6)
4.6 `domains/sources/booleans.py`: `boolean_variables(module_id, names)`,
`edge(vars, parent, child, prior, label)` for the `domain.py` boilerplate.
4.7 Natural gas: move `hdd`/`temp_anom`/`heating_dem`/`price_up`/`storage_draw`
math out of `NOAAClient`/`EIAClient` into `natural_gas_v1/signals.py`. (DL5)
4.8 Each source raises `EvidenceUnavailable` when **all** of its inputs fail.
Partial failures stay as today (0.5) during Phase 4 so golden records don't move.
After Phase 4, a separate behavior commit makes `build_record` emit `MISSING` for
unavailable signals (D10, B9), re-runs G1/G2, and updates their snapshots with a
written comparison of dominant histories. (DL7)
4.9 Delete per-domain `scheduler.py` (10) once Phase 5.3's generic scheduler
lands. Fix `scripts/backfill_sf_urban.py` on top of the shared backfill or
delete it (D11). (DL9, B11, B14)

Each domain's PR first adds a pipeline golden at the HTTP layer (canned
upstream responses via `httpx.MockTransport`; `yf.download` stubbed for
yfinance) through the public `fetch_evidence`, so client and helper merges are
checked against real request/response shapes, not mocked client methods.

Convert one domain end-to-end first (**sf_urban_v1** — it has live tests),
then macro, then the rest one PR each. Golden evidence-record tests (Phase 0)
must produce identical records per domain, except the `evidence_id`.

### Phase 5 — Runtime and API

**Done except 5.5's read-model split and the art repo's side of 5.6.** 5.8's
auth and CORS origins landed on 2026-10-13 (D7).

Landed: 5.1 (`runtime/settings.py`), 5.2 (`runtime/registry.py`, the one list
of domains; `DomainEngine` rename not done — the facade kept its name and
`activate_domain`/`_modules`, because the art package uses them), 5.3 (one
ingest/backfill/scheduler in `runtime/`; ten scheduler classes and the
runners deleted), 5.4 (`app.py` 2,610 → 155 lines: `routers/`, `dto`,
`presenters`, `context`, `narrative`; G4 unchanged), 5.5 partly
(`ontology_mode` validated, 422 on unknown values), 5.6 engine side
(`reset_domain` does the art rebuild in one transaction including the 0002
tables; `learning_stats` replaces reads of private counters), 5.7 (a missing
key or art package disables that piece, not the app), 5.8 partly (backfill
`days` capped at 1,825; art manual-ingest `path` restricted to
`POE_ART_MANUAL_DIR`; CORS no longer pairs `*` with credentials).

Not done: the `PopulationReadModel` split (the `dynamic` branches remain; low
value until a third mode exists); the art package still uses its own reset
through engine internals (`tests/test_art_compat_surface.py` guards them) —
switching it is a change in `art-market-domain`, waiting on your go-ahead;
~~POST auth and an explicit CORS origin list (D7)~~ done 2026-10-13.

5.1 `runtime/settings.py` — all env parsing, same var names. (A12)
5.2 `runtime/registry.py` + `DomainEngine` replaces `ProbabilisticOntologyEngine`
(`active_domain`/`_modules` removed). (A2, C5)
5.3 `runtime/ingestion.py` + `runtime/scheduler.py`: one ingest+learn, one
backfill, one scheduler; all take the lock; CPU work via `to_thread`. Delete the
four backfill copies, eleven runners, and the per-domain scheduler classes
(after Phase 4 confirms they hold no domain-specific logic). (A3, A4, A10, A11)
5.4 Split `app.py`: `dto.py`, `presenters.py`, `routers/*`, `create_app()`.
Pure move; golden response snapshots must not change. (A1, A7, A9)
5.5 Read models: `PopulationReadModel`, apriori + POE-A implementations;
`ontology_mode` validated. (A8)
5.6 Art domain boundary: define what the art package may call (e.g. a
`replace_evidence(records)` method on `DomainEngine` returning a result
object) and stop passing the raw engine / reading `_art_causal_prior_result`.
Requires a matching change in `art-market-domain`, released with one version of
overlap (old and new calls both supported) before the old calls are removed. (A6, D2)
5.7 Optional domains and missing keys degrade instead of crashing. (A13)
5.8 Security: explicit CORS origins from settings; shared-secret header on POST
routes; cap `days`; restrict `path` to the configured manual-ingest dir. (A14) — see D7.

### Phase 6 — Lock it in

**Done.** CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, ruff (F,
SLF001, BLE001 only), import-linter (7 layer contracts in `pyproject.toml`)
and pytest, including `tests/test_guardrails.py` (600-line file budget,
SPEC §20.7 performance budgets, resume < 2 s). README and `CLAUDE.md`
describe the new layout. CI has not run on GitHub yet (branch not pushed).

Enable the guardrails in §6 (import contracts, ruff SLF001/BLE001, file-size
test, perf budgets). Fix remaining violations. Update `README.md` and
`CLAUDE.md` project-structure section to the new layout.

---

## 8. Decisions

Status key: **Decided** (answered 2026-10-04, with the downsides we accepted) · **Open** (still needs an answer; recommendation given).

| ID | Question | Status / recommendation |
|----|----------|-------------------------|
| D1 | Can production DBs be rebuilt from stored evidence instead of keeping the current learned state? | **Decided: yes, rebuild.** Migrate evidence rows losslessly (typed soft-evidence keys, B1a; duplicates from B7 collapsed to the earliest per `(domain, timestamp)`), then replay once with the fixed code. Accepted downsides: (1) the dominant hypothesis and scores shown after the migration will differ from before. Each redeploy already reset them (B1), so nothing trustworthy is lost. (2) Old `paradigm_shifts` rows point to candidate IDs that no longer exist. Keep them; they carry names. Add a `pre_migration` flag so lineage lookups for those IDs return 404 with a clear message. (3) A one-time startup replay, measured at about 0.1 s per 300 records. Precondition: **snapshot the Railway volume before deploying Phase 3.3.** |
| D2 | Change `art-market-domain` at the same time (Phase 5.6)? | **Superseded 2026-10-13:** instead of changing `art-market-domain`, the art domain moved into this repo (`domains/art_prestige_regime_v1`), so there is no cross-repo contract left. The art repo is no longer used; nothing was changed there. |
| D3 | `ExploreExploitService` is built and tested but never used. SPEC §10.1 puts it in the learn loop. Wire it in or delete it? | **Done 2026-10-23: deleted.** The milestone reached its target without it (D14), and it would have induced hypotheses from the data, where the engine's stance is that hypotheses are conjectures and evidence only judges them. SPEC §5.2 marked superseded. D24 later reversed the stance: hypotheses are now formed from the evidence, and judged only on evidence after. |
| D4 | `LearningService.accumulate_em` is only used by one level-1 test and ignores soft evidence. Keep or delete? | **Done 2026-10-13: deleted.** TEST-L1-04 now runs the production path and fails the SPEC bound (B20), marked `xfail(strict)`. |
| D5 | Drop the never-used SPEC §8 stub methods from the `DomainModule` contract? | **Done (recommendation followed, 4.1).** |
| D6 | `POST /v1/inference/query` accepts `conditions` and `aggregation` but ignores them. **Checked:** the frontend sends `aggregation: 'weighted_avg'` from 3 components (never `conditions`), so rejecting would break the dashboard. Options: (a) keep ignoring; (b) implement `weighted_avg` — dashboard probabilities change to population-weighted; (c) reject after the frontend stops sending it. | **Done 2026-10-13: (b).** `weighted_avg` returns the population's P(target), weighted by structure posterior (after fixing those weights, B21); the graph stays the candidate's. `conditions` still unused; no caller sends it. |
| D7 | Is a shared-secret header acceptable for POST routes, and what origins should CORS allow? | **Done 2026-10-13, narrowed.** The dashboard calls `POST /v1/ingest/trigger` ("Fetch now") and `/v1/report/{d}/refresh`, and a token in a static site is public, so only the operator routes (backfill, art manual ingest) need `Authorization: Bearer $POE_ADMIN_TOKEN`; unset = 503. `POE_CORS_ORIGINS` (default `*`). Open risk: "Fetch now" can be spammed and each call hits upstream APIs; add a per-domain cooldown if that happens. |
| D8 | Learn order (C9): score each batch before updating counts (prequential), or keep today's order? | **Done 2026-10-13 (as part of D14):** prequential. It alone made T* dominant before the switch on 20/20 seeds (in-sample scoring cancelled the BIC penalty). |
| D14 | **Milestone robustness.** Fixing variant-parent selection (2.3: rank by `candidate_score`, start at the best) fails golden G2: seed 42 detects the A→D shift at 270 records (bound 200). Measured over 10 seeds, the fix is not worse than today. But the bigger finding is that today's engine is not reliable on this scenario either: T* dominant after 300 records in **4/10** seeds, shift detected within 200 records in **4/10** (with the fix: 5/10 and 6/10). TEST-L3-03 / G2 pass because seed 42 is a good seed. | **Done 2026-10-13.** Parked fix merged; then, with your go-ahead, three algorithm changes (commit 6339b543): score each batch before learning it (D8), rank by a score window with a 100-record half-life (SPEC `score_window`, migration 0003), and prune no edge before its child CPT holds 120 records. Seeds 0–39: 35/40 detect the shift within 200 records (was ~11/20); on 900 stationary records the dominant flips in ~2% of batches. TEST-L3-03 and G2 now require 16 of 20 seeds (both at 18). Live domains will rank recent evidence more, so dominant hypotheses and shift history change after deploy. |
| D15 | **Rival research programmes.** A replay of 2003–2026 through the macro domain (`evals/README.md`) found every rival seed explanation extinct within two years in every seed: pruning removes the bottom quartile and variants are bred only from survivors, so once one lineage leads early the others never return, and every later paradigm shift is one lineage refining itself. | **Done 2026-10-23.** Each candidate carries its `lineage` (the seed it descends from, persisted in `metadata`). Pruning spares each lineage's best candidate unless the leader's evidence over it is decisive: log Bayes factor (window total less BIC penalty) above ln 100, Jeffreys' scale. A refuted programme can still go (TEST-L3-02 unchanged); one short of refuted stays. Golden G1 soft and G4 (mr, cr, ng) regenerated: populations keep rivals. Populations persisted before this have no lineage and prune as before until rebuilt. |
| D16 | **Fair trial for rivals.** Replay 2 (D15) kept rival programmes until refuted, and all were refuted by 2008. But variants are bred from the best-scoring survivors first, so a rival rarely got offspring while the leading lineage kept exploring: judged without revising its auxiliary hypotheses. | **Done 2026-10-23.** Breeding starts each round with a different programme's best (best programme first, rotated by a turn counter persisted with the rng), then everyone else by score. With one programme it is plain best-first, as C1/B18 had it. Golden G1 and G4 regenerated. |
| D17 | **Crisis-sensitive doubt.** Replays 1–3 found the learned structure worse than independent signals through COVID in most seeds: CPT counts never decay, so seventeen years of evidence outweighed two years of a broken world. | **Done 2026-10-23.** `model/doubt.py`: the leader's surprise per record (negative log-likelihood, scored before learning) is tracked with the score half-life; a batch above mean + 2 sd, after 52 records, is a crisis, and every active candidate's CPT counts and score window are halved before it learns that batch. Thresholds conventional, fixed before replay 4. State persisted with the population. Golden snapshots unchanged (no crisis in them). |
| D18 | **Calibration and humility.** SPEC §13.1 lists calibration error; nothing measured it, nor whether the weighted population predicts better than its leader. | **Done 2026-10-23.** `model/calibration.py`, `services/health.py`: each cycle, before learning, the population's posterior-weighted predictive log-likelihood of the batch, and the leader's and population's leave-one-out P(variable true \| the rest) for the batch's last record, binned (Brier, expected calibration error). Changes nothing learned. `engine.epistemic_health(domain)`. |
| D19 | **Beliefs about change.** No structure could say this week follows from last; regimes are largely persistence. | **Done 2026-10-23.** A variable may have a companion holding last period's value (`Variable.lag_of`; `sources.structure.with_lags`). Nothing may point into one; records get their predecessor's values when learned (`model/temporal.lagged`), never when stored; they are never scored. Macro-regime adds `T_persistence` (each signal follows its own last week) as a sixth programme. Health adds `forecast_ll`: log P(this week \| last week only) under the leader. Golden G4 mr, G6 regenerated. A live population persisted before this has 8 variables and must be rebuilt. |
| D20 | **Five ordered levels.** A boolean signal can say only which side of its threshold the world is on, not how far. | **Tried and reverted 2026-10-23** (commit 1290d1c6; replay 8 in `evals/README.md`: better calibrated, but the leader kept 2–3 links where it had kept 8–13, since each five-level relationship costs ten times the parameters; revisit with ordinal tables). What was tried: `model/levels.py`: a domain's P(past threshold) = σ(s) is read as a logistic centred on s, cut at −2, 0, 2, 4 (each level about one standard deviation of that logistic wide) into `well_below, below, past, well_past, extreme`; the three past 0 sum to σ(s), so levels are a finer cut of the same evidence. `sources.structure.level_variables`, `build_soft_record(levels=True)`. Macro-regime records levels; other domains stay boolean until measured. BIC's parameter count generalised ((values − 1) × parent configurations; unchanged for booleans). Calibration and the dashboard's probability read P(past). Golden G4 mr, G6, G10 macro regenerated. |
| D21 | **Judge soft beliefs against soft evidence.** Calibration (D18) scored the leader against each signal rounded to true or false, but the engine learns from soft evidence, which on weeks that round to true puts the signal at 0.75 on average; a faithful belief then looks timid. | **Done 2026-10-23.** `Calibration.observe` takes the outcome as a probability; health also tracks `leader_calibration_vs_evidence`, against the probability the evidence gave each signal (1 or 0 for hard evidence, so the two agree there). The rounded score is kept. Replay 9 judges it. |
| D22 | **Refute by evidence, not by simplicity.** Refutation (D15) compared window totals less BIC; the prequential window already charges for parameters, so BIC charged twice, and replay 10's diagnostics found it alone refuted every rival within weeks. Totals over windows of different sizes also compared different data. | **Done 2026-10-24.** `scoring.log_bayes_factor`: the gap in average log-likelihood over the records both candidates were scored on, no BIC. BIC still ranks candidates and keeps structures small (without it, a seed-0 replay grew structures until it used 11 GB). |
| D23 | **Score what was observed; give rivals the auxiliary they share.** A variable with a missing parent was skipped, scoring it as certain (a free first week for every structure with lags). Causal programmes were refuted for lacking persistence, which none denies. | **Done 2026-10-24.** `CPTData.get_probability_given` pools the rows over unknown parents, as often as the data saw each; `compute_log_likelihood` scores every observed variable. Macro's causal seeds assume persistence; `T_persistence` is persistence alone (seeds removed by D24; the scoring change stands). Goldens G1 soft, G4 mr, G6 regenerated. A live population built before this keeps its seeds until rebuilt. |
| D24 | **Start with no hypotheses; form them from the evidence.** The seed worldviews were written in 2026 with knowledge of 2003–2026, so the replays tested hypotheses on the history they were written from (EPISTEMOLOGY §2). | **Done 2026-10-24.** Reverses D3's stance (not its deleted service) and D23's shared persistence. A domain gives `variables()` only, every real domain with last-period companions; the engine starts each with one unconnected candidate. `services/synthesis.py` offers, for each programme's best, the admissible connection or reversal the last `RECENT_RECORDS` (= `SCORE_HALF_LIFE_RECORDS`) records most support beyond BIC's penalty; one per programme per cycle, then blind variants, which never vary the unconnected. A connection formed from nothing founds a programme named for its pair ("A–C"). A new candidate's changed tables are re-learned from the remembered records (`_reproduce`); scoring stays prequential. Milestone restated (G2): from nothing, hold B–D after 300 records, then take up A–D with a logged shift within 200, ≥16/20 (19/20); finding all of T* from nothing is a strict xfail (B–C is too weak for the memory span: 0/20 at 300 records, with the four other dependences in 11/20). The level-3 L3-03, judging given rivals, is unchanged and passes. Goldens G1, G4, G5, G6 regenerated. Live populations keep their seeds until rebuilt; replay 11 is not yet planned or run. |
| D25 | **Read measured signals as levels of degree, not doubts.** A measured signal is a precise number; turning its distance past a line into P(True) passed a degree off as a doubt, and counting each such doubt apart from the others blurred relations toward independence (on macro's last 100 weeks, 3 links supported where the same weeks as levels support 8). Macro's raw series show one hump each, not two regimes (EPISTEMOLOGY §3). | **Done 2026-10-25.** `sources/grades.py`: `level_of` (low below −0.5, mid within ±0.5, high above +0.5 of the signal's own unit), `graded_variables` (ORDINAL, support low/mid/high), `build_graded_record` (OBSERVED at a level; no signal → MISSING). All ten measured domains converted, every signal formula unchanged; any 0.0/0.5 fallback for missing input became MISSING (and sovereign debt's liquidity composite averages only the parts with data). Art keeps yes/no soft evidence: its reports are testimony (NEXT.md problem 9). Calibration judges each level of a graded signal (a yes/no still only on True). API: inference returns `target_level`, `target_degree` (P(True) for a yes/no, mean position low→high for levels) and `target_distribution`, replacing `target_probability`; narrative regime state gives `level` and `degree`; graph nodes `degree`. `/v1/ingest/replace` refuses values a variable cannot take, before forgetting the domain. Replay 12: every signal's persistence in every seed, one link beyond it in all five; the population has had one programme since 2008. Goldens G4, G5, G6, G10 regenerated. Live domains need rebuilding to take it up. |
| D26 | **A rival can always be founded.** Replay 12 had one programme alive from 2008: programmes could be founded only from the unconnected start, refuted once persistence was found, and each signal's persistence founded a "programme" of its own, so the rivals were one worldview many times over. | **Done 2026-10-25.** New `services/programmes.py` (programme naming, hard core, `rival`, the fair start), split from `population_manager.py`. Persistence is common ground and founds no programme; the unconnected lineage may hold it. Each cycle, while fewer than half the places hold programmes and the leader has a programme, the connection between two concepts that the last `RECENT_RECORDS` most support beyond BIC and the leader lacks founds a rival: the leader without its hard core, with that connection in its place, named for its pair, with the leader's record of the past (its fit lowered by any complexity it saves, so it ties; the incumbent keeps a tie). Replay 13: rivals through 2004–06 and 7–22 changes of programme then, some weeks apart; none after 2009, when the 100-week memory showed no anomaly; seeds settle on different worldviews; fit gap 2.57–2.72 (replay 12: 2.51–2.55). Golden G1 regenerated. |
| D27 | **Put the leader's core on trial.** After 2009 replay 13's leaders were never challenged: a rival needs a connection the leader lacks, and the evidence offered none (a longer memory would not have: 200 weeks offered one connection, 400 none). Lakatos protects the core; Popper exempts nothing (EPISTEMOLOGY §6). | **Done 2026-10-25.** `programmes.trial`: when no rival is founded and every living candidate is in the leader's programme, the leader without its hard core, everything else kept, `trial_P->C`, lineage `unconnected` (it holds no worldview), level with the leader on score. Refutation (`population_manager._refuted`) now needs decisive evidence on fit and on score both, so a simpler challenger is not refuted for the fit lowered to tie it; for a more complex one the rule is D22's. `_level_with` keeps the tie exact (rounding left a challenger ahead by 2e-16). Replay recorder fixed: it counted links edge existence had switched off as held, which overstated replays 11–13's links between signals. Replay 14: the trial led in four seeds by 2006; in the fifth the core had been switched off (NEXT.md problem 10); from 2009 every seed held persistence alone, fit gap 2.56–2.72, forecast and calibration as replay 13. G2 unchanged (19/20); golden G1 regenerated. |
| D28 | **Art evidence by rule, read as discourse.** Art formed no links in 92 records: its 25 hand-named yes/no signals were almost always "yes", mostly unobserved, and carried a thesis (AI imagery raising a premium on the handmade) that was never the project's question (B23, docs/art-evidence-plan.md §1). Art is a humanities domain: what the press says is itself the evidence, not a noisy sample of a hidden rate, and two papers are two voices, not two witnesses who must agree. | **Done 2026-10-26 (local).** Thirteen graded signals for Bourdieu's three consecrating bodies (plan §3): eight monthly talk signals, the share of a paper's art articles carrying one of its editors' four most-used topic tags (Guardian `artanddesign` from 2010; NYT subjects of articles tagged Art), each month against the two years before; four Art Basel & UBS figures, first-printed, each April, against the figures before; museum acquisitions (Chicago and Cleveland) each December. Yearly signals give last year's level themselves (`build_graded_record(previous=)`, kept by `model/temporal.py`). Removed: the report files and their routes (`/v1/ingest/art/manual`, `/v1/ingest/art/rebuild`; art rebuilds like any domain), GDELT for art, and the yes/no helpers no domain used. Needs `GUARDIAN_API_KEY` and `NYT_API_KEY`. |
| D29 | **Cases mode, for art only.** Art's signals are aggregates (D28) and form no lasting links (replays 15–16); the abductive engine found that art's order shows in many small histories judged together: an artist or a concept is a case, and a mechanism ("a case in state F this year tends to O next year") is judged across all cases at once, each year predicted from the years before, against each case's own past graded finely (abductive_engine ART-PLAN §§8–9). Other domains are one economy or one city: one case each, so the mode has nothing to judge there. | **Done 2026-10-28 (local).** `model/cases.py` (a case-year, its weight, doubling grades); `services/cases.py` (every set of a small pool of mechanisms a rival scheme, backoff tables, standing decayed with a 5-year half-life, a shift when a rival stands 3 nats ahead; for the open year, the likeliest cases and those whose chance the leader raises most over own past); `runtime/cases.py` computes each domain's reports once per process (under a second for art). `DomainRegistration.case_sets`; only art gives any, from snapshots in `art_prestige_regime_v1/case_data/` (about 1 MB each; identical closed case-years stored once with a weight): artists (last year's NYT, Guardian from 2010, critics' approval, contested → Chicago and Cleveland acquisitions; `evals/artist_records.py`) and concepts (contested, both papers, modality → next year's writers; abductive_engine `evals/export_concepts.py`, then `evals/concept_snapshot.py`). The claims come from reading on a subscription the server does not have, so snapshots are rebuilt locally once a year. `GET /v1/cases?domain=` returns the case sets, empty for a domain with none. Replay 18 (artists, own past graded finely): NYT leads from 2007 (on 2006's evidence), +177 nats, deals +60. Concepts: contested from 2015 (on 2014's), +38. Nothing in the existing engine changes; golden G4 (API contract) regenerated for the new route. Later the same day: the report also gives every rival set's gain (`mechanisms`), not the likeliest cases (mostly what own past names, many catch-all concepts); the narrative snapshot carries `case_mechanisms` and a hint to lead the written report with them (empty and out of the hash for other domains, so their cached reports stay valid); the dashboard's art tab shows the case engine in place of the monthly-totals panels. | **Amended 2026-10-29:** the user noticed that "NYT" beat "NYT + Guardian" and every combination lost to its parts. The count tables split cells by every mechanism at once, so a combination relearned its parts in each cell. `services/cases.py` now fits each scheme as a multinomial logistic model (own-past term per grade, one term per mechanism level, L2 prior sd 3 and 1, L-BFGS, fitted on past years only); a combination leads only when it stands 3 nats ahead of each part. Two fixes of the tables were tried first and rejected on made-up cases (abductive_engine ART-PLAN §9 amended). New results: artists, NYT + critics' approval from 2023 (+223 nats; NYT alone +218; Guardian adds about 2, no longer "hurts"); concepts, all three from 2002 (+153 engine, the triple +779; both papers alone +509, which the tables scored −119); trends, nothing over the years (−0.3; contested ahead only since 2024). Dealing each feature at random within years leaves −61 to +10 nats. Reports take about 15 s to compute once per process.
| D30 | **Trends, for art only.** The concepts (D29) are some 10,000 particular topics, not the trends a reader means (craft, AI, identity). The abductive engine groups every claim by its idea, with proper names removed, each year over the three years before, and follows the groups across years; a trend needs at least 36 writers and 10 subjects over three years. All five episodes fixed in advance (NFTs, restitution, Black artists and race, AI-made art, graffiti) peak where expected; no mechanism predicts a trend's growth, a quarter or a year ahead (abductive_engine ART-PLAN §§10–11). | **Done 2026-10-29 (local).** Two snapshots from abductive_engine `evals/export_trends.py` through `evals/trend_snapshot.py`: the trends as a third case set (`case_data/trends.json`; years to September; outcome falls, holds or grows a doubling of writers, so the engine's chance of the outcome at all is the chance a trend holds or grows), and this year's lists (`trend_data/trends.json`: new since 2021, growing ×1.5, fading to half, argued over by the minority side's share of at least 10 verdicts; themes only, named by a local model). `model/trends.py`, `DomainRegistration.trend_lists`, `runtime/trends.py`; `GET /v1/trends?domain=` (trends null for a domain without); the narrative snapshot carries `trends` and a hint that they describe the present, out of the hash when absent so other domains' reports stay valid. The report prompt gains a paragraph on trends without a version bump: it applies only when trends are present, and the art hash changes anyway. Dashboard panel `TrendLists`. | Later the same day: the art report leads with trends, analysed from eight of this year's claims each (prompt section "When the data has `trends`", up to 750 words, token cap 2,000); and each list has its own written report (`prompts/trend_report.md`, its own cache version; `GET /v1/trends/{domain}/{list}/report`, `POST …/refresh`, hash-gated like the domain report; up to 12 trends a paragraph each; the model is told to use only what is in the data).
| D31 | **Success, for art only: what predicts that an artist succeeds next year.** Four kinds kept apart, each its own case set over every artist Chicago or Cleveland ever acquired, 2003–2025: critics approve, more press (either paper), museum buys, and the market (place in Artprice's Top 500 by auction turnover, from its free yearly reports). Eight features of an artist's year, graded none / one / several: claims in a new, growing, fading or argued trend (D30's list rules applied to every year), articles tagged painting (Guardian only), photography or sculpture, and NYT articles. Judged by the additive case engine (D29 amended) with two controls: each leading feature dealt at random among the year's artists (3 deals), and a placebo with the features of the year after (abductive_engine ART-PLAN §12, deviations 1–5). | **Done 2026-10-29 (local).** `evals/success_records.py` builds the four sets (a market case needs a table that year, the next and some year before, or press would stand in for an unknown place); `evals/success_run.py` judges them on 8 cores with the controls; `evals/success_snapshot.py` writes `success_data/success.json` with abductive_engine's `evals/export_rewarded.py` (this year's approvals and disapprovals by medium and theme, description only). `model/success.py`, `DomainRegistration.success`, `runtime/success.py`; `GET /v1/success?domain=` (success null for a domain without); one written report per kind (`prompts/success_report.md`, its own cache version; `GET /v1/success/{domain}/{kind}/report`, `POST …/refresh`, hash-gated). Each kind says whether its placebo is a fair test: not for approval and press, whose year-after features count part of the outcome. Dashboard panel `SuccessPanel`. | Limits, carried into the reports: museum-collected artists only; the market is the top 500 only, in the years Artprice published a readable table (2009, 2010, 2014, 2015, 2018–2025); features come from a model reading the press. Art Basel and Hiscox reports are context, not outcomes. Prompt v2 (same day, after the first four reports misread the controls and claimed agreement between kinds that was not there): the report data gives what each leading feature adds (gain lost when it alone is dealt) and each other kind's leading features with their directions, and the prompt says gains are totals over thousands of artist-years. Prompt v3: the v2 reports still softened the market's +2.4 and claimed agreement between kinds, so the report data carries `verdicts` fixed by rule (strength: under 10 nats too small to claim, 100 or more overwhelming; what the year-after control means; leading features that add nothing or that joined after the last scored year; features leading for all four kinds and which way they push), which the report states as given. Prompt v4: verdicts also say, for each leading feature, which other kinds it leads for and which way it pushes there, and why a fair year-after control is fair; the agreement paragraph is built from them only. Prompt v5 (ART-PLAN §12.8): each report ends with an image prompt, an illustration of a "successful" work by that measure. Its subject is chosen by rule (`success_narrative._image_subject`: the theme the leader's trend lists push up most, ties to this year's net approvals; the leader's medium that pushes up, else this year's most approved); the writer describes only the work, and `report.finish_success_report` adds a fixed label and setting. None where the gain is too small to claim (the market). A section before it, written by code from the same rule (`image_subject.reasons`), says how the prompt was made: the lists and their pushes, the tie and what came next, where the medium came from and what it adds, the media never tested, and that the details are not findings. Where nothing predicts (the market), the prompt describes instead (ART-PLAN §12.9): the snapshot's `at_the_top` counts what the press said this year about our artists in the latest Top 500 table (`evals/success_records.market_top`), and the subject is the theme naming the most of them, the medium the tag on most of their articles; the reasons say it shows what goes with market success, not what leads to it. |
| D9 | Rename the import package from `src` to a real name (e.g. `poe`)? `CLAUDE.md` prescribes the `src/engine` layout. | **Decided 2026-10-23: keep `src`.** `CLAUDE.md` prescribes the layout, and a rename would touch every import for nothing a reader sees. |
| D10 | When an upstream signal is unavailable, emit `MISSING` instead of a soft 0.5? | **Decided (my call): emit `MISSING`; if every input fails, raise `EvidenceUnavailable` and write no record.** Why this is the best option: a soft 0.5 is treated as a real half-true/half-false observation. It adds counts that pull every CPT toward 0.5 and toward independence, and it counts in scoring. `MISSING` uses machinery that already exists and is tested. Learning imputes the value from the current model (no pull toward 0.5), scoring skips it (`learning.py:498`), and the diagnostics already skip non-observed values. Accepted downsides: (1) learning results change, so this gets its own behavior commit after Phase 4, and we re-run G1, G2 (L3-03) and compare dominant-candidate histories before merging. (2) Imputed counts still raise `n` slightly for the missing variable, which mildly overstates confidence. That is far smaller than today's bias. Not done: per-assignment `confidence` stays unused, which is out of scope. |
| D11 | `scripts/backfill_sf_urban.py`: fix or retire? It writes duplicates and gives every historical week today's FRED data. | **Done 2026-10-13: retired.** Use `POST /v1/ingest/backfill?domain=sf`. FRED look-ahead (B10) is still a separate project. |
| D12 | Weekly anchor day? | **Decided: Sunday.** Weekly records are stamped with the Sunday that ends their week. Schedulers keep running Monday and target the Sunday just past; manual trigger and backfill use the same rule for all weekly domains, including mr and ai. Accepted downsides and mitigations: (1) 9 schedulers change from Friday to Sunday stamps. **The same commit migrates stored Friday-stamped weekly records to the following Sunday** (+2 days), so the switchover week doesn't end up with one Friday and one Sunday record. This must run before Phase 4.5 derives `evidence_id` from the timestamp. (2) Stored data is otherwise unchanged: a fetch with `observation_end` = Sunday returns the same values as Friday, because the sources don't publish on weekends. The existing Sunday test (`test_variable_identity_and_weekly_cadence.py:78-88`) stays; the scheduler tests change. |
| D13 | `market_risk_v1/` is empty but listed in `CLAUDE.md` and SPEC §18. Build or delete? | **Done 2026-10-13: deleted.** SPEC §18 keeps it as an example. |

---

## Appendix A — Where things go

| Today | After |
|-------|-------|
| `api/app.py` response models (lines 112–440) | `api/dto.py` |
| `api/app.py` helpers `_normalize_scores`, `_edge_status_label`, `_node_status_label`, `_time_ago`, candidate status | `api/presenters.py` |
| `api/app.py` `_DOMAIN_MAP`, `_require_domain_env`, `_fetch_evidence_record`, lifespan engine list | `runtime/registry.py` (data) + loops in `runtime/app_state.py` |
| `api/app.py` 4 backfill copies, 11 `_run_*_scheduler` | `runtime/ingestion.py`, `runtime/scheduler.py` |
| `api/app.py` `_env_*`, `_data_dir`, `_load_env` | `runtime/settings.py` |
| `api/app.py` routes | `api/routers/*.py` |
| `api/poea_dynamic.py` | `api/read_models/poea_read_model.py` |
| `api/report.py` | `api/report/{cache,llm,sanitize}.py` |
| `stores/parameter_store.py` `CPTData` | `model/cpt.py` |
| `schemas.py` / `population_manager.py` `_avg_score`, `score_weights`, `summary` entropy | `services/scoring.py` |
| `inference.py` `_build_tabular_cpd`, model build; `learning.py` EM model build | `services/bn_model.py` |
| `engine.py` `ProbabilisticOntologyEngine` | `engine.py` `DomainEngine` |
| `config.py` | `runtime/settings.py` |
| `domains/agriculture_weekly.py`, 9 `_last_friday`, 10 `_weekly_backfill_dates`, `_most_recent_monday` | `model/cadence.py` |
| 8 `*/ingestion/fred_client.py` | `domains/sources/fred.py` + per-domain `series.py` |
| 3 `*/ingestion/yfinance_client.py` | `domains/sources/yfinance.py` |
| 10 `_sigmoid`/`_soft_bool`, 9 `_zscore`, 9 `build_evidence_record` | `domains/sources/soft_evidence.py` |
| `*/ingestion/pipeline.py` `compute_snapshot`, `_compute_*` | `<domain>/signals.py` |
| `*/ingestion/pipeline.py` `fetch_evidence` | `<domain>/source.py` |
| 10 `*/scheduler.py` | deleted → `runtime/scheduler.py` |
| `domains/market_risk_v1/` | deleted (D13) |
| `scripts/backfill_sf_urban.py` | deleted or rebuilt on `runtime/ingestion.py` (D11) |
