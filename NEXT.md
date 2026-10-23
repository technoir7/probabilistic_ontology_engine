# Open problems

What the engine still gets wrong or cannot yet say, in rough order of how
much each matters to it as epistemology. Each comes from a replay
([evals/README.md](evals/README.md)) or a known gap; none is a bug in the
sense of the code doing other than it says.

## 1. It is timid

When it says 15% the signal comes true 3% of the time; when it says 84%,
97% (replay 5, unchanged since). It holds its beliefs more weakly than its
evidence warrants. The cause has not been found. Candidates: soft evidence
near 0.5 adding counts that pull every table toward even odds; the
Dirichlet prior; halving in crises. Each can be tested by a replay that
changes one and measures calibration.

## 2. Rivals die young

Every rival programme falls to evidence of 100 to 1 by 2005–08, so for most
of the 23 years the population argues within one worldview. Protection
until refuted (D15) and fair breeding (D16) delayed this but did not stop
it. Open: is that the right verdict on these worldviews, or does the
windowed score judge a programme before it has had evidence enough to
revise itself?

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
