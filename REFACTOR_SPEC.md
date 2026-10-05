# Refactor Spec — Probabilistic Ontology Engine

Status: draft for review · Date: 2026-10-04 · Scope: `src/`, `tests/`, `scripts/`, repo hygiene

This is the plan we follow to refactor the backend. It says what is wrong (with
evidence), what the code should look like afterwards, and the order to get there
without breaking the running service. §0–§2: summary and rules. §3–§4: evidence and bugs.
§5–§6: target design and guardrails. §7: the plan. §8: decisions for you.

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
| A6 | **An external package drives the engine from inside.** The art route passes the whole engine to `art_prestige_regime_v1.manual_ingest.rebuild_art_evidence_state(engine, …)` and reads back `getattr(engine, "_art_causal_prior_result", …)` — a domain package setting a private attribute on the engine. | `app.py:1353-1384` |
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
| E4 | `_resolve_query_candidate` returns the dominant candidate when given a malformed ID instead of 400 (`app.py:654-658`); reads a `label` attribute that does not exist (`:650`). | — |
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
| B5 | `mean-field` accumulation assumes binary parents in one place: `{v: 1.0 / 2 for v in pv.support}` (`learning.py:224`) vs `1.0 / len(pv.support)` everywhere else. | Wrong for any non-BOOLEAN variable. | — |
| B6 | Shift-event write failure is logged and the learn cycle continues (`population_manager.py:467-473`), so the shift log can silently miss events. Becomes moot once learn runs in one transaction (Phase 3). | — | — |
| B7 | **Evidence dedup never fires.** Every pipeline sets `evidence_id=uuid4()`; the store dedups with `INSERT OR IGNORE` on `evidence_id`. So re-running a trigger or backfill for a date that is already stored appends a duplicate and learns it twice. The `after > before` guards in `app.py:784-789, 2230-2235` are always true. | Double-counted evidence after any manual re-run or overlapping backfill. | `evidence_store.py:44-60`; `*/ingestion/pipeline.py` |
| B8 | **Weekly timestamps depend on the entry point** (DL2): Sunday via the API, Friday via the scheduler, any weekday for mr/ai via the API; daily backfill of weekly domains. | Duplicate and oversampled weeks. | `agriculture_weekly.py:36`; `app.py:766-772, 1294-1297` |
| B9 | **Upstream outage is learned as real evidence** (DL7). | CPTs drift toward independence during outages. Fix decided in D10. | — |
| B10 | **Look-ahead in backfills.** FRED is fetched without vintages and monthly series are dated by period start, so a backfill for 2026-09-04 sees September CPI (published in October). EDGAR filters by period end, not filing date. Worst case: `scripts/backfill_sf_urban.py:248` caches every FRED series with `end_date=today` and serves it to every historical week. | Backfilled history uses data that did not exist yet. Out of refactor scope except the script (D11). | — |
| B11 | **`backfill_sf_urban.py` is not idempotent.** Its "already exists" check compares `'<date> 00:00:00'` against stored `isoformat()` (`…T00:00:00+00:00`), so it never matches. | Duplicates on every run. Don't run it until fixed or retired. | `scripts/backfill_sf_urban.py:260-265` |
| B12 | `fetch_businesses` ignores `end_date` (DL4). | Future data in historical SF records. | `sfgov_client.py:213-219` |
| B13 | **Suspected: SF data truncated.** SFGov queries are capped at `$limit` 1000/2000 rows ordered `DESC` over a 365-day window. SF incidents run in the hundreds per day, so 2,000 rows ≈ 1 week; `_monthly_zscore` needs 3 months → `CrimeIndexElevated` is likely stuck at 0.5. | Needs one live check before fixing. | `sfgov_client.py:111, 153, 198` |
| B14 | `credit_cycle_v1/scheduler.py:77` `asyncio.run(_main() if False else None)` raises. | Standalone entry point broken. Deleted in Phase 5 anyway. | — |
| B15 | `_compute_refinancing_stress` pairs DGS5 and HY observations by list index, not by date. | Misaligned series whenever release calendars differ. | `credit_cycle_v1/ingestion/pipeline.py:186-192` |

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

---

## 7. Plan

Each step is one PR unless noted. "Exit" is what must be true to merge.

### Phase 0 — Safety net (no behavior changes)

0.1 **Hygiene.** `git rm -r --cached .venv` and all tracked `*.pyc`; add
`uv.lock` (`uv lock`), move `dev` extras to `[dependency-groups]`, pin pgmpy to
the installed major version; fix `CLAUDE.md` SPECM→SPEC; move one-off audit docs
to `docs/archive/`. (H1–H3, H5, H6)
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
to call `engine.learn`; replace module-path patches (T4) with the G4 injection
fixture; move private-helper imports (T5) onto G6 where they test pipeline
math. Collapse the 10 ingestion test files' shared template into G6 in Phase 4,
not now.

0.4 **CI** runs the suite (§6.6). Linters come in Phase 6, not now, so they
don't block Phase 1–5 PRs with unrelated noise.

### Phase 1 — Bug fixes that must land before code moves

One commit each, failing test first: B2 (thresholds), B3 (inference query uses
the requested candidate; reject unknown `conditions`/`aggregation` with 422
until implemented — see D6), B5, B7 (the ingest path skips a record whose
`(domain, timestamp)` is already stored; Phase 4.5 makes it structural), B12,
B15, DL3 (keep tracebacks). B13 after a live check. B1 is fixed in Phase 3
because it needs the new persistence. B9 is fixed after Phase 4 (D10); B10 depends on D11.

### Phase 2 — Core barriers (pure code, no I/O changes)

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

### Phase 3 — Persistence

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

