# Open problems

What the engine still gets wrong or cannot yet say, in rough order of how
much each matters to it as epistemology. Each comes from a replay
([evals/README.md](evals/README.md)) or a known gap; none is a bug in the
sense of the code doing other than it says.

## 1. No worldview beats persistence

Since replay 10 the rival programmes get a fair trial and live for years,
but none, given persistence, explains the weeks better than persistence
alone. Is that the verdict on these worldviews, or on weekly yes/no
signals, which may be too coarse to carry how credit or money moves the
rest? Monthly evidence, or degrees (problem 2), would say.

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
