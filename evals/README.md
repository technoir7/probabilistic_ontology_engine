# Does the engine notice when the economy changes? A replay of 2003–2026

*The plan was written before the measured replay ran; results are at the end.*

The engine is a demonstration of epistemology, not a forecaster: of how
beliefs should be held, revised and given up. So this measures its belief
revision, not its predictions. A rational believer changes its mind when the
world changes, keeps it otherwise, and holds a structure only if it explains
the evidence better than believing nothing connects. Nothing in the engine
is tuned for accuracy here, at that cost or any other.

The engine keeps several competing explanations of how eight macro signals
relate (inflation, the yield curve, Fed liquidity, credit spreads,
volatility, the dollar, the labour market, tech momentum), scores each on
the evidence, and records a paradigm shift when the leading explanation
changes. This asks whether those shifts mean anything: replayed week by week
through twenty years of real data, does the leading explanation change when
the economy did, and does the structure it learns explain each week better
than assuming the signals are unrelated?

## The data

Weekly evidence for the macro domain (`macro-regime-v1`), built by its own
pipeline (`compute_snapshot`) from FRED's full history of each series,
fetched once as public CSV files and kept in `evals/data/fred/`. One record
per week, every Friday from 2003-04-04 (WALCL begins in December 2002 and
its signal needs 14 weeks) to the latest. Each week sees only what had been
published by then (CPI about 45 days after its month, unemployment about
36), within the lookback the live client asks FRED for.

One substitution: FRED now serves the ICE BofA high-yield spread
(`BAMLH0A0HYM2`) only from October 2023, so `CreditSpreadStress` would be
missing for nineteen of the twenty years. The replay uses Moody's Baa
corporate yield minus the 10-year Treasury (`BAA10Y`, from 1986) under the
same rule (above its rolling 52-week mean by a z-score of 1 or more). The
two are reported side by side over the three years both exist.

The data are today's revised series, not what was known each week (CPI and
unemployment are revised after release); the replay can know slightly more
than the engine would have live.

## The replay

A fresh engine, as the app runs it (same scoring, pruning, mutation and
half-life), learns the records oldest first, one learning cycle per week.
After each week it records the leading candidate, which seed explanation it
descends from (its family: monetary, credit, AI boom, recession, null), every
candidate's score, and the structure entropy. Mutation is random, so the
replay runs with 5 seeds (0–4) and every result is reported for each seed
and as the median.

## The events

Fixed here, before any replay, with the date each began:

| Event | Began | Source |
|---|---|---|
| The 2008 recession | 2007-12 (NBER peak) | NBER |
| Lehman Brothers fails | 2008-09-15 | |
| The taper tantrum | 2013-05-22 (Bernanke's testimony) | Federal Reserve |
| The first hike after zero rates | 2015-12-16 | Federal Reserve |
| Quantitative tightening begins | 2017-10 | Federal Reserve |
| The COVID crash | 2020-02 (NBER peak); markets 2020-03-09 | NBER |
| The 2022 hiking cycle | 2022-03-16 (first hike) | Federal Reserve |
| Quantitative tightening resumes | 2022-06-01 | Federal Reserve |
| Silicon Valley Bank fails | 2023-03-10 | FDIC |
| ChatGPT is released | 2022-11-30 | OpenAI |

## Questions

1. **Do shifts follow events?** For each event, does the leading
   explanation change family within 26 weeks after it began? Reported per
   event and seed. Against chance: the same number of family changes placed
   at random weeks (10,000 draws), the share of events they would "catch".
2. **How many shifts happen away from any event?** Family changes more than
   26 weeks after every event, per seed. A shift a quarter is noise, however
   well some line up.
3. **Does the learned structure explain each week better than none?** Each
   week, before learning it, the leading candidate's probability of that
   week's eight signals (soft evidence, as learned) against a baseline that
   treats them as independent, learned from the same evidence with the same
   half-life. Reported as average log-likelihood per week, overall and by
   period. If structure does not beat independence, the explanations it ranks
   are telling us little.
4. **Does the leader match the story told at the time?** A stated
   expectation, not a test the engine was built to pass: credit-first or
   recession leading through 2008–09; monetary or recession through 2022–23;
   AI boom in 2023–24. Reported as the weeks each family led in each period.

Shown as one chart: the leading family week by week for each seed, with the
events marked.

## Pilot, and two fixes before the measured run

A pilot replayed 2006–2009 with seed 0, to check the replay runs (208 weeks
in about two seconds) and that its signals match what happened. It is part
of the measured period; the events, window and questions above were fixed
before it and not changed after. It found two faults in how the macro
domain reads FRED, both in the live app, both fixed before the measured run:

- **DollarStrength was inverted.** `DEXUSEU` is dollars per euro, so a
  lower rate is a stronger dollar; the domain read a higher one as stronger
  (the sovereign-debt and crypto domains read it correctly). Through 2007,
  as the dollar fell, it read "dollar strength" every week.
- **The CPI lookback was too short.** CPI for a month is published about 45
  days after it begins; a 430-day lookback then holds 12 published months
  for part of every month, one short of what the inflation signal needs, so
  InflationShock went missing. It is 480 days now. Measured over 2024–2026,
  the old lookback would have lost the signal in about half of all weeks.

Nothing about the engine is changed in response to the replay. A change it
suggests would be measured on a new replay, written up separately.

Not tested: other domains, and whether any of this would help anyone make a
decision.


## A third fix, after the replay ran

The first full replay gave all five seeds exactly the same result. The
engine takes a `random_seed` but never handed it to the PopulationManager,
which always mutated with `random.Random(42)`; so every engine, whatever its
seed, has made the same "random" choices, and SPEC §2.2's reproducibility
from a seed was reproducibility from 42. The seed now reaches it
(`tests/level3/test_engine_seed.py`); the app, which uses 42, is unchanged.
The replay was run again with five seeds that differ. The first run is kept
in `data/replay/as-run/`; its one result was the same as seed 0's in kind
(no family change, structure ahead of independence by 0.21 nats a week).

## Results

![The leading explanation, week by week](../docs/replay.svg)

1229 weeks, 2003-04-04 to 2026-10-16, five seeds.

1. **Do shifts follow events? No: the leading family never changed.** In
   every seed the leader descended from `T_null` every week of the 23
   years, so no event was followed by a family change, and chance, with
   none to place, catches none either.
2. **Shifts away from events: none**, for the same reason.
3. **Is the learned structure worth believing over "nothing connects"?
   Yes, except when the world broke.** Each week, before learning it, the
   leading structure gave that week's eight signals more probability than
   independent signals did, by 0.17 to 0.29 nats a week across the seeds
   (median 0.24). By period, median of seeds:

   | Period | Gain over independence (nats a week) |
   |---|---:|
   | 2003–07 | 0.12 |
   | 2007–09 | 0.32 |
   | 2010–19 | 0.28 |
   | 2020–21 | **−0.36** (every seed below zero) |
   | 2022–23 | 0.91 |
   | 2024–26 | 0.21 |

   Through COVID every seed would have done better believing nothing
   connected: the relationships it had learned over seventeen years broke,
   and it did not let go of them fast enough. By 2022 it had relearned
   them, and the tightening cycle is where its structure helped most.
4. **Did the leader match the story told at the time? No.** `T_null`'s
   line led throughout 2008–09, 2022–23 and 2023–24 in every seed; the
   credit, recession, monetary and AI-boom explanations were not there to
   lead.

**Why: the rivals die young.** The population starts with ten candidates
across the five seed explanations. Within 14 to 25 months, by mid-2004 to
mid-2005 in every seed, every active candidate descends from `T_null`.
Most likely, the sparsest explanation scores best while evidence is thin
(its BIC penalty is smallest), pruning removes the bottom quartile, and new
candidates are bred only from the survivors, so once a lineage leads early
the others have no way back. This was not tested separately. What the engine calls a paradigm shift after that
(29 to 52 changes of leader per seed, 20 to 27 distinct leading structures)
is one lineage adding and removing an edge at a time: normal science, in
Kuhn's terms, with no rival paradigm left to shift to.

Not planned, so only exploratory: those within-lineage leader changes do not
follow the events more than chance would. The share of events followed by
one within 26 weeks ranged from 2 to 8 of 10 across seeds, against 4.7 to
6.8 at random; the chance of doing as well at random was 0.12 to 0.99. Every
seed did change leader within 26 weeks of Lehman's failure.

**The stand-in credit spread** (Moody's Baa less the 10-year Treasury)
agreed with the ICE high-yield spread's CreditSpreadStress in 71 of the 104
weeks both could be read (68%). Close enough to carry the variable's
meaning, not to stand for it exactly; the high-yield spread reacts faster.

**Also found, in the live app's data.** In a backup of the live macro
database (2026-10-16), 2,674 of its 4,144 evidence records (65%) carry no
information: every signal recorded as 50/50 at confidence 0.5. Most were
written on days other than Fridays, though the domain is weekly. Current
code records a signal it could not compute as MISSING rather than 50/50
(REFACTOR_SPEC D10), so these are probably from older code, but the live
population learned from them, and the dashboard shows what it learned.

## What this suggests, for the epistemology

These are not changes made here; each would be a new replay.

- **Keep rivals alive.** A believer that lets every alternative die cannot
  change its mind, only adjust it. Pruning within each seed lineage rather
  than across the population, or keeping at least one candidate per
  lineage, would keep Lakatos's competing research programmes in play, so
  that a shift between worldviews stays possible.
- **Let a broken structure lose faster.** COVID is where it held its
  beliefs too long. A score half-life that shortens when the leader's
  recent surprise is far above its usual (a crisis widens the window of
  doubt) would let it give up a failing structure sooner, without making it
  fickle in calm years.
- **Clean the live record, and relearn it.** Rebuild the live macro
  population from this replay's evidence, after removing the blank records.

## Replay 2: rivals kept until refuted

*Plan, written before replay 2 ran.*

The change (REFACTOR_SPEC D15): every candidate carries the seed explanation
it descends from, its research programme, and pruning spares each
programme's best candidate until the evidence for the leader over it is
decisive, a Bayes factor above 100 on Jeffreys' scale. A programme can still
be abandoned, but only when refuted, not for ranking low while the evidence
is thin. Nothing else changes: same data, events, window, seeds and
questions as above, written to `data/replay2/`.

One question more:

5. **Do the rivals survive, and do they ever lead?** The number of
   programmes alive each year, and the weeks each one leads. If they
   survive but never lead, the population keeps alternatives in mind
   without ever finding the evidence to adopt one.

A change in the fit gap (question 3) is reported but not expected: the
leader is still the best-scoring candidate, so keeping rivals should not
make it worse, unless it changes which lineage breeds.

### Replay 2 results

![Replay 2](../docs/replay2.svg)

1. **Shifts and events: still none caught.** Three seeds changed family
   twice, both times in the same two weeks of July 2005, when the AI-boom
   programme led for one week; no event was followed by a family change.
2. **Shifts away from events:** those two, in three seeds.
3. **Fit gap:** 0.19 to 0.30 nats a week (median 0.24, as before). Through
   COVID, three seeds still did worse than independence; two did not.
4. **The story told at the time:** not matched; `T_null`'s line led
   2008–09, 2022–23 and 2023–24 in every seed.
5. **Rivals survived longer, then were refuted.** All five programmes were
   alive in 2003; two in 2004 and 2005; by 2008, one in every seed. The
   rivals were not lost for ranking low: by 2008 the evidence against each
   passed 100 to 1.

So the null lineage's win holds up under a fairer rule. One unfairness
remains: variants are bred from the best-scoring candidates first, so a
rival programme rarely gets offspring while the leading lineage keeps
exploring. A programme judged without being allowed to revise its
auxiliary hypotheses (in Lakatos's terms) has not had a fair trial.

## Replay 3: a fair trial for rivals

*Plan, written before replay 3 ran.*

The change (REFACTOR_SPEC D16), on top of replay 2's: each round of breeding
starts with a different programme's best candidate, so every surviving
programme gets to revise itself. Same data, events, seeds and questions
1–5, written to `data/replay3/`. If the rivals still fall by 2008, the null
lineage's win is not an artefact of who was allowed to breed.

## Replay 4: doubt in a crisis

*Plan, written before replay 4 ran.*

The change (REFACTOR_SPEC D17), on top of replay 3's: when the leading
structure is more surprised by a week than its usual by two standard
deviations (after a year of evidence), every candidate's learned counts and
score window count for half before it learns that week. Ordinary weeks
change nothing. Same data, events, seeds and questions 1–5, written to
`data/replay4/`, and one more:

6. **When does it doubt, and does doubt help?** The weeks it judged a
   crisis, against the events; and the fit gap through COVID (2020–21),
   where replays 1–3 did worse than independence in most seeds, and in
   calm periods, where doubt could make it worse.

### Replay 4 results

![Replay 4](../docs/replay4.svg)

Run twice: first with the independence baseline remembering everything
while the candidates forgot in a crisis, which made structure look twice as
good as it was; then, as the plan intended ("learned from the same
evidence"), with the baseline forgetting on the same weeks. Only the second
is reported.

1–2. **Shifts and events: none caught.** One seed (4) changed family nine
   times between 2005 and 2007, ending with the AI-boom programme leading
   from September 2007 to the end; none of the changes followed an event.
3. **Fit gap:** 0.13 to 0.24 nats a week (median 0.17), lower than replay
   3's 0.27, because the independent baseline also gains from forgetting.
   **Through COVID every seed now beats independence** (0.07 to 0.28),
   where four of five fell below it before.
4. **The story told at the time:** not matched.
5. **Rivals:** one programme alive from 2008 in four seeds; two in seed 4
   until 2020.
6. **Doubt.** 21 to 38 crisis weeks per seed over 23 years, most of them in
   2005–06, while the population was still settling; others in 2009, 2010–11,
   2015–16 and 2018–19. They do not line up with the events either. Doubt
   helps the believer: its own average log-likelihood per week rose from
   −4.96 to −4.62 (median of seeds), from −5.33 to −4.41 through COVID, and
   from −4.66 to −4.45 in 2010–19, so it did not make calm years worse.

## Replay 5: calibration and humility

*Plan, written before replay 5 ran.*

The change (REFACTOR_SPEC D18) observes and learns nothing: before each
week is learned, the engine records how well the whole population, each
structure weighted by its posterior weight, predicted that week, and, for
each signal, the probability the leader and the weighted population gave it
being true given the week's other seven signals. Learning is replay 4's, so
the leaders and crises are the same; written to `data/replay5/`.

7. **Humility: does the weighted population explain the evidence better
   than its leader?** Average log-likelihood per week, population against
   leader.
8. **Calibration: when it says 70%, is it right 70% of the time?** The
   Brier score and the expected calibration error (ten bins) of the
   leader's and the population's leave-one-out probabilities, against a
   believer that always says each signal's base rate so far.

### Replay 5 results

7. **Humility gains nothing yet.** The weighted population predicted each
   week as well as its leader and no better (−4.57 to −4.71 nats a week,
   within 0.006 of the leader in every seed): with posterior weights taken
   over a window of about 150 records, nearly all the weight sits on the
   leader. The population is all but certain of its favourite.
8. **Its confidence is informative but timid** (replay 9 found the timidity
   was in the measure, not the engine). Over 9,824 judgements per
   seed, its Brier score was 0.16 to 0.17 against 0.216 for a believer
   saying each signal's base rate, so it knows a good deal about each
   signal from the others. But its calibration error (0.07 to 0.10) is a
   little worse than the base rate's (0.06), and in the direction of
   diffidence: when it said 15% the signal was true 3% of the time; when it
   said 84%, 97% (seed 0). It holds its beliefs more weakly than its
   evidence warrants.

## Replay 6: beliefs about change

*Plan, written before replay 6 ran.*

The change (REFACTOR_SPEC D19), on top of replay 5's: each signal has a
companion holding its value last week, which any structure may take as a
parent and none may explain, and a sixth programme, `T_persistence`, holds
that each signal follows its own last week and nothing else. Each week the
leader's forecast is also recorded: the probability it gave this week's
signals from last week's alone, before seeing any of them. Explanation
still decides what is believed; the forecast is watched, not rewarded.
Same data, events, seeds and questions 1–8, written to `data/replay6/`,
and one more:

9. **Is persistence the better worldview, and does believing in change
   forecast better?** Which programmes lead and survive with persistence
   available; the leader's forecast log-likelihood per week, against
   replay 5's leader, which could only forecast from base rates (its
   structure had nothing to go on but this week).

### Replay 6 results

![Replay 6](../docs/replay6.svg)

1–4. **Shifts, events and the story: as before.** Every seed's first leader
   was `T_persistence`, for five weeks; then the leader passed to another
   programme and stayed (in four seeds `T_null`'s line; in seed 2, after
   six changes in 2003–07, the AI-boom line). No event was followed by a
   family change.
5. **Rivals:** two programmes alive into 2004–08, one from 2015.
7–8. **Humility and calibration:** much as in replay 5 (Brier 0.16 to
   0.17; the population no better than its leader).
9. **Persistence won by being absorbed.** It led only the first five
   weeks, yet by 2003–05 every surviving programme's leader had taken links
   from last week (3 to 8 of its 6 to 11 links by 2026), mostly a signal
   following its own last week, and `T_persistence` was refuted as a rival
   while its idea lived on in the others: a programme absorbing a rival's
   content, in Lakatos's terms. With them the leader explains each week far
   better than in replay 5 (−2.2 to −3.6 nats a week, from −4.6), and
   forecasts each week from last week's signals alone at −3.8 to −4.1 nats,
   against −4.8 for base rates. The fit gap over independence (question 3)
   rose to 1.2 to 2.6 nats a week, but most of that is persistence, which
   the independent baseline does not have.

## Replay 7: as first published

*Plan, written before replay 7 ran.*

Replays 1–6 used today's revised CPI and unemployment, so each week could
know a little more than it did at the time. Replay 7 is replay 6 with those
two series as they were first published: for each week, the latest
monthly ALFRED vintage taken on or before it (CPI on the 16th, after its
mid-month release; unemployment on the 8th, after its first-Friday
release), so a week may see a release a few days late but never one not yet
made. The market series are not revised. Written to `data/replay7/`; the
engine is replay 6's.

10. **Does honesty about what was known change the beliefs?** Questions
    1–9 as before, and how many weeks the inflation and labour-market
    signals differ from replay 6.

### Replay 7 results

![Replay 7](../docs/replay7.svg)

10. **Honesty about what was known changed little.** As first published,
    InflationShock differed from replay 6 in 37 of 1,229 weeks and the
    labour signal (EquityRiskOn) in 28. The beliefs barely moved: `T_null`'s
    line led throughout in two seeds and almost throughout in the others,
    where the AI-boom line led for 11 to 42 weeks; no event was followed by
    a family change. The leader explained each week a little less well in
    four seeds (it knew a little less) and better in one, forecast it from
    last week at −3.6 to −4.1 nats against replay 6's −3.8 to −4.1, and was
    as timid (Brier 0.14 to 0.17). So nothing in replays 1–6 rests on
    hindsight; replay 7 is the honest baseline from here on.

## Replay 8: five levels

*Plan, written before replay 8 ran.*

The change (REFACTOR_SPEC D20), on top of replay 7's: each macro signal is
recorded in five ordered levels, from well below its threshold to far past
it, cut from the same evidence (the three levels past the threshold sum to
the old probability of "true"). Same data as first published, events,
seeds and questions as replay 7, written to `data/replay8/`. Log-likelihoods
over five levels and over two are not on one scale, so the comparison with
replay 7 is made where they agree:

11. **Does believing in degrees make it a better believer?** The Brier
    score and calibration error of its belief that each signal is past its
    threshold, given the others (the same event replay 7 judged), against
    replay 7; which programmes lead; how many links the leader holds; and,
    within each replay, the fit gap over independent signals and the
    forecast from last week against base rates.

### Replay 8 results

![Replay 8](../docs/replay8.svg)

11. **Degrees made it more careful and less knowing.** Judged on the same
    event as replay 7 (is each signal past its threshold, given the
    others), its calibration error fell (0.060 to 0.078 against replay 7's
    0.066 to 0.119; it is less timid) but its Brier score rose (0.19
    against 0.14 to 0.17; it knows less from the other signals). Its
    leader held 2 or 3 links where replay 7's held 8 to 13, and its gain
    over independent signals fell to 0.04 to 0.26 nats a week. The cause
    is the price of a relationship: explaining a five-level signal by a
    five-level cause takes 20 numbers where a boolean pair took 2, and the
    BIC penalty, the engine's Occam's razor, finds that 23 years of weekly
    evidence support few relationships at that resolution. Persistence was
    worth more: from last week alone it forecast each week 1.6 nats better
    than base rates (replay 7: 0.8, on its own scale). `T_null`'s line led
    every week in every seed; no event was followed by a change.

    A finer instrument asks for more evidence per belief. Levels would pay
    for relationships with more data, or with tables that use the levels'
    order (an ordinal model needs a few numbers per cause, not 20). The
    engine went back to yes/no signals; the levels are in commit 1290d1c6,
    to try again with ordinal tables.

## Replay 9: timid, or judged unfairly?

*Plan, written before replay 9 ran.*

Replays 5 to 8 judged the engine's beliefs against each signal rounded to
true or false. But the engine learns from soft evidence: on the weeks a
signal rounds to true, the evidence itself puts it at 0.75 on average (and
at 0.20 on the weeks it rounds to false; 9,914 judgements as first
published). A belief learned faithfully from that evidence says about 75%
on weeks that score as 100% true, and looks timid by construction.

The change (REFACTOR_SPEC D21) measures, alongside the old score, the
leader's calibration against the probability the evidence gave each signal.
Nothing the engine learns changes. Same data as first published, seeds and
events as replay 7, written to `data/replay9/`:

12. **Is the timidity in the engine or in the measure?** If in the measure,
    the leader's calibration error against the evidence will be far below
    its error against the rounded signal (replay 7: 0.066 to 0.119), and
    in each bin what it says will be near what the evidence says. If the
    error against the evidence stays near replay 7's, the engine is timid
    and the cause is still to be found.

### Replay 9 results

12. **The timidity was in the measure.** Against the probability the
    evidence gave each signal, the leader's calibration error was 0.010 to
    0.014 across the five seeds, against 0.066 to 0.119 against the signal
    rounded (unchanged from replay 7, as it should be: nothing learned
    changed). In no bin did what it said differ from what the evidence said
    by more than 0.043; seed 0 said 0.15 where the evidence said 0.12, 0.74
    where it said 0.73, 0.84 where it said 0.85. Its Brier score against the
    evidence was 0.037 to 0.052. Replays 5 to 8 called it timid; it was
    holding its beliefs exactly as firmly as its evidence did, and being
    scored against a certainty the evidence never had.

    One distortion remains: each judgement conditions on the week's other
    signals rounded to true or false, so the engine is asked a slightly
    sharper question than its evidence supports. It did not show here.

## Replay 10: a fair trial for rival worldviews

*Plan, written before replay 10 ran, and after diagnostic runs of seed 0
that found the three faults below.*

Replays 3 to 9 found every rival programme refuted by 2005–08, and none
ever revised: each died holding every link it was founded with. Recording
each programme's best candidate week by week showed why:

- **Refuted by the razor.** For their first eight weeks the six seeds
  explained the evidence within half a nat of each other; the BIC penalty,
  not the evidence, put the rivals past the refutation line. The windowed
  score is prequential from even tables, so it already charges a complex
  structure for the parameters it must learn; BIC charged it again.
- **Refuted on a free week.** A variable whose parent was not observed was
  not scored, which scored it as certain. In the first week nobody has a
  last week, so persistence scored zero log-loss where every other seed
  lost 5.5 nats, more than the refutation line.
- **Refuted for a claim no rival denied.** With the first two fixed, the
  causal programmes died within four weeks for not knowing that signals
  persist, before any had a turn to add it.

The changes (REFACTOR_SPEC D22, D23): refutation compares average
log-likelihood over the records both candidates were scored on, without
BIC (which still ranks them); a missing parent is averaged over as the
data has seen it; every causal seed assumes persistence as a shared
auxiliary, and `T_persistence`, persistence alone, is the baseline they
must beat. Same data as first published, seeds and events as before,
written to `data/replay10/`:

13. **Do rivals now live until the evidence refutes them, and does any
    programme displace another?** Weeks each programme survives and leads;
    whether any rival is revised (holds a link it was not founded with)
    before it dies; leader changes against the events; calibration against
    the evidence, fit gap and forecast against replay 9.

### Replay 10 results

![Replay 10](../docs/replay10.svg)

13. **Rivals now live until the evidence refutes them, and none displaces
    persistence.** Monetary lived 386 weeks (to 2010) in every seed,
    recession 373 (to 2010), credit 696 (to 2016); AI boom and the sparse
    baseline lived to 2014–15 in some seeds and to the end in others. Most
    revised themselves before dying (AI boom and the sparse baseline in
    four seeds of five, credit and monetary in one; recession never). Where
    replays 3 to 9 refuted them within weeks, these are refutations by
    evidence, after years of it. But persistence alone led every week of
    every seed: given that each signal follows its own last week, no
    worldview's further claims explained the weeks better. No leading
    programme changed, so no event was followed by a change.

    Persistence explains each week 0.56 to 0.57 nats better than
    independent signals and forecasts it from last week alone at −3.35 to
    −3.37 nats (base rates: −4.8). Calibration against the evidence is
    0.046 to 0.048, worse than replay 9's 0.010 to 0.014: in the middle it
    is unsure, saying 0.56 where the evidence says 0.65. Each judgement
    conditions on last week's values rounded to true or false, which is the
    likely cause.

    **A correction to replays 6 to 9.** Their fit gap scored the leader on
    each week's record before last week's values were attached, and a
    variable whose parent was missing was skipped, which scored it as
    certain. Every leader holding last week's values as causes was credited
    with those variables free, so their fit gaps (and replay 6's "explains
    each week far better") are overstated. Their forecasts, calibration,
    survival and leaders came from the engine's own scoring and stand,
    except as the skipped-variable fault touched the engine too (replay 10's
    second fault).

## Replay 11: an engine given no hypotheses

*Plan, written before replay 11 ran. The design it tests was settled
against the synthetic milestone (EPISTEMOLOGY.md §2), not against any
replay; nothing here has been run on the FRED data.*

Replays 1 to 10 began from six worldviews written by hand in 2026, by
someone who knew how 2003–2026 turned out. However carefully the evidence
was kept to what was first published, the hypotheses carried hindsight.
REFACTOR_SPEC D24 removed them. The engine now begins with the eight
signals, each one's value last week, and one explanation that connects
nothing. Each week it offers each programme's best explanation the
connection, or reversal, that its last 100 records most support beyond
BIC's penalty, judged only on the weeks after. Blind variants revise what
it has formed and never form anything from nothing. Persistence is no
longer assumed.

Same data as first published (ALFRED), seeds 0–4, the same events and
window, written to `data/replay11/`. Compared with replay 10 throughout.

14. **Does it find persistence, and how soon?** For each signal, the first
    week the leader holds "this signal last week bears on it", and the
    share of weeks after that it keeps holding it. Expected: all eight
    within the first year, since in replay 10 persistence explained each
    week 0.56 nats better than independent signals. If any signal's
    persistence is never held, that is a finding about the engine, not the
    signal.
15. **Does anything it forms explain the weeks better than persistence?**
    The leader's fit gap over independent signals, week by week and over
    the whole run, against replay 10's 0.56–0.57 nats; and every link
    between two different signals that a leader holds for 52 weeks or
    more. A better fit with such links would be the first evidence that
    the signals bear on one another. The same fit with none would say
    replay 10's verdict did not depend on the hand-written worldviews.
16. **Do its changes of programme follow the events?** Programme changes
    (worldview changes, not revisions) against the ten events, within 26
    weeks, as before; and changes away from any event.
17. **Is it still calibrated?** Calibration against the evidence and the
    forecast from last week alone, against replay 10's 0.046–0.048 and
    −3.35 nats.

What would count against the design: a leader that never holds most of
the persistence links, a fit gap well below replay 10's, or a population
that fills with programmes the evidence never refutes.

### Replay 11 results

Five seeds, 1,229 weeks each, about 110 seconds a seed. The seeds agree
closely: what the engine forms depends far more on the evidence than on its
blind variation.

14. **It finds most of persistence, slowly, and only where the signal
    moves.** Nothing was connected for the first 170 weeks (to mid-2006):
    the weekly evidence is soft, and read as probabilities, "this week is
    like last" is a faint pattern in a few dozen records. The first
    persistence held was the dollar's (June 2006), then tech momentum's
    (December 2006), credit's (November 2007), inflation's (late 2008) and
    liquidity's (August 2009); the labour signal's in three seeds of five.
    Once held, each was kept in 91% or more of the weeks after, except tech
    momentum's in one seed (41%). Two were never held
    in any seed. The yield curve matches the week before 98% of the time,
    but it was inverted in few periods, and within any 100 weeks in which
    it never changes, persistence predicts it no better than how often it
    is inverted; there is nothing to learn from. Volatility is the softest
    signal (mean confidence 0.67) and the least persistent (77%).
15. **Nothing it forms explains the weeks better than given persistence
    did.** The fit gap over independent signals is 0.44 to 0.51 nats a
    week, against replay 10's 0.56, and the forecast from last week −3.60
    to −3.70 nats, against −3.35. Most of the shortfall is the three years
    with nothing connected and the persistence it never found. Every seed
    held one link between different signals for about 955 weeks, last
    week's credit stress bearing on the yield curve, first held in June
    2008, from 100 weeks spanning the curve's 2006–07 inversion and the
    credit stress that followed. Three seeds also held the dollar bearing on
    the labour signal for 366 to 915 weeks. These are the first cross-signal links any replay has
    kept, but they come with a worse fit, not a better one, so they are not
    yet evidence that the signals bear on one another.
16. **Its changes of programme do not follow the events.** Five to nine per
    seed, all between 2006 and 2009, catching 0 to 2 of the ten events
    within 26 weeks, no more than chance (p 0.48 to 1.0); five in each seed
    came away from any event. After 2009 one programme led to the end.
17. **It is better calibrated.** Against the evidence, 0.022 to 0.027,
    against replay 10's 0.046 to 0.048: holding fewer links, it is less
    often confidently wrong.

Against the plan's tests: it holds most of the persistence links (five to
six of eight), its fit gap is below replay 10's by 0.05 to 0.12 nats, and
the population did not fill with unrefuted programmes (one alive from
2013). Replay 10's verdict, that no account beats persistence, did not
depend on the hand-written worldviews. The cost of not being told is three
years of believing nothing, and two signals whose persistence a 100-week
memory cannot see (NEXT.md problem 8).

## Replay 12: degrees read as levels

*Plan, written before replay 12 ran. Two probes on the same macro history
were run first and informed it: from nothing, on the last 100 weeks, the
evidence supports 3 links beyond BIC's penalty with signals read as soft
yes/no, and 8 (all persistence) read as three levels; on all 23 years, 10
(8 persistence, 2 between signals) and 8 (all persistence). Expectations
below lean on them.*

Every macro signal used to reach the engine as P(True), a sigmoid of its
distance past the line that names it. That read a degree as a doubt, and
counting each doubt apart from the others blurred relations toward
independence (EPISTEMOLOGY.md §3). REFACTOR_SPEC D25 reads each signal as
one of three levels, observed exactly: low, middle or high, cut at half a
unit either side of the line. Nothing else changes from replay 11. Same data
as first published, seeds 0–4, events and window, written to
`data/replay12/`.

Log-likelihoods over three levels and over two are not on one scale, so as
in replay 8, comparisons with replay 11 are made within each replay:

18. **Does it find persistence sooner, and for every signal?** The first
    week the leader holds each signal's persistence, and the share of weeks
    after that it keeps it, against replay 11 (5–6 of 8, none before 170
    weeks; never the yield curve or volatility). Expected: all 8, within
    the first two years.
19. **Does anything beyond persistence earn its place?** Every link between
    two different signals a leader holds for 52 weeks or more, against
    replay 11's (credit stress last week to the yield curve, about 18
    years; the dollar to equities in 3 seeds). Expected: fewer, since a
    relation between three-level signals costs three times as much.
20. **How much better than independent signals, on its own scale?** The
    leader's fit gap over independent three-level signals, and the forecast
    from last week against base rates, each within replay 12.
21. **Do its changes of programme follow the events, and is it
    calibrated?** Programme changes against the ten events within 26
    weeks, as before; calibration level by level (not comparable with
    replay 11's, which judged P(True)).

What would count against the change: persistence found no sooner or for no
more signals than in replay 11, or a leader that holds nothing for years.

### Replay 12 results

18. **Every signal's persistence, in every seed, mostly within three
    years.** The leader left the unconnected start after 19 weeks (replay
    11: 170). Unemployment's trend (EquityRiskOn) persisted from August 2003
    in every seed; inflation, volatility, the dollar, credit stress, NASDAQ
    momentum (AIRiskOn) and the yield curve by early 2006 in all but one
    case (volatility in seed 3, August 2007). The Fed balance sheet was
    last, 2009–10 in four seeds (seed 1 held it from August 2003 but kept it
    only 69% of the weeks after). Once held, each was kept 97–100% of the
    weeks after, bar volatility in two seeds (75%, 88%). Replay 11 never
    held the yield curve's or volatility's.
19. **More beyond persistence, not less, and one link in every seed.**
    Expected fewer; it held more. Every seed's leader held "unemployment's
    trend last week bears on NASDAQ momentum" (EquityRiskOn last week to
    AIRiskOn) for 1,159 to 1,174 of 1,229 weeks, from 2004 to the end.
    Four seeds held one or two more for over a year, differing by seed:
    volatility with unemployment's trend (seed 0), NASDAQ momentum with the
    dollar and the yield curve with the balance sheet (seed 1), NASDAQ
    momentum to volatility (seed 2), and NASDAQ momentum last week to
    volatility with NASDAQ momentum to unemployment's trend (seed 3); seed
    4 held none. Leaders ended with 9 to 11 links. Replay 11's credit-stress-to-yield-curve link
    was not held. A link held in every seed is the first stable finding
    beyond persistence any replay has made, but it is a dependence, not a
    cause: the labour market and tech stocks may both follow the business
    cycle, which the engine has no concept for.
20. **On its own scale, the structure explains far more.** The leader's fit
    gap over independent signals was 2.51–2.55 nats a week, and its
    forecast from last week alone −3.45 to −3.49 nats against −6.00 to
    −6.04 for base rates: 2.5 nats a week better (replay 11, on yes/no:
    1.2–1.3). The scales differ, so the comparison is within each replay.
21. **It settled in 2003 and never changed its mind.** Each seed changed
    programme three times, all between August and September 2003, and the
    unemployment programme then led for 1,210 weeks. No change followed any
    event. From 2008 on, only one programme was alive: its rivals were
    refuted and the evidence prompted no new founding connection the leader
    lacked. Calibration, level by level: 0.036–0.040 (not comparable with
    replay 11's P(True) judgments).

Neither thing that would have counted against the change happened.
Persistence was found sooner, for every signal, and the leader never held
nothing. Two costs showed. With every signal's persistence and a link
between signals held from the first years, the population has had no rival
programme since 2008: nothing it could change its mind to. Questions about
paradigm shifts now turn on revisions within one programme. And the one
stable link joins two concepts named for one thing and measured by another
(EquityRiskOn is read from unemployment; NASDAQ momentum is named AIRiskOn),
so the names say more than the evidence does.

## Replay 13: rivals that can always be founded

*Plan, written before replay 13 ran. Nothing in it has been run on the FRED
data; the design was settled against the synthetic tests.*

Replay 12 settled in 2003 and had no rival programme alive from 2008 on.
Two rules made that inevitable: a programme could be founded only from the
unconnected structure, which was refuted once persistence was found; and a
persistence link founded a programme, so the "rivals" were each one
signal's persistence and converged on the same structure. REFACTOR_SPEC D26
changes both. Persistence is common ground and founds nothing. And whenever
the recent evidence supports a connection between two concepts that the
leader lacks, it founds a rival: the leader's structure without its hard
core, with that connection in its place, level with the leader, while fewer
than half the population's places hold programmes. Same data as first
published, seeds 0–4, events and window, written to `data/replay13/`;
compared with replay 12.

22. **Are there rivals?** Programmes alive, year by year, against replay
    12's one from 2008; how long rivals live; how many are founded.
23. **Does the lead ever change programme, and when?** Changes of programme
    (not revisions) against the ten events within 26 weeks, and away from
    them. A rival that only denies the leader's core and leads has shown the
    core was not needed: those changes are the point.
24. **Does it cost the leader what it had found?** Persistence links and
    the links between signals held for 52 weeks or more, the fit gap over
    independent signals, and the forecast from last week, against replay
    12.

What would count against the change: no rival alive for years again; or
changes of programme every few weeks with no events behind them, which
would mean rivals are founded too level to be told apart; or a leader that
holds less than replay 12's.

### Replay 13 results

22. **Rivals arise when the evidence shows an anomaly, and after 2009 it
    showed none.** Every seed founded rivals through 2004–06, two to three
    programmes alive on average in 2004. From 2008 on there was one again,
    in every seed but one (1.7 in 2008 in seed 2). The founding rule was not
    what stopped them: probed on seed 0's leader every few years from 2009,
    the last 100 weeks supported no connection between two concepts that
    the leader lacked (one offer in January 2009; none at any probe after).
    With nothing the leader fails to account for, there is no anomaly to
    found a rival on, and the rule founds none. The binding limit is the
    100-week memory hypotheses are formed from (NEXT.md problem 8).
23. **The lead changed programme 7 to 22 times per seed, all between 2004
    and 2006, none after an event.** In seeds 2 and 3 some changes came
    weeks apart (July 2004: three in three weeks). That is what the plan
    said would count against the change: rivals founded level with the
    leader, while the window holds little evidence, trade the lead on
    noise. It stopped once the evidence accumulated. Different seeds
    settled on different worldviews: inflation bears on credit stress
    (seeds 1, 2 and 4; in seed 1, last week's inflation), the labour
    trend on NASDAQ momentum (seed 0), NASDAQ momentum on the dollar (seed
    3). Replay 12's seeds all settled on the labour trend; that the
    outcome now depends on the seed says these worldviews explain the
    weeks about equally well, and the evidence does not choose between
    them.
24. **It kept what it had found and fit better.** All eight persistence
    links in every seed's final leader, 9–10 links in all; fit gap over
    independent signals 2.57–2.72 nats a week (replay 12: 2.51–2.55);
    forecast from last week −3.44 to −3.47 against base rates −6.05 to
    −6.16; calibration level by level 0.034–0.038 (replay 12:
    0.036–0.040).

The engine can now change its worldview, and did, early and too readily.
That it did not later is the evidence's verdict at the resolution it can
afford, not the rule's: in Kuhn's terms, normal science without anomaly.
Whether a longer memory for forming hypotheses would show anomalies a
100-week one cannot is the next question (NEXT.md problem 8).

## Replay 14: the leader's core on trial

*Plan, written before replay 14 ran. Nothing in it has been run on the FRED
data; the design was settled against the synthetic tests.*

After 2009 replay 13's leaders were never challenged: a rival needs an
anomaly, a connection the recent evidence supports that the leader lacks,
and there was none. A longer memory would not supply one: probed on seed
0's leader, 200 weeks offered one connection (January 2009) and 400 weeks
none. REFACTOR_SPEC D27 tests the core instead of waiting for an anomaly.
While no other worldview is alive, the engine founds a trial of the
leader's core: its structure without the connection that founded its
programme, everything else kept, level with it on score. Without its core
it holds no worldview. The leader keeps the core only by predicting better
from here on, by more than the core costs in complexity. A trial is refuted
only when the evidence is decisive against it on fit and on score both, so
it is not refuted for the fit it gave up by being simpler. Same data as
first published, seeds 0–4, events and window, written to
`data/replay14/`; compared with replay 13.

Blind variants could already drop the core by chance, keeping the
programme's name, and the leaders kept their cores through 2026; so the
expected answer is that the cores survive. The question is whether they do
when tested on purpose and fairly.

25. **Does the core survive its trials?** Trials founded per seed; how long
    each lives; how many lead. A trial that leads has shown the core was not
    needed: the leader's worldview is given up.
26. **Does testing make the lead change on noise?** Changes of programme
    after 2009 (replay 13: none), against the ten events within 26 weeks,
    and how many weeks apart.
27. **Does it cost the leader what it had found?** Persistence links, the
    links between signals held for 52 weeks or more, fit gap, forecast and
    calibration, against replay 13.

What would count against the change: trials that take the lead every few
weeks with no event behind them; or a leader that holds or predicts less
than replay 13's.

### Replay 14 results

The first run's recorder listed every link a leader carried, including
links edge existence (Level 2) had switched off, which the engine no longer
reasons with. Found when seed 1 never put its core on trial: the core had
been switched off. The recorder now lists only links in use; the figures
below are from the rerun. Replays 11–13 were recorded the old way (see the
note on replay 13 below).

25. **The cores did not survive.** In four seeds a trial took the lead:
    seed 0 in July 2005, seeds 2 and 3 in August 2005, seed 4 in May 2006.
    In seeds 0, 2 and 3 the lead went back and forth three to five times
    through 2005, then stayed. The trials that led held no other link
    between signals either. In
    seed 1 no trial was founded after 2004, because there was no core to
    try: its leader has been named for last week's inflation bearing on
    credit stress since May 2006, but from mid-2009 that link was switched
    off in every week (NEXT.md problem 10). So in every seed the leader
    from 2009 on holds each signal's persistence and nothing else: no link
    between two signals was in use in any week after mid-2009, except 8
    weeks in seed 3.
26. **It did not change on noise after 2009.** Seeds 0, 1 and 4: no change
    of programme after 2009. Seeds 2 and 3: four each, all in August–
    November 2010, when the evidence prompted a new programme (last week's
    equity risk bearing on liquidity stress), which led twice for a few
    weeks and lost both times. That is the engine forming a conjecture and
    the evidence refuting it, not a trial trading the lead.
27. **Giving up the cores cost nothing.** All eight persistence links in
    every seed; fit gap over independent signals 2.56–2.72 nats a week
    (replay 13: 2.57–2.72); forecast from last week −3.43 to −3.46
    (replay 13: −3.44 to −3.47); calibration level by level 0.035–0.037
    (replay 13: 0.034–0.038). Seed 1, which ran no trial, is identical to
    replay 13's seed 1.

Tested on purpose, the links between signals that replays 12 and 13
reported as worldviews did no work that persistence did not already do.
This is the finding of replays 1–10 again, now reached by an engine that
formed its own hypotheses and then tried to refute them: at weekly levels,
macro's evidence supports that each signal persists, and nothing more.

**Correction to replays 11–13.** Their link lists included links Level 2
had switched off. Replay 14's seed 1 ran exactly as replay 13's seed 1
did, and its leader's one link between signals (last week's inflation on
credit stress) was off in every week after mid-2009, so replay 13's claim
that it was held to 2026 was wrong for that seed. The other seeds' later
years cannot be checked from the stored rows; their fit, forecast and
calibration, which the engine computed from the links in use, stand.

## Replay 15: art, from 2001

*Plan, written before replay 15 ran. Nothing in it has been run on the art
data; the design was settled against the synthetic tests.*

The first replay of a domain other than macro, and of the humanities one.
Art formed no links in 92 live records because its evidence could show
none (docs/art-evidence-plan.md §1). REFACTOR_SPEC D28 replaced it with
thirteen measured signals for Bourdieu's three consecrating bodies: eight
monthly talk signals (the share of a paper's art articles carrying one of
its editors' four most-used topic tags, each month against the two years
before, the Guardian and the NYT kept apart), four yearly Art Basel & UBS
figures (each April), and museum acquisitions (each December). The
question is whether this evidence can show links, and which.

**Data.** Monthly records built by the art domain's own pipeline
(`ArtPipeline`) from saved inputs in `evals/data/art/`, not refetched:
- the press: each month's art articles and the eight tags' counts,
  counted by the clients' rules (the NYT from 2000, the Guardian from
  2010), from the tag probe of 2026-10-26;
- the figures: `report_figures.csv`, as live;
- museums: Chicago's distinct artists by fiscal year and Cleveland's by
  accession year, fetched 2026-10-26. These are today's catalogues, not
  what was published each December; recent years fill in late, which the
  pipeline's 12–18 month delay allows for.

One record per month-end from January 2001 (the NYT's first month with a
year of history) to September 2026: 309 months. The Guardian's signals
start in January 2011, the figures in April 2019, and museums each
December once a museum has four earlier years to compare with. Seeds 0–4, a fresh
engine each, as the app runs it, written to `data/replay15/`.

**Events**, fixed here, with the month each began:

| Event | Began | Source |
|---|---|---|
| Lehman Brothers fails | 2008-09 | |
| Salvator Mundi sells for $450m, an auction record | 2017-11 | Christie's |
| Museums close for COVID (the Met, MoMA, Tate) | 2020-03 | the museums |
| A digital work (Beeple, NFT) sells for $69m | 2021-03 | Christie's |

28. **Does it form links, and of what kind?** Per seed, the links the
    leader reasons with for 12 months or more: within one paper's talk,
    between the two papers, and between talk and the yearly signals. A
    signal's persistence counts apart.
29. **Do they explain the months better than no links?** Fit gap over
    independent signals, nats a month, overall and by year; forecast and
    calibration as in replay 14.
30. **Do changes of programme come with the events?** Changes of
    programme per seed, and how many fall within 6 months after an event.
31. **Does the editors' bookkeeping show as a finding?** The NYT's tags
    per art article doubled from 2019 to 2020 (art plan §12). A link among
    NYT signals that forms in 2020–2022 and goes once those months leave
    the two-year comparison is the tagging change, not the art world.

What would count against the design: links that come and go month to
month; a structure that predicts no better than independence; or links
that exist only while the NYT's tagging change is inside the comparison
window. Expected (art plan §8): some links within talk, if any, and none
involving the yearly signals, which have seven Aprils.

### Replay 15 results

28. **No lasting link between signals.** The leader held a link between
    two signals in 15–40 of 309 months per seed, never for 12 months in a
    row except once: seed 4's museum acquisitions bearing on NYT sculpture
    talk, February 2015 to February 2016. Museums are observed only in
    December, so that link was judged on one or two Decembers; it is
    chance, not a finding. Rival programmes were founded (up to eight alive
    at once), and every seed's most successful one was the same, last
    month's NYT auctions talk bearing on its museums talk, which led for
    11 months and lost. Persistence: only Guardian painting talk (every
    seed) and Guardian photography talk (seeds 2–4) held their own last
    month for a year or more.
29. **The structure predicts no better than no links.** Fit gap over
    independent signals −0.006 to +0.006 nats a month; no year beyond
    ±0.2. Calibration level by level 0.038–0.041, close to macro's.
30. **Changes of programme do not come with the events.** 14–23 changes
    per seed, none within 6 months after any of the four events. Most fall
    in 2012–2013, as the Guardian's signals entered with their first two
    years of comparison; the rest are short-lived conjectures refuted
    within months.
31. **The NYT's tagging change does not show.** No link among NYT signals
    formed in 2020–2022.

So, measured as POE measures, art's talk in the press, month by month,
shows no relation the engine can hold: not within a paper, not between
London's press and New York's, not between talk and the market or the
museums. The design did not fail the way the old one did (every signal
"yes"); the evidence varied and the engine tried rivals and refuted them.
What month-to-month levels of tag shares can carry for art is each topic's
own persistence, and at most that. Whether discourse moves on a slower
time than a month, or is better read than counted (the abductive engine's
art phase), are open, and neither is tested here.

## Replay 16: art talk on a slower clock

*Plan, written before replay 16 ran.*

Replay 15 read talk month by month and found nothing to hold. Taste may
move over seasons and years, not months. Replay 16 asks the same questions
of the same saved inputs aggregated:
- **by quarter:** each quarter's share against the eight quarters before
  (two years, as monthly), 2001 Q1 to 2026 Q3, about 103 records;
- **by year:** each year's share against the five years before, 2005 to
  2025, 21 records.

Figures and museums as in replay 15, each in the quarter or year it is
seen. Seeds 0–4, otherwise as replay 15.

32. **Do links hold on a slower clock?** Links between signals the leader
    holds for 4 quarters, or 3 years, in a row.
33. **Do they predict better than no links?** Fit gap per record.

Expected: little. 21 yearly records cannot carry a link between
three-level signals at BIC's price (art plan §2), and 103 quarters are a
third of replay 15's months. If replay 16 also finds nothing, the slower
clock is closed as a question for counted talk.