Convert one domain end-to-end first (**sf_urban_v1** — it has live tests),
then macro, then the rest one PR each. Golden evidence-record tests (Phase 0)
must produce identical records per domain, except the `evidence_id`.

### Phase 5 — Runtime and API

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

Enable the guardrails in §6 (import contracts, ruff SLF001/BLE001, file-size
test, perf budgets). Fix remaining violations. Update `README.md` and
`CLAUDE.md` project-structure section to the new layout.

---

## 8. Decisions

Status key: **Decided** (answered 2026-10-04, with the downsides we accepted) · **Open** (still needs an answer; recommendation given).

| ID | Question | Status / recommendation |
|----|----------|-------------------------|
| D1 | Can production DBs be rebuilt from stored evidence instead of keeping the current learned state? | **Decided: yes, rebuild.** Migrate evidence rows losslessly (typed soft-evidence keys, B1a; duplicates from B7 collapsed to the earliest per `(domain, timestamp)`), then replay once with the fixed code. Accepted downsides: (1) the dominant hypothesis and scores shown after the migration will differ from before. Each redeploy already reset them (B1), so nothing trustworthy is lost. (2) Old `paradigm_shifts` rows point to candidate IDs that no longer exist. Keep them; they carry names. Add a `pre_migration` flag so lineage lookups for those IDs return 404 with a clear message. (3) A one-time startup replay, measured at about 0.1 s per 300 records. Precondition: **snapshot the Railway volume before deploying Phase 3.3.** |
| D2 | Change `art-market-domain` at the same time (Phase 5.6)? | **Decided: yes.** Accepted downsides: (1) the backend pins an art-package commit (Phase 0.2), so art changes no longer reach production until the pin is bumped. That is intended, because deploys become reproducible. (2) The release must be coordinated: the art package first ships the new public hook *alongside* the old calls (one release of overlap), then the backend switches, then the old calls are removed. **Assumption: you have write access to `technoir7/art-market-domain`.** If you don't, fall back to a thin adapter in `runtime/` that confines the old contract to one file. |
| D3 | `ExploreExploitService` is built and tested but never used. SPEC §10.1 puts it in the learn loop. Wire it in or delete it? | **Open.** Recommend: Delete now (git keeps it); re-add when there is a design for how proposals enter the population. |
| D4 | `LearningService.accumulate_em` is only used by one level-1 test and ignores soft evidence. Keep or delete? | **Open.** Recommend: Delete with its test; mean-field is what production runs. |
| D5 | Drop the never-used SPEC §8 stub methods from the `DomainModule` contract? | **Open.** Recommend: Yes, and update SPEC §8 to match. |
| D6 | `POST /v1/inference/query` accepts `conditions` and `aggregation` but ignores them. Implement, or reject with 422? | **Open.** Recommend: Reject now (Phase 1), implement only if the frontend needs it. Check `epistemic-monitor` usage first. |
| D7 | Is a shared-secret header acceptable for POST routes, and what origins should CORS allow? | **Open.** Recommend: Yes; the Vercel URL + localhost. |
| D8 | Learn order (C9): score each batch before updating counts (prequential), or keep today's order? | **Open.** Recommend: Prequential — it is the standard fair comparison and removes the bias toward denser graphs. Behavior change; would get its own commit after Phase 3 and will move dominant-candidate history. |
| D9 | Rename the import package from `src` to a real name (e.g. `poe`)? `CLAUDE.md` prescribes the `src/engine` layout. | **Open.** Recommend: Not in this refactor. Revisit after Phase 6. |
| D10 | When an upstream signal is unavailable, emit `MISSING` instead of a soft 0.5? | **Decided (my call): emit `MISSING`; if every input fails, raise `EvidenceUnavailable` and write no record.** Why this is the best option: a soft 0.5 is treated as a real half-true/half-false observation. It adds counts that pull every CPT toward 0.5 and toward independence, and it counts in scoring. `MISSING` uses machinery that already exists and is tested. Learning imputes the value from the current model (no pull toward 0.5), scoring skips it (`learning.py:498`), and the diagnostics already skip non-observed values. Accepted downsides: (1) learning results change, so this gets its own behavior commit after Phase 4, and we re-run G1, G2 (L3-03) and compare dominant-candidate histories before merging. (2) Imputed counts still raise `n` slightly for the missing variable, which mildly overstates confidence. That is far smaller than today's bias. Not done: per-assignment `confidence` stays unused, which is out of scope. |
| D11 | `scripts/backfill_sf_urban.py`: fix or retire? It writes duplicates and gives every historical week today's FRED data. | **Open.** Recommend: Retire; use `POST /v1/ingest/backfill` on the shared runner. Fixing FRED look-ahead (vintages via ALFRED, filing dates for EDGAR) is a separate project. |
| D12 | Weekly anchor day? | **Decided: Sunday.** Weekly records are stamped with the Sunday that ends their week. Schedulers keep running Monday and target the Sunday just past; manual trigger and backfill use the same rule for all weekly domains, including mr and ai. Accepted downsides and mitigations: (1) 9 schedulers change from Friday to Sunday stamps. **The same commit migrates stored Friday-stamped weekly records to the following Sunday** (+2 days), so the switchover week doesn't end up with one Friday and one Sunday record. This must run before Phase 4.5 derives `evidence_id` from the timestamp. (2) Stored data is otherwise unchanged: a fetch with `observation_end` = Sunday returns the same values as Friday, because the sources don't publish on weekends. The existing Sunday test (`test_variable_identity_and_weekly_cadence.py:78-88`) stays; the scheduler tests change. |
| D13 | `market_risk_v1/` is empty but listed in `CLAUDE.md` and SPEC §18. Build or delete? | **Open.** Recommend: Delete the empty package; update `CLAUDE.md`. |

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
