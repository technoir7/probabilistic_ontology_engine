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

The engine now forms its own hypotheses (D24), so the question has to be
asked again: does anything it forms beat persistence, and does it even
find persistence? That is replay 11, which needs planning in writing
before it runs (evals/README.md).

## 2. Unsure in the middle

Leading with persistence, it says 0.56 where the evidence says 0.65
(calibration error 0.047, replay 10). Each judgement conditions on last
week's values rounded to true or false; conditioning on them as soft
evidence would test whether that is the cause.

## 3. Finer evidence costs too much structure

Five ordered levels per signal made it better calibrated but left it able
to afford 2–3 links (replay 8, reverted). An ordinal table, which prices a
relationship by its order rather than by every cell, would cost a few
parameters per cause instead of 20. Code for the levels: commit 1290d1c6.

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

## Outside the epistemology

Two write routes are open to anyone: `POST /v1/ingest/trigger` and
`POST /v1/report/{domain}/refresh`, which the public dashboard calls.
Acceptable for a demo; a real deployment would need the admin token or a
rate limit on both (see the README's API section).
