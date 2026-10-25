# Open problems

What the engine still gets wrong or cannot yet say, in rough order of how
much each matters to it as epistemology. Each comes from a replay
([evals/README.md](evals/README.md)) or a known gap; none is a bug in the
sense of the code doing other than it says.

## 1. No worldview beats persistence

In replay 10 the hand-written programmes got a fair trial and lived for
years, but none, given persistence, explained the weeks better than
persistence alone. Is that the verdict on these worldviews, or on weekly
yes/no signals, which may be too coarse to carry how credit or money moves
the rest? Monthly evidence, or degrees (problem 2), would say.

The engine now forms its own hypotheses (D24). In replay 11 it found
persistence for most signals and held a few links between signals, but fit
the weeks a little worse than replay 10's persistence; replay 12 asks the
same with levels (D25).

## 2. Unsure in the middle

Leading with persistence, it says 0.56 where the evidence says 0.65
(calibration error 0.047, replay 10). Each judgement conditioned on last
week's values rounded to true or false. Measured signals are now levels
observed exactly (D25), so nothing is rounded for them; art's testimony
still is.

## 3. Finer evidence costs too much structure

Five ordered levels per signal, read as probabilities, made it better
calibrated but left it able to afford 2–3 links (replay 8, reverted).
Measured signals are now three levels observed exactly (D25): a cause costs
6 parameters per three-level child, not 20, and persistence is affordable,
but a relation between two different signals is still dear. An ordinal
table, which prices a relationship by its order rather than by every cell,
would cost a few parameters per cause.

## 4. Any link is admissible

New variants may add an edge between any two signals (except into last
week's values). Domain knowledge that some directions are impossible (an
exogenous series has no parents in its domain) is not expressed. A
per-domain allow-set used by `_derive_admissible_edges` would carry it; it
should be added only with a replay that shows what it changes.

## 5. Only macro's history is as first published

Macro's live history was rebuilt from ALFRED vintages. Every other
domain's history comes from today's figures, revisions included (B10).
Replay 7 found revisions changed macro's beliefs little, so this is a
small distortion, but it is one.

## 6. Some links are true by definition

A few domains read two variables from one series: credit's
LeveragedLoanStress and BankLendingTightening are the same DRTSCILM
z-score at two thresholds, and CorporateDefaultRisk and HYSpreadElevated
both come from the high-yield spread. A link between such a pair is
learned as strong because it cannot be otherwise, and says nothing about
the world. Since D24 this matters more: the engine forms first the
connection the evidence most supports, and a pair that cannot disagree
supports it best. Each variable should come from its own source, or such
pairs should be inadmissible as links (problem 4).

## 7. Some "13-week" signals look back 18 weeks

Macro's NASDAQ momentum and energy's WTI and XLE momentum take the price
91 observations back as 13 weeks ago, but the series are daily trading
prices, so 91 observations is about 18 weeks. Credit's TOTCI had the
opposite fault, three observations of a weekly series read as three
months; it is fixed. Fixing macro's changes what the replays measured, so
it waits for a replay that says what it changes.

## 8. Weak dependences go unfound

A hypothesis is formed from the last 100 records and must explain more
than chance could. In the synthetic test, a real dependence worth about
0.04 nats a record (B–C) was found in none of 20 runs within 300 records,
so the test that the whole true structure is found from nothing is a known
failure (G2, xfail). A longer memory would find it but notice a change of
regime more slowly (D14); forming hypotheses from a longer memory than the
score's is the obvious thing to try, and the replays would have to show it
does not slow the response to change.

## 9. Testimony is counted label by label

Art's reports are testimony: each label is a doubt about a yes/no claim,
and art keeps soft evidence for it (EPISTEMOLOGY section 3). But each
label's doubt is counted apart from the others', which blurs relations
between testified concepts toward independence, as it once blurred
measured ones (on macro, 3 links in 100 weeks where the same weeks as
levels support 8). The cure is to treat each concept's true value as
hidden and each label as evidence about it (Pearl's virtual evidence),
learning the tables by expectation maximisation.

## Outside the epistemology

Two write routes are open to anyone: `POST /v1/ingest/trigger` and
`POST /v1/report/{domain}/refresh`, which the public dashboard calls.
Acceptable for a demo; a real deployment would need the admin token or a
rate limit on both (see the README's API section).
