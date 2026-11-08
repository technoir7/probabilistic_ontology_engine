# ART_CONSOLE_SPEC v1 · machine-oriented · as_of=2026-11-08
# pins: poe@7cf26819 (engine+API) · epistemic-monitor@f511a98 (dashboard), plus the 2026-11-08 change: art export prompt + `success` in the narrative snapshot
# rebuild values in §4/§8 after any snapshot rebuild; they are the shipped data's, not live
# notation: A→B data flow; [file:sym]; ⟨k⟩ = constant; ≡ defined as; ∅ = empty/null; nats = natural-log score units

## 0 SCOPE
console ≡ dashboard tab key=`art` ticker=`AR` label=`art_regime` in epistemic-monitor/app/page.tsx, plus every engine route/compute it reads.
mount: Dashboard.active==='art' → <CasePanels key=art domain=art/> (only the active tab mounts; key remounts on tab change) + <DomainReport domain=art/> below grid in .report-section.
contrast: other domains → RegimePanels (EpistemicStateBar, BeliefGraph, RegimeStatePanel, OntologyPopulation, ParadigmShiftTimeline, ExplorationFrontier, PromptLine); ng → NgPanels. Art replaces state/graph/population/history/frontier slots with case-engine panels because art's monthly signals form no links (replays 15–16) [REFACTOR_SPEC D29].
epistemic stance (binding on all art output): discourse=evidence (D28); no thesis in inputs; LLM reads or writes, code judges; nothing LLM-written is learned from; description≠prediction (only what beats own past in the case engine "predicts").

## 1 PANEL ORDER (CasePanels, DOM order) → grid slot (CSS class) → data
| # | component | css slot | SWR key | endpoint(s) | poll |
|1| CaseStateBar | .epistemic-state col1/3, 5-col grid, max-h 112 | ['cases',art] + ['population-status',art] | GET /v1/cases ; GET /v1/population/status | cases: none ; status: 30s |
|2| CaseGraph | .belief-graph-panel col1 rows2/4, svg 520×300 | ['cases',art] | GET /v1/cases | none |
|3| RegimeStatePanel | .regime-panel col2 rows2/4 | ['regime-readings',art] | 13× POST /v1/inference/query {domain:art,target_variable:V} | 30s |
|4| CaseRivals | .population-panel col3 rows1/5, max-h 500 scroll | ['cases',art] | GET /v1/cases | none |
|5| TrendLists | .shift-panel col1/3 | ['trends',art] | GET /v1/trends ; sub-report routes | none |
|6| SuccessPanel | .shift-panel | ['success',art] | GET /v1/success ; sub-report routes | none |
|7| MoversPanel | .shift-panel | ['success',art] | GET /v1/success ; /v1/success/art/movers/report | none |
|8| ThemesPanel | .shift-panel | ['success',art] | GET /v1/success ; /v1/success/art/themes/report | none |
|9| LivesPanel | .shift-panel | ['success',art] | GET /v1/success | none |
|10| CaseForecasts | .shift-panel | ['cases',art] | GET /v1/cases | none |
|11| CaseShifts | .frontier-panel col1/3 | ['cases',art] | GET /v1/cases | none |
|12| PromptLine | .prompt-line col1/-1 | — | — (static string `cases --domain art --sets artists,concepts --rivals all --against own_past`) | — |
|13| DomainReport (outside grid) | .report-section | ['domain-report',art,undef,undef] | GET /v1/report/art ; POST /v1/report/art/refresh | none |
grid: cols `1fr 1fr 300px`; rows `minmax(112,auto) 150 252 minmax(144,auto) minmax(88,auto) minmax(38,auto)`, auto-rows minmax(88,auto); ≤640px → 1 col, all placements reset.
SWR dedupe: 4 panels share ['cases',art] → 1 fetch; 4 share ['success',art] → 1 fetch. All use revalidateOnFocus:false.
header (shared, applies to art): `[ fetch now ]` → POST /v1/ingest/trigger?domain=art then mutate keys whose [1]===art or [1].domain===art; `[ EXPORT SNAPSHOT ]` → GET /v1/export/narrative-snapshot?domain=art, prepend SNAPSHOT_PROMPT with VARIABLE_DEFINITIONS_BY_DOMAIN.art (13 signal glosses), download `art-snapshot-<iso>.txt`; art uses ART_SNAPSHOT_PROMPT (cases, trends, success first; the 13 monthly totals only as background), every other domain the economics SNAPSHOT_PROMPT; window.fetchEntropyDebug(domain=art) → GET /v1/debug/entropy.
error contract: every fetcher throws on !ok [lib/api.ts get/post]; panels render `API ERROR · <msg>`; never placeholder data. post() omits Content-Type on bodyless POST (avoids CORS preflight); error detail from body.detail if string.
theme: CRT green-on-black; tokens --green #00ff41, --amber #ffb300 (=engine's current belief/leader), --green-dark #009922 (=helps), --red-dim #991500 (=fails/hurts), --text-faint #00882a (=description, not advice). Colour semantics are load-bearing: description-only lists (themes w/o record, lives) are never coloured help/harm.

