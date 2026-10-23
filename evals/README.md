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