## 2 ENGINE TOPOLOGY (art path)
registry: DomainRegistration("art","art_prestige_regime_v1","Art Prestige Regime","art_prestige_regime.db",ArtPrestigeRegimeV1,art_source.open_source,env=(GUARDIAN_API_KEY,NYT_API_KEY),"ART",cadence=Monthly(),backfill_pause_s=1.0,case_sets=art_cases.case_sets,trend_lists=art_trends.current,success=art_success.current) [src/engine/runtime/registry.py]. Only art supplies case_sets/trend_lists/success; other domains → empty/None.
layers (import downward only, lint-imports): api/routers → runtime/{cases,trends,success} → services/cases.py → model/{cases,trends,success}; domains/art_prestige_regime_v1/{cases,trends,success}.py load JSON → model dataclasses.
snapshots (static, in git, rebuilt offline ~yearly from abductive_engine; server never reads press):
  case_data/artists.json 0.9MB · concepts.json 1.0MB · trends.json 0.2MB ; trend_data/trends.json 112K ; success_data/success.json 136K
compute lifetime:
  cases: runtime.cases._case_reports @functools.cache per key, guarded by threading.Lock `_computing` (concurrent callers wait, don't recompute); warmed at app start by daemon thread `warm-case-reports` [api/app.py:73]; route calls via asyncio.to_thread. Cost: 2^|pool| L-BFGS fits per year per set; measured 36s on laptop @7cf26819 (docs say ~15s laptop, >60s server).
  trends/success: @cache file read, once per process.
monthly engine (comparison only): standard POE loop on 13 graded signals (low/mid/high, D25) + _prev lags; CaseStateBar shows only whether its dominant name startsWith 'unconnected' → "no links found" else "links under trial".
  signals: GuardianPhotographyTalk GuardianExhibitionTalk GuardianPaintingTalk GuardianArchitectureTalk (tag share of Guardian artanddesign, vs 2y before) · NYTMuseumsTalk NYTPhotographyTalk NYTSculptureTalk NYTAuctionsTalk · ArtSalesGrowth DealerShare OnlineShare HighEndShare (Art Basel&UBS, report_figures.csv, yearly/April) · MuseumAcquisitionMomentum (AIC+CMA distinct artists acquired, yearly/Dec).
  source: open_source(env) → ArtPipeline({guardian,nyt}, AICClient, CMAClient) [ingestion/*].

## 3 CASE ENGINE (services/cases.py) — exact semantics
model.cases: LEVELS⟨3⟩ (outcome ∈ {0 none,1 one,2 several}); level(n)=min(n,2); doubling(n)=0 if n==0 else min(6,(n-1).bit_length()+1) → grades 0,1,2,3-4,5-8,9-16,17+.
CaseYear{year, own:tuple(graded own past), features:{f:int}, outcome:int|None (None=open year to forecast), weight:int (identical closed rows stored once), case:str|None}.
CaseSet{key,title,pool,records,labels{case→name},outcome:str,meanings{f→words}}.
snapshot JSON: {key,title,outcome,pool[],labels{}, closed:[[year,own[],values[],outcome,weight]], open:[[year,own[],values[],case]]}; load() raises ValueError if len(values)≠len(pool).
scheme ≡ each subset S⊆pool (incl ∅ = "own past alone"); CaseEngine holds 2^|pool| CaseSchemes over one shared _Data.
CaseScheme.fit: multinomial logistic, outcome 0 reference; columns = intercept + one per own-past grade tuple ("own",o) + one per (f, nonzero level v) for f∈S; prior: intercept flat, own sd⟨OWN_SD=3⟩, mechanism sd⟨MECHANISM_SD=1⟩ (L2); data grouped by (own, S-values) counts; L-BFGS-B gtol1e-9 ftol1e-15 maxiter5000; warm start from prior year's terms where columns persist; failure unless success or "ABNORMAL" in message → RuntimeError.
predict(r): softmax([0, x·W]); unfitted → uniform 1/3.
effects(): per (f,v): logsumexp(base+W[f,v]) − logsumexp(base), base = intercept + mean own-past term ⇒ push on log-odds of any outcome vs none at average own past (+ helps, − hurts).
step(year, rows):
  1 score every scheme on rows with models fitted on prior years: Σ w·log p(outcome)
  2 result=(score[leader], score[∅])
  3 standing[s] = ⟨DECAY=0.5^(1/5)⟩·standing[s] + score[s]   (HALF_LIFE_YEARS⟨5⟩)
  4 learn rows; refit all schemes
  5 earned = {s : ∀x∈s, standing[s] − standing[s∖x] > ⟨SHIFT_NATS=3.0⟩}  (∅ trivially earned)
  6 best = argmax_{earned} standing; if best≠leader ∧ standing[best]−standing[leader] > 3 → Shift(year, leader, best); leader=best
  ⇒ shift decided on year Y's evidence, used from Y+1. Initial leader=∅.
case_report(set, top⟨FORECAST_ROWS=20⟩):
  iterate closed years ascending; first year learn-only (scores not recorded); YearScore(year, engine=leader-before-year score, own_past, cases=Σweight)
  mechanisms: per nonempty s, gain = Σ_years (score[s] − score[∅]); sorted desc
  gain(report) ≡ Σ (engine − own_past) over scored years  ← leader-path gain, ≠ any single mechanism's gain
  forecast_year = open_rows[0].year | None; Forecast(case,label,own_past=P∅,with_leader=Pleader) for open rows
  most_raised = rows where with_leader[0] < own_past[0], sorted by (with_leader[0]−own_past[0], label) asc, top 20  (rank = how much leader lowers P(none))
  effects = leader scheme's effects()

## 4 CASE SETS — current values (computed @7cf26819)
| key | title | outcome | pool | leader | since | gain | scored yrs | case-yrs | forecast_for |
| artists | Artists | Chicago and Cleveland acquisitions next year | nyt,guardian,approval,contested | nyt+approval | 2024 | +220.2 | 2001–2024 (24) | 217,632 | 2026 |
| concepts | Concepts | writers taking the concept up next year | contested,both_papers,modality | contested+both_papers+modality | 2002 | +153.2 | 2001–2024 (24) | 261,016 | 2026 |
| trends | Trends | trends holding or growing next year | contested,both_papers,modality | contested | 2024 | −0.3 | 2001–2025 (25) | 11,322 | 2027 |
(since = last shift.year+1; forecast_for = forecast_year+1; artists/concepts forecast_year=2025, trends=2026)
shifts: artists 2002 ∅→nyt · 2008 →nyt+approval · 2013 →nyt+guardian+approval · 2015 →+contested · 2023 →nyt+approval ; concepts 2001 ∅→all three ; trends 2023 ∅→contested.
mechanism gains: artists nyt+approval+contested 239.2, nyt+approval 239.0, …, nyt 218.2, approval 136.7, guardian 45.2, contested 16.0 (all >0) ; concepts triple 776.7, both_papers+modality 658.0, both_papers 507.7, modality 188.2, contested 172.0 ; trends all <0 (contested −2.3 … triple −17.1).
note: trends' leader 'contested' gained on decayed standing though total gain <0 → nothing predicts trend growth (D30).
top forecasts: artists Christopher Wool 23%→29%, G.B. Tiepolo 17→21, Bridget Riley 16→19 ; concepts Calder Gardens 27→41 ; trends "turbine · hall · modern's" 60→65.
artists snapshot: closed rows 6,262 (weighted), open 9,068 (=artist count after D32 §16 maker filter); own is a 2-tuple of grades.
MEANINGS (domain cases.py) f→words: nyt, guardian, approval, contested (both praised and condemned), both_papers, modality (predictions or doubts), new_trend, growing_trend, fading_trend, argued_trend, good_theme, poor_theme, good_life, poor_life, painting (Guardian-tagged), photography, sculpture.
dashboard MECHANISM labels (lib/labels.ts): nyt→"NYT coverage", guardian→"Guardian coverage", approval→"critics' approval", contested, both_papers→"in both papers", modality→"predictions or doubts", *_trend→"in a <x> trend", painting→"painting (Guardian)", good_theme/poor_theme→"in a good-/poor-record theme"; unknown→raw key; []→"own past alone". (good_life/poor_life have no dashboard label → raw.)

## 5 /v1/cases contract
GET /v1/cases?domain=art → CasesOut{domain, case_sets: CaseSetOut[]}; 404 unknown domain; other domains → case_sets=[].
CaseSetOut{key,title,outcome,pool[],leader[],shifts[{year,frm[],to[]}],years[{year,engine,own_past,cases}],gain,mechanisms[{features[],gain}],forecast_year|null,most_raised[{case,label,own_past[3],with_leader[3]}]}.
(meanings/effects exist on CaseReport but are NOT serialized.)

## 6 CASE PANELS — render logic
CaseStateBar: per set LeaderCell{label `<key>_leader`, amber mechanismLabel(leader), sub `since <leaderSince> · ±<gain.toFixed(0)> nats`}; cell case_years_judged = Σ_sets Σ_years cases /1000 → "490k"; cell monthly_totals (see §2); cell forecast_for = first non-null forecast_year +1 ("2026", sub "from data through 2025").
  leaderSince(set) = last shift.year+1 else years[0].year.
  quirk: gain −0.3 → "-0 nats" (sign prefix only for ≥0, toFixed(0) yields "-0").
CaseGraph [lib/caseGraph.ts caseGraph(sets,W=520,H=300)]: one horizontal band per set (h=H/n); edges only for single-feature mechanisms present in pool order; left x=MARGIN⟨150⟩, right x=W−150 (outcome node), y spread with PAD⟨26⟩; tone = leader∋f ? 'leader'(amber) : gain>0 ? 'helps'(green-dark) : 'fails'(red-dim, dashed 3 3); width = 1 + (MAX_WIDTH⟨7⟩−1)·max(gain,0)/best, best = max single-feature gain across ALL sets (shared scale); gain label at 22% along edge, signed integer with U+2212; outcome text wrapped ≤20 chars.
  caveat: leader tone is per-feature (f∈leader), so a combination leader colours each member amber; combination gains not drawn.
CaseRivals [rivalRows]: per set header `<title> → <outcome>`; rows = all mechanisms best-first; bar = gain/max(1,max|gain|) centred at 50% (pos right, neg left); leader row amber matched by sorted-join equality.
CaseForecasts: per set: bar strip of (engine−own_past) per year, scaled to max|gain|, centred; title `<title> · <first>–<last>`; list `<outcome>, <forecast_year+1>: own past → with <leader>`; up to ROWS⟨8⟩ of most_raised as `label  anyChance(own_past) → anyChance(with_leader)`; empty → "the leader is own past: it raises no one".
  anyChance(p) = 1−p[0] → ">99%" if ≥.995, "<1%" if <.005, else round%. Never rounds to certainty.
CaseShifts: per set `<title>: ` then shifts as `<year+1> <mechanismLabel(to)>` joined " → ", last amber; none → "own past alone throughout".
tooltip text hard-codes "2001–2024" (CaseGraph, CaseRivals) — trends set actually scores 2001–2025.

## 7 TRENDS (D30)
model.trends: LISTS=(new,growing,fading,argued). Trend{key,name,start(first broad yr),words[],writers[per years],papers[],verdicts(approvals,disapprovals),sample[claims]}. TrendLists{year (years end Sept),before,years[],all_writers[],lists{name→keys[]},trends{key→Trend}}; share(k,y)=writers/all_writers; share_before = mean over BEFORE prior years.
load validation: len(all_writers)=len(years); year and year−before ∈ years; lists keys == LISTS; each trend writers len == years; every listed key exists → else ValueError.
current: year=2026 (Oct 2025–Sep 2026), before=3, years 2010–2026, 107 trends; counts new 15, growing 12, fading 41, argued 48.
list rules (engine LIST_RULES / dashboard TREND_LIST): new = broad first time ≥2021, rank writers this year; growing = share ≥1.5× mean of 3 prior, rank ratio; fading = share ≤½ best of 3 prior (that year broad), rank that best; argued = ≥10 verdicts, rank evenness of split. Broad ≡ ≥36 writers and ≥10 subjects over 3 years (abductive). Names by local qwen, proper names stripped.
GET /v1/trends?domain= → TrendsOut{domain, trends: TrendListsOut|null}, mirrors model 1:1.
TrendLists panel: header `trends · october <y−1> – september <y>`; 4 columns ORDER new,growing,fading,argued; each `TREND_LIST[l][0] · <n> [ read report ]`; ROWS⟨12⟩ then `+N more`/`fewer`; row = name + sparkline (shares, 44×12, normalised to own max) + measure():
  new → "<writers now> writers"; growing → "×<now/avg_before .1f>" or "new" if avg 0; fading → "<pct(max before)> → <pct(now)>"; argued → "<round(100·min/(yes+no))>% split".
  row expands: `broad since <start> · <papers joined '+'> | neither paper this year · <for> for, <against> against`, words joined " · ", sample claims quoted.
  read report → inline DomainReport sub={section:'trends',name:l}.

## 8 SUCCESS (D31) — model & values
Success{year, forecast_for, kinds{key→SuccessKind}, rewarded[], meanings, lists{f→list}, media{f→medium}, at_the_top{kind→AtTheTop}, apart=('movers',), themes{kind→ThemeTest}, lives{kind→LifeClaim[]}, life_tests{kind→ThemeTest}, life_years, life_told{kind→(most[(name,score)],least[])}, life_graph{kind→[(src,tgt,P(tgt|src),times_usual)]}}.
SuccessKind{key,title,outcome,leader[],leader_since,gain,mechanisms[(“a+b”,gain)],effects{(f,level)→push},dealt{f→[gain per deal ×3]},placebo,placebo_fair,most_raised[(artist,p_own,p_leader)],years[(year,engine−own)]}.
POOL = new_trend,growing_trend,fading_trend,argued_trend,painting,photography,sculpture,nyt (graded none/one/several). load: kinds ⊇ KINDS(approve,press,museum,market) ⊆ KINDS∪APART; themes ⊆ KINDS; life_* ⊆ kinds; at_the_top ⊆ KINDS; leader ⊆ POOL (themes add good/poor_theme, lives good/poor_life) else ValueError.
population: every artist Chicago (AIC) or Cleveland (CMA) ever acquired (9,068 after maker filter); market = Artprice Top 500 by auction turnover, tables 2009–2025.
controls: dealt = each leading feature shuffled among the year's artists (3 deals) → adds(f) = gain − mean(dealt[f]); placebo = same test with next year's features; placebo_fair=false for approve/press (year-after features count the outcome itself).
current: year=2026, forecast_for=2026.
| kind | title | leader | since | gain | adds per feature | placebo (fair) |
| approve | Critics approve | growing+argued+painting+nyt | 2022 | 343.2 | growing 35.6, argued 130.3, painting 1.8, nyt 58.2 | 10708 (no) |
| press | More press | new+growing+argued+nyt | 2025 | 143.3 | new 0.0, growing 16.8, argued 61.7, nyt 5.4 | 16608 (no) |
| museum | Museum buys | argued+photography+nyt | 2015 | 223.0 | argued 35.0, photography −3.1, nyt 61.9 | 190.7 (yes → coverage before) |
| market | Market | growing+nyt | 2024 | 56.5 | growing 3.6, nyt 27.2 | 97.3 (yes → coverage WITH, not before) |
| movers (apart) | Market movers | argued+nyt | 2017 | 66.2 | argued 2.8, nyt 20.1 | 106.6 (yes → with) |
scored years: approve/press/museum 2004–2024; market/movers 2011–2024. movers outcome: move up bands {not listed, 251–500, 101–250, 26–100, 1–25}.
rewarded: 55 rows, kind∈{medium,trend}: approvals/disapprovals this year + claim texts. at_the_top only for market (describes instead; ART-PLAN §12 deviation 6).
themes (record per theme per kind from prior years, shrunk; tested on top of kind leader): approve 347.6 vs 343.2 (good_theme not in leader); press 143.3=143.3; museum leader photography+nyt+good_theme 242.2 vs 223.0 (+19.2, record leads); market nyt+good_theme 55.0 vs 56.5. records year=2025.
lives: verdict=nothing for all 5 kinds; told_year 2025; 8 life claims each; edges approve 16, press 8, museum 10, market 4, movers 10.

## 9 /v1/success contract
GET /v1/success?domain=art → SuccessOut{domain, success: null | {year, forecast_for, kinds{k→SuccessKindOut}, rewarded[RewardedOut], themes{k→ThemeTestOut}, lives{k→LifeTestOut}}}.
serialization: effects keys "f=level" (string); mechanisms [[name,gain]]; most_raised [[artist,p_own,p_leader]]; years [[y,g]]; ThemeTestOut{leader,leader_since,gain,gain_without,effects,dealt,placebo,year,best[[name,rec]],worst}; LifeTestOut = ThemeTestOut + {verdict: life_verdict(s,k), told_year, told_most[[name,score]], told_least, edges[[src,tgt,share,times]]}.
NOT serialized: meanings, lists, media, at_the_top, lives claims text (only reach the LLM via report snapshot).
life_verdict(s,k) [success_narrative]: no life_test → untested; adds = gain − mean(dealt.good_life); if good_life∉leader ∨ gain−gain_without < SMALL⟨10⟩ ∨ adds ≤1.0 → nothing; elif placebo_fair ∧ placebo ≥ gain → with; else predicts.

## 10 SUCCESS-FAMILY PANELS — render logic
SuccessPanel: header `success · what_predicts_it · forecast for <forecast_for>`; 4 Kind columns ORDER approve,press,museum,market; then 3 RewardedLists: `critics_rewarded · media · <year>` (all medium rows by share desc), `most_approved · themes` (trend rows top REWARDED⟨8⟩), `least_approved · themes` (reversed top 8); row = name, `a–d`, share%; title attr lists `+ claim`/`− claim`.
  Kind (exported, reused by Movers): title + `[ read report ]`; row mechanismLabel(leader) `±gain nats`; pushes(kind,PUSHES⟨5⟩) = effects sorted by |push| desc as `<label>, one|several  ↑/↓ |push|.2f`; adds(kind) rows `adds · <label>  ±n` sorted desc; row `features from the year after` = placebo or "n/a" (tooltip) when !placebo_fair.
  rewardedBy(rows,kind): filter kind, share=a/(a+d), sort desc.
MoversPanel: same Kind on kinds.movers; ∅ → "no market movers analysis for this domain"; report sub {success,movers}.
ThemesPanel: header `themes · which_help · records for <year>`; single `[ read report ]` (sub {success,themes}); per kind column: themeRecord(t) → leads = leader ∩ {good_theme,poor_theme} ≠ ∅; over = gain−gain_without; adds = gain − mean(dealt.good_theme) (unused in UI); line "record leads +over nats" (green) or "record adds nothing" (faint); best/worst SHOWN⟨6⟩ names, coloured green/red only if leads else faint.
LivesPanel: ORDER approve,press,museum,market,movers filtered to kinds with lives; header `lives · told_of_the_championed · <told_year>`; column: VERDICT text {untested:"forecast: not tested", nothing:"forecast: life adds nothing", with:"forecast: comes with success", predicts:"forecast: life predicts"}; told most ×6; pairs(): edges deduped by unordered pair (first seen kept), sorted by times desc, top PAIRS⟨3⟩ → "a + b ×times"; told least ×6. All faint/neutral: description only.

## 11 REPORTS (LLM, hash-gated)
routes [api/routers/reports.py]:
  GET  /v1/report/art                       → cached only; {found:false,domain} if none
  POST /v1/report/art/refresh               → snapshot=narrative.snapshot_for(app.state,'art') ; prompts/snapshot_report.md ; PROMPT_VERSION⟨4⟩
  GET|POST /v1/trends/art/{list}/report[/refresh]   → trend_list_snapshot ; trend_report.md ; TREND_PROMPT_VERSION⟨1⟩ ; cache key art-trends-<list>
  GET|POST /v1/success/art/themes/report[/refresh]  → themes_snapshot ; themes_report.md ; THEMES_PROMPT_VERSION⟨2⟩ ; key art-themes   (registered BEFORE /{kind} route)
  GET|POST /v1/success/art/{kind}/report[/refresh]  → success_snapshot ; success_report.md ; SUCCESS_PROMPT_VERSION⟨23⟩ ; key art-success-<kind> ; writes⟨3⟩ ; finish=finish_success_report
  LookupError (unknown list/kind) → 404.
refresh algorithm (_refresh): h=sha256(canonical json, sort_keys, minus metadata.timestamp, interpretation_hints, empty case_mechanisms, null trends, null success); exact cache file `<key>__apriori__pv<ver>__<h[:16]>.json` under $POE_DATA_DIR/reports → hit returns cached; else need FIREWORKS_API_KEY (absent → stale or 503); generate up to `writes` times; on exception → newest same-version file as stale=true, else 502. Saved {domain,generated_at,snapshot_hash,report}. load_cache rejects empty report. GET never builds snapshot, never calls LLM.
response DomainReportOut{found:true,domain,generated_at,snapshot_hash,report,cached,regenerated,stale}.
LLM: Fireworks OpenAI-compatible; writer FIREWORKS_REPORT_MODEL default accounts/fireworks/models/deepseek-v4p1-flash; max_tokens 3000, reasoning_effort none; finish_reason=length → error; empty → retry once; meta-reasoning heuristic (first 600 chars vs _META_PATTERNS) → retry with strict system ("Begin with '## In short'"), served anyway if still matched.
domain snapshot for art: standard NarrativeSnapshotOut + case_mechanisms[NarrativeCaseSetOut{title,outcome,leader(words),leader_since,gain_nats_over_own_past,mechanisms[{mechanism,gain_nats}],belief_changes["from Y: words"],forecast_for,most_raised top FORECAST_ROWS⟨5⟩ {case,own_past_chance,with_leader_chance}}] + trends{period,compared_with,note,new/growing/fading/argued_over top TREND_ROWS⟨6⟩} + success{forecast_for,note,kinds[{kind,title,success_means,leader(words),leader_since,gain_nats_over_own_past,verdicts (=success_narrative._verdicts, same as the kind's own report),kept_apart}]} [success_narrative.success_summary] + hints CASES_HINT, TRENDS_HINT, SUCCESS_HINT (lead with trends, then cases, then success; trends describe). prompts/snapshot_report.md trends layout = 5 headings incl "What predicts an artist's success", ≤900 words; PROMPT_VERSION not bumped (D30 precedent: section applies only when field present; art hash changes anyway, other domains unaffected).
trend row (report): {trend,broad_since,writers_this_year,share_this_year_pct,share_before_pct,share_by_year_pct{y−3..y},papers,approvals,disapprovals,distinctive_words,what_critics_said}; list report top LIST_ROWS⟨12⟩ + rule text.
success snapshot: {domain,kind,title,success_means,forecast_for,leader(words),leader_since,gain_nats_over_own_past,scored_years,verdicts[],best_rival_sets top12,leader_effects[{feature "one|several: meaning",push,times_the_odds…=exp(push) .1f}],each_leading_feature_adds,control_placebo…gain_nats,control_placebo_is_a_fair_test,artists_the_leader_favours top12,other_kinds{title→{leading_features,gain,helps,hurts}},critics_rewarded_this_year,image_subject|null,note}.
verdicts by rule (_verdicts; writer must state as given): strength gain<10 "too small to claim" | ≥100 "overwhelming" | else "clearly but modestly"; placebo line (unfair / with / before); each leading f with adds≤1 → "adds nothing" (or "joined after last scored year, untested" if |adds|<.05 ∧ leader_since>last scored); per leading f: leads for all other main kinds (helps/hurts list) | also leads for X(helps|hurts), not for Y | leads for no other kind. Comparisons exclude `apart` kinds.
image_subject (_image_subject): at_the_top[kind] exists (market) → _described_subject (theme naming most top-500 artists, ties claims then net approvals; medium = tag on most of their articles; describes_instead=true); elif gain<10 → null ("Nothing … no illustration"); else theme = argmax over trends of (Σ push of leader's trend-list features whose list contains theme, net approvals, writers now); medium = leader medium with max positive push else most-net-approved medium; reasons[] written by code; wall_text_voice by kind {museum: museum acquisition label, market/movers: commercial gallery sale, approve/press: exhibition wall text}; life_claims numbered ≤8; life_finding; life_edges.
finish_success_report: splits writer output at "## Image prompt"/"## Wall text"/"## Artist statement"/"## The imagined artist"; missing part → MissingPart(WriteAgain); rebuilds: body + "## How the image prompt was made"(code reasons) + IMAGE_LABEL + description + IMAGE_SETTING (fixed white gallery) + wall text (label) + statement (label) + life section.
life pipeline (D32): sentences split on /(?<=[.!?\]])\s+(?=[A-Z"'‘“])/; each must cite [n,…] ⊆ given else WriteAgain → word rule life_words.lacking(sentence, cited claims): allowed = claim words (with plural/tense/irregular-verb forms) ∪ _JOINING stopwords (no time/cause/contrast words) ∪ they/them (+he/she only if a claim states "she/her" etc.) → cut with reason → survivors read by 2 readers [GLM-5.3 flash glm-5p3-flash, writer model], prompt life_check.md v4, answer "i y|n" per line, temperature 0, reasoning low, max_tokens 16000; out-of-form → ask once more → WriteAgain; keep iff all readers y → kept < min(⟨LIFE_SENTENCES=3⟩, #claims) → ShortLife (rewrite, up to 3 writes, fullest kept) → optional edit (life_edit.md, writer model) re-run through word rule+readers, kept only if cites ⊇ checked life's claims; "same"/fail → checked life stands. Rendered: LIFE_LABEL, finding, life (edited + "as first checked"), cut list with reasons, life_graph lines, claim trail.
DomainReport component: SWR no polling; badge STALE|REGENERATED|CACHED, UTC timestamp, #hash[:8]; `[ update report ]` → POST refresh → mutate(fresh,{revalidate:false}); errors shown with "showing previous cached report"; body via reportBlocks (split /\n{2,}/, heading = ^#{1,3} line, rest para) + inline **bold**/*em* only. Sub-report label `<section>_report · <title>`.

## 12 PROVENANCE / REBUILD (offline, outside server)
abductive_engine: press.py (Guardian artanddesign + NYT Art, 2000-01→2026-09) → reading.py (Claude Haiku via `claude -p`, fixed claim form: who/about/asserts/force{reports,judges,predicts,doubts}/stance{approval,disapproval,neither}; out-of-form refused) → ground.py (names+numbers in article; 561,133 claims) → embed (nomic-embed-text) → synthesis (concepts) → names.py (strip proper names) → trends.py (qwen3.6 names) → evals/export_*.py.
POE evals: artist_records.py, concept_snapshot.py, trend_snapshot.py, success_records.py, success_run.py (8 cores), themes_run.py, lives_run.py, life_graph_run.py, champions.py, success_snapshot.py → the JSON in §2. Plan of record: abductive_engine/ART-PLAN.md (plan before run, predictions, dated deviations). Raw data ~/Documents/art-press-texts (1.4GB), ~/Documents/art-market-reports. Don't push POE during a rebuild.

## 13 INVARIANTS (test-worthy)
I1 no panel shows a value not from the engine; fetch failure → visible error.
I2 a scheme is scored on year Y only by fits on years < Y (prequential).
I3 leader change needs >3 nats decayed standing over leader AND each combination >3 over each one-smaller part.
I4 most_raised ranks by lift over own past, never by raw likelihood.
I5 gain shown for a set = leader-path gain, not best mechanism's gain.
I6 success verdicts/strength words come from code thresholds 10/100; writer restates, never derives.
I7 description-only outputs (trend lists, rewarded, themes without record, lives, at_the_top market prompt) never coloured or worded as causes.
I8 GET report routes never call the LLM; POST calls it only on hash change (+ prompt version).
I9 life sentence survives only if cited ⊆ given ∧ word rule passes ∧ every reader says y.
I10 snapshots are static per deploy; any change in output requires a rebuilt JSON or code/prompt change.

## 14 KNOWN GAPS / RISKS
G1 POST …/refresh routes and /v1/ingest/trigger are unauthenticated; refresh can spend Fireworks credit (SNAPSHOT §6.6).
G2 RegimeStatePanel issues 13 inference POSTs per viewer every 30s for signals the console itself says carry no links.
G3 /v1/cases cold compute 36s (laptop); first request before warm thread finishes blocks on the lock.
G4 tooltips hard-code 2001–2024; trends set runs to 2025.
G5 "-0 nats" rendering for small negative gains (trends set).
G6 CaseGraph draws single-feature edges only; a combination leader appears as several amber single edges with their solo gains.
G7 good_life/poor_life lack dashboard labels (raw keys if ever in a leader; press life leader currently includes good_life but LivesPanel doesn't render leaders).
G8 success.year=2026 and forecast_for=2026 coincide while kinds score to 2024; header reads "forecast for 2026".
G9 data limits: 2 papers (NYT lead paragraphs only), 2 museums, museum-collected artists only, Top 500 only, features from a model's reading, lives from one year's championed; yearly manual rebuild.
G10 life readers are models: faithful synonyms can be cut; joins can juxtapose two real people's claims (accepted, ART-PLAN 15.19).
