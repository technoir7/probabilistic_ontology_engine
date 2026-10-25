# The epistemology of the Probabilistic Ontology Engine

This is the philosophical account of how the engine holds beliefs, revises
them, and gives them up: what each mechanism is for, which position in the
philosophy of knowledge and science it takes, and where it falls short.

Related documents:
- [SPEC.md](SPEC.md) is the architecture.
- [REFACTOR_SPEC.md](REFACTOR_SPEC.md) §8 records each design decision
  (D1–D24), several of which were made for the reasons given here.
- [evals/README.md](evals/README.md) reports the replays that tested them.
- [NEXT.md](NEXT.md) lists what remains open.

References to the *Critique of Pure Reason* use the standard A (1781) and B
(1787) pagination; other works are cited by section. Quotations are kept
short, and the rest is paraphrase.

## 1. What the engine is

The engine is a working argument about how beliefs should be held, revised
and given up, written as software. It forms rival explanations of a domain
from the evidence: for macro, how inflation, the yield curve, liquidity,
credit, volatility, the dollar, unemployment and tech momentum bear on one
another. It weighs each against the evidence, week by week, and changes its
mind when the evidence requires it.

It is not a forecaster and is not tuned to be one. Where good epistemic
conduct and predictive accuracy pull apart, conduct wins. Its forecasts are
watched only as a check on its honesty: a believer whose stated confidence
does not match how often it is right is not believing well, whatever else
it does.

### Where it stands in the order of cognition

Kant describes a ladder of cognition (*Jäsche Logic*, Introduction VIII,
Ak 9:64–65). It runs from merely having a representation, through
perceiving with consciousness, to being acquainted with a thing, to
cognizing it through concepts, and on to understanding, insight and
comprehension. In the *Critique* he adds that what turns ordinary cognition
into science is systematic unity: knowledge organized into one whole under
an idea (Architectonic, A832/B860). Put plainly:
- percepts are organized into concepts;
- concepts are organized into knowledge;
- knowledge is organized into science.

The engine works on the upper two steps and not the first:
- **From percepts to concepts: not the engine's work.** Each domain turns
  raw observations into signals ("inflation shock", "credit spread
  stress") using rules a person wrote. The engine receives concepts
  already formed.
- **From concepts to knowledge: the engine's work.** It forms its own
  hypotheses about which concepts bear on which (section 2), and learns how
  strongly, and how sure it can be that each relation exists at all
  (levels 1 and 2, section 4).
- **From knowledge to science: the engine's work.** It holds whole
  explanations as rival systems and asks which systematic whole the
  evidence supports (level 3, sections 4 to 8).

That the first step is done by hand is the engine's deepest limitation.
Section 11 returns to it.

## 2. Where hypotheses come from

Where hypotheses come from is the oldest question this engine takes a side
on, and the one on which it has changed its mind.

One tradition holds that there is a logic of discovery: that good hypotheses
can be read off, or reasoned toward, from the data. Peirce's abduction is
its strongest form. The other tradition, Popper's, denies that discovery
has a logic at all. A hypothesis is a *conjecture*, a bold guess from
wherever it comes, and the only rational work is criticism: deducing what
the conjecture forbids and checking whether that happens (*The Logic of
Scientific Discovery*, 1934/1959; *Conjectures and Refutations*, 1963).
Reichenbach's distinction says the same thing in other words: the *context
of discovery* belongs to psychology, and only the *context of
justification* belongs to epistemology (*Experience and Prediction*, 1938).

### Popper's side, and why the engine left it

The engine was first built on Popper's side. A service that would have
proposed relations by screening the data was deleted unused (D3), and
hypotheses entered in two ways: as rival worldviews written by each
domain's author, and as blind variants of whichever survived. For macro the
worldviews were monetary transmission, credit as the leading signal, an AI
productivity boom, a recessionary cascade, a sparse baseline, and
persistence.

Those worldviews were said to be stated in advance. They came before the
engine saw any evidence, but not before history happened. They were written
in 2026 by someone who knew how 2003–2026 turned out; nobody would have
written the AI-boom worldview in 2003. By Popper's own standard, a test
counts only if the conjecture was made before the outcome was known and
could have failed. A hypothesis written with hindsight and then tested on
the history it was written from is not a test of that hypothesis. So on the
hypothesis side the replays carried hindsight, though on the evidence side
they were careful to use only figures as first published (section 3).

The engine now gives no hypotheses at all (D24). It begins with none, and
forms its own from the evidence.

On where hypotheses come from, the engine left Popper. On how they are
held, it has come back to him: even the core of the worldview it leads with
is put to the test in quiet times, not presumed (D27, section 6).

### What it begins with

It does not begin with nothing. Locke held that the mind begins as a blank
sheet, and that every idea comes from sensation or from reflection on it
(*Essay Concerning Human Understanding*, II.i.2). Kant answered that
although all cognition begins with experience, it does not all arise from
experience (B1): the mind brings forms of its own, and experience supplies
their content. The engine is built on Kant's answer. It begins with:
- **Concepts.** Each domain's signals, defined by a person. This is the
  limit set out in section 1: the step from percepts to concepts is not
  the engine's.
- **The form of time.** Every signal comes with a companion holding its
  value one period earlier, which may ground a judgment about now and is
  never itself judged: nothing points into the past. For Kant, time is the
  form of all appearances, given before any of them (A34/B50). Every
  domain whose evidence arrives in time has this form; only the synthetic
  test domain, whose records are drawn independently, does not.
- **The form of a connection.** What it is for one concept to bear on
  another: a directed dependence, with conditional probabilities for its
  strength and a probability that it exists at all. This is the category
  of relation as a form without content (A80/B106). No particular
  connection is given.
- **Rules of judgment.** How it scores, when it refutes, and how much a
  pattern must explain before chance is ruled out (sections 5 and 6).

It holds one explanation at the start: every concept unconnected. That is
not a hypothesis about the world but the absence of one. It predicts each
signal by how often that signal has occurred, and asserts nothing about how
any of them bear on another. In Kant's terms it is the manifold before
synthesis.

### Synthesis: how a hypothesis is formed

For Kant, knowledge requires that the manifold be combined, and combination
is never given by the senses. It is an act of the understanding (B129–130),
and every combination stands under the unity of one self-consciousness
(B131–132). The engine's act of combination works like this. Each week, for
the best explanation in each research programme, it asks: which connection
that this explanation lacks, or holds the wrong way round, would best have
explained the evidence it remembers? Its memory is the last 100 records, the
span its scores mostly attend to (section 5). It offers the best such
change if what the change explains exceeds what its extra parameters could
fit by chance, by the same penalty that ranks explanations (Schwarz's BIC).

Three features keep this a synthesis and not a search for patterns:
- **It is judged within the whole.** What a connection would explain is
  measured given everything the concept already depends on in that
  explanation. A connection is proposed as part of one structure, never as
  a pattern on its own (section 4).
- **It reproduces what it remembers.** When a connection is formed, the
  engine re-reads the evidence it remembers under the new connection,
  rather than starting that connection's probabilities from nothing. Kant
  held that combining a present representation with past ones requires
  reproducing the past ones (the synthesis of reproduction, A100–102).
  Without it, a correct new connection began by predicting worse than the
  explanation it improved on, and was lost.
- **It is offered, not believed.** Forming a hypothesis is not accepting
  it. Every proposal joins the population as a rival, and only later
  evidence decides it.

Peirce described abduction as reasoning from a surprising fact C to a
hypothesis A such that, were A true, C would be a matter of course (*CP*
5.189). The engine's version is plainer. It does not wait to be surprised;
it asks which connection would have made what it saw least surprising.

### Direction

From nothing, a connection's direction is undecided. "A bears on C" and "C
bears on A" explain exactly the same evidence when nothing else is known
(Verma and Pearl, 1990). So a programme founded on a connection is named
for the pair it connects, written "A–C", not for a direction.

The engine turns a connection round only when the evidence prefers the
other direction. Two cases settle it:
- **Time.** Last period's value can only be a ground of this period's.
- **A meeting of independent grounds.** When two signals are independent of
  each other but each bears on a third, the pattern fixes both arrows into
  the third.

This follows Kant's Second Analogy, which concerns the order of time, not
its lapse: a cause may be simultaneous with its effect, and what fixes
their order is the rule by which one depends on the other (A202–203/
B247–248). The engine claims a direction where a rule in the evidence
orders the two, and otherwise keeps the one it happens to hold, without
claiming it (section 11).

### Why this does not grade its own homework

The reason given for D3 was that a hypothesis suggested by the data, then
judged by the same data, would count the evidence twice. The answer is in
how the engine judges (section 5). A hypothesis is scored only on evidence
that arrives after it is formed. It inherits its parent's score, so the
evidence that prompted it counts equally for the parent and the child; the
two differ only by how they predict from then on. The past suggests; only
the future confirms. Reichenbach's line between discovery and justification
is kept. What has changed is that discovery now has a method, and the
method can be stated and examined.

### Blind variation, in its place

The engine still varies blindly. A blind variant adds or removes one
relation at random. Campbell called this *blind variation and selective
retention* (*Psychological Review*, 1960), and Popper took the same view of
how knowledge grows (*Objective Knowledge*, 1972). It now has two limits:
- **It only revises.** It varies hypotheses the evidence has prompted. A
  random connection of the unconnected would be a hypothesis from nowhere,
  and the engine makes none.
- **The evidence is heard first.** Each programme's best explanation takes
  the change the evidence most prompts, and blind variants fill the places
  left. In the synthetic test, this did better than giving every free place
  to the evidence (19 runs of 20 against 17), and it keeps blind variation
  alive.

### What it costs

Not being told costs something. In the synthetic test domain, whose true
structure is known, the engine was formerly given that structure as one of
its starting hypotheses. Starting from nothing:
- after 300 records it holds all four of the strong dependences in 11 runs
  of 20, and the one the change of regime will overturn in all 20;
- it notices the change of regime, and takes up the new dependence, within
  200 records in 19 runs of 20, against the 16 required (D14);
- it rarely finds the weakest dependence at all. That dependence carries
  about 0.04 nats a record, less than the engine's memory can tell from
  chance. A given hypothesis could include it without having earned it; a
  formed one must earn it.

The engine accepts this cost. A believer told the answer in advance has
learned nothing from finding it again.

These figures are not an independent test of the design, because the design
was settled against them. Three features were added after this test
failed, each for a reason stated above: re-reading what is remembered,
turning connections round, and never varying the unconnected. A fourth,
one evidence-prompted change per programme a week, was chosen because it
did better here. By the engine's own method (section 9), the independent
test is the next replay, on evidence the design has not seen.

## 3. What is given: evidence

### Concepts applied by judgment

Each week, a domain reads its sources and judges, for each of its concepts,
where the world stands under it: how far the yield curve is from inverting,
or how far volatility is above or below its usual level. Kant calls this
*determining judgment*: subsuming a case under a concept already given
(*Critique of the Power of Judgment*, Introduction IV). The rules for it,
such as which line and which window, are written by the domain's author.
The engine inherits them as given.

### Degree, not doubt

A measured signal is a precise number. Volatility this week is 2.3 of its
usual spreads above its median; nobody is unsure of that. What a judgment
near the line is unsure of is not the number but the *word*: whether 2.3
spreads is "elevated". The engine used to treat this as a doubt. It turned
the distance past the line into a probability that the concept applied
(0.73, say) and learned from it as if the world were either elevated or not
and the evidence only blurry about which. That was a category mistake: a
degree passed off as ignorance. It also did harm. Taking each signal's
"probability" apart from every other's, the engine counted two signals that
always moved together, each read at 70%, as disagreeing in 42% of weeks
(0.7 × 0.3 twice). Relations were blurred toward independence, and the
engine held fewer than its evidence supported: on macro's last 100 weeks, 3
links where the same weeks read as levels support 8.

Three views of what such a concept is were weighed (D25):
- **A sharp fact, unseen.** "Credit stress" is on or off, and the readings
  are blurry glimpses of which. This is epistemicism about vagueness: a
  vague word has a sharp cut-off we cannot know (Williamson, *Vagueness*,
  1994). In economics it is the regime-switching view (Hamilton,
  *Econometrica*, 1989). It makes a real claim that can be tested: if the
  regimes are there, the raw numbers should fall into two humps. In macro's
  23 years none does. Every signal lies on one hump or one hump with a long
  tail; the two that looked two-sided did so only because their scale ran
  most weeks off its ends.
- **A matter of degree.** There is only more or less, and the line is drawn
  by us. Locke says this of most of our sorts: their boundaries are "the
  workmanship of the understanding" (*Essay* III.iii.13–14). Kant goes
  further in the Anticipations of Perception: in every appearance the real
  that is sensed has an intensive magnitude, a degree, with a continuum of
  lesser degrees between it and nothing (*Critique of Pure Reason*,
  A166/B207). Peirce made continuity a principle of method (synechism, CP
  6.169).
- **What the engine did:** neither, coherently.

The engine now takes the second view for every measured signal. A signal is
read as one of three levels, observed exactly: low (more than half a unit
below its line), middle (within half a unit) and high (more than half a unit
above), where the unit is the signal's own scale (a z-score, or a unit the
domain sets). Three is not arbitrary. Kant's table gives quality three
moments, reality, negation and *limitation* (A80/B106); a yes/no concept
uses only the first two, and limitation, the real present in some degree,
is what was missing. Half a unit splits a standardised signal into three
roughly equal bands, so each level carries as much as it can. The cut was
fixed in advance on that ground, and it was also the better of the two
tried on macro (8 links at 100 weeks, against 7 at a whole unit); the
choice was not tuned further.

Two costs are conceded:
- **A level is coarser than the number.** 0.6 and 2.9 units above the line
  are both "high". Finer grades would lose less, but each costs evidence.
- **Levels cost evidence.** A relation between two three-level signals has
  four times the free parameters of one between two yes/no signals, so
  BIC's penalty is larger and a weak relation takes longer to earn. Finer
  concepts make the engine believe less, for longer: an old empiricist
  point.

### Testimony is doubt, and is kept as doubt

Not every input is a measurement. Art's reports are read by a language model,
which labels each concept true or false with a confidence that the label is
right. That is testimony, and its confidence is a doubt about a yes/no claim,
so art's concepts stay yes/no and its readings stay probabilities.

Classical conditioning assumes evidence is certain: one learns that E, and
conditions on it. Richard Jeffrey argued that experience often does not make
anything certain; it shifts our probabilities over a partition without
settling any cell of it, and belief should move accordingly (*The Logic of
Decision*, 1965, ch. 11). Testimony is such experience. The engine learns
from it by fractional counts, moving as far as the testimony warrants and no
further. One flaw remains: each label's doubt is counted apart from the
others', which blurs relations between testified concepts as it once blurred
measured ones. The cure is to treat the true value as hidden and each label
as evidence about it (Pearl's virtual evidence), learned by expectation
maximisation (NEXT.md problem 9).

A corollary, learned on macro while its signals were still read as
probabilities, holds for testimony: **a belief should be judged against the
evidence it was given, not against a sharpened version of it.** Judged
against signals rounded to true or false, the engine looked timid. Judged
against the probabilities the evidence actually gave, it was well
calibrated (D21; replay 9). The timidity was in the measure, not the
believer.

### Absence of evidence is not evidence of indifference

When a source fails, or a signal cannot be computed, the engine records the
signal as *missing*. It does not record it as 50/50. A 50/50 entry would be
learned as a real observation, a confident report that the world was
balanced on the threshold, and it would pull every relation toward
independence (D10). Keynes's critique of the principle of indifference
applies: ignorance does not license equal probabilities (*A Treatise on
Probability*, 1921, ch. IV). Not knowing is a state of the believer, not a
fact about the world, and the engine keeps the two apart.

Two further rules follow:
- **A missing value is averaged over, never treated as known.** When a
  relation's cause is unobserved in a given week, the engine averages over
  that cause's values in proportion to how often it has seen each one. It
  does not skip the relation, which would score the effect as certain
  (D23).
- **An outage is not ignorance.** When a source refuses a request, the
  failure is reported and the week is retried. It is not recorded as a
  week in which nothing could be known. An earlier version did record it
  that way, and so took its own outages for ignorance about the economy.

### No hindsight

A believer in 2008 could not know 2009's revisions to 2008's figures. Macro's
history is replayed and learned as first published, from the vintages FRED
archives, each week seeing only what was public by then (replay 7). It made
little difference to what the engine came to believe: inflation read
differently in 37 of 1,229 weeks, and the same programme led. But a result
that might rest on hindsight is not a result. Every change of mind the
engine records is dated by the evidence that caused it, not by when the
engine happened to process it.

### What is conceded

The concepts are someone's choice, and observation is theory-laden (Hanson,
*Patterns of Discovery*, 1958). The engine can only believe what can be
said in its domain's vocabulary. Two consequences are known:
- **The vocabulary may be too coarse.** It may be too coarse to carry how
  credit or money moves the rest (NEXT.md problem 1).
- **Some relations are true by definition.** Some pairs of concepts are
  read from the same source series, so a relation between them is
  analytic, not learned from the world (NEXT.md problem 6).

## 4. Three levels of belief

Belief is held at three levels, each revised by Bayesian updating (SPEC
§3.1).

### Level 1: how strong is a relation?

Given that one concept bears on another, how does it bear: how probable is
each state of the effect, given each state of its causes? This is ordinary
Bayesian learning of conditional probability tables, from counts that start
even and grow with evidence.

### Level 2: does a relation exist at all?

Every relation carries a probability that it exists, raised or lowered by
whether the evidence is better explained with it than without it. Belief
about *structure* is graded, not all or nothing. A relation can be held at
0.5, which is suspended judgment: the engine neither asserts nor denies it.

No relation is denied on too little evidence. A relation cannot be dropped
until its effect has been observed 120 times. Below that, a real relation
can lose to the cost of its own parameters, and a premature denial is
permanent (D14).

### Level 3: which whole explanation?

The engine keeps a population of rival whole explanations (ten by default).
Each is a complete structure: every concept, every relation, every strength.
They are judged as wholes, never relation by relation.

This is holism about confirmation. Duhem argued that a physical hypothesis
cannot be tested alone, only together with the auxiliary assumptions needed
to draw a prediction from it (*The Aim and Structure of Physical Theory*,
1906). Quine generalized the point: our beliefs meet experience as a body,
not one statement at a time ("Two Dogmas of Empiricism", 1951, §6). When a
whole explanation predicts badly, the evidence does not say which part was
wrong. So the engine scores the whole, and lets variants (section 2) find
out which part to change.

### The unity of a structure

At the centre of Kant's *Critique* is the claim that every representation
must be able to belong to one self-consciousness (B131–132). Only by being
combined into that one unity does any of it become knowledge of an object.
The engine's structures are built to an analogous requirement:
- **Each explanation is one connected whole,** scored by the single
  probability it gives to all of a week's evidence.
- **It must answer for every observed concept.** It may not ignore what it
  cannot explain, and an explanation that leaves a concept unconnected
  still has to predict it, and pays for predicting it crudely (D23).

This is an analogy and not a claim that the engine is self-conscious. The
point is structural: belief is a single, connected system, and no part of it
is exempt from the evidence.

## 5. Judging explanations

### Prequential: judge a forecaster by its forecasts

Each week's evidence is scored by each explanation *before* the explanation
learns from it (D8). An explanation is never credited for fitting what it
has already seen. Dawid named this the *prequential* principle: assess a
forecasting system only by the forecasts it actually issued, in sequence
(*JRSS A*, 1984). It is the engine's version of the demand that a theory
be tested against what it did not already know.

Because tables start even and are scored before they learn, a complex
explanation pays for its complexity automatically. It must spend evidence
learning parameters a simpler one does not have, and it predicts badly while
it does.

### Recency: old evidence counts for less

An explanation's score is a window over recent evidence, in which each
record's weight halves every 100 records (about two years of weekly
evidence) (D14). The justification is that the world changes. Evidence
about a world that no longer exists is weaker evidence about this one.
The cost is that an explanation which was right for a decade earns less
from that decade as it recedes. The engine accepts the cost, because a
believer that never discounts the past cannot notice a changed present.

### Simplicity ranks, but refutes nothing

Among explanations that predict about equally well, the engine prefers the
simpler. Its ranking subtracts a penalty for each parameter, the Bayesian
information criterion (Schwarz, *Annals of Statistics*, 1978). That is
Occam's razor in a form Jeffreys defended as a prior commitment of
inductive inference: simpler laws are to be preferred until the evidence
favours a complex one (*Theory of Probability*).

But simplicity only ranks. It never refutes (D22). Whether an explanation is
abandoned is decided by how well it predicted, and nothing else. Replay 10
found what happens otherwise. The prequential score already charges for
complexity, so a refutation that also subtracted the penalty charged it
twice. On that double charge alone, every rival worldview was refuted
within weeks, before the evidence had said anything against it.
Simplicity is a reason to *act* on an explanation. It is not a reason to
*disbelieve* the alternatives.

One concession: the penalty also keeps structures small enough to compute.
Without it, a replay grew structures until it used 11 GB of memory. So the
razor here is partly a principle and partly a necessity.

### Refutation

An explanation is refuted when a rival has outpredicted it, on the weeks
both were scored on, by odds above 100 to 1. This is a Bayes factor in the
range Jeffreys called "decisive" (D15, D22).

This is not Popper's falsification, which is deductive: an observation the
theory forbids refutes it. Probabilistic explanations forbid nothing; any
week is possible under any of them. Popper saw this, and proposed that
probabilistic hypotheses be treated as falsified by a *methodological*
decision once the evidence is improbable enough under them (*Logic of
Scientific Discovery*, §§65–68). The engine's threshold is such a decision,
fixed in advance. The comparison is always with a rival, never with the
data alone. An explanation is given up for a better one, not into a void.

The evidence must be decisive whichever way complexity is counted: on fit
alone, and on fit less complexity (D27). For a more complex rival the
first is the harder test. The scoring already charges it for the
parameters it must learn, and charging BIC as well refuted every rival
within weeks (D22). For a simpler one, such as a trial of the leader's core
(section 6), the second is the harder test: the fit it gave up by being
simpler is not evidence against it.

## 6. Rival research programmes

### Programmes, not theories

Lakatos replaced the single theory with the *research programme*: a hard
core of commitments held fixed, a protective belt of auxiliary hypotheses
revised to meet the evidence, and a heuristic for revising them
("Falsification and the Methodology of Scientific Research Programmes",
1970). A programme is *progressive* while its revisions predict, and
*degenerating* when they only accommodate.

In the engine:
- **Programme:** a connection between two concepts that the evidence
  prompted, from the unconnected start or as a rival to the leader,
  together with every explanation descended from it (section 2). A
  concept's persistence founds no programme (below).
- **Hard core:** that founding connection, between two concepts. A trial
  of the core, which goes without it, holds no worldview (*The core is on
  trial*, below).
- **Protective belt:** the relations its descendants add, remove and turn
  round.

### Rivals live until refuted

Early versions of the engine pruned the worst quarter of the population
each round, and bred new variants from the best. Replayed over 2003–2026,
every rival worldview was extinct within about two years in every run
(replay 1).
Every later "paradigm shift" was one lineage adjusting itself, because no
other was left alive. A believer that lets every alternative die cannot
change its mind; it can only adjust it.

So each programme's best explanation is now spared from pruning until the
evidence refutes it (D15). This is Lakatos's tolerance toward programmes
that have not yet had their chance. It is also something of Feyerabend's
*principle of proliferation*: keep rival theories alive, because a theory's
faults are often visible only from outside it (*Against Method*, 1975).

### A fair trial

A programme kept alive but never allowed to revise itself is not given a
trial. It is merely kept for comparison. Variants were bred from the best
explanations first, so a trailing programme almost never got to try a
revision. Programmes now take turns proposing variants (D16), so each can
adjust its protective belt before it is judged. Lakatos held that "instant
rationality" is a myth: a programme cannot be judged on its first
encounter with difficulty.

### A claim no rival denies is not held against anyone

Every macro worldview, whatever else it claimed, could accept that signals
tend to persist from one week to the next. Before D23, the causal
worldviews lacked that assumption, and were refuted for not knowing it by a
programme that claimed nothing else. That was a verdict on a shared
auxiliary, not on what the worldviews disputed, so D23 gave every causal
programme persistence as an assumption.

Replay 10 asked whether the trial was then fair. It was: the rivals lived
for years and most revised themselves. Those that died were refuted by
evidence, and two survived to the end in some runs. But none led (section
7).

D24 removed that assumption along with every other given hypothesis.
Persistence is now something the engine must find, not something it is
told, and it is the first thing the evidence prompts. But for a while it
also founded programmes: each signal's persistence was a "programme", and
with signals read as levels (D25) those were the first found. They were
the same worldview many times over, converged on one structure, and were
refuted as copies. Replay 12 had one programme alive from 2008 on.

So persistence is common ground again, now found rather than given (D26).
In Kant's terms it is the First Analogy, that in all change something
persists (A182/B224): not one account of change among others, but the
condition of experiencing change at all. It founds no programme. What
programmes dispute is the Second Analogy: the rules by which one thing
follows from another (A189/B232). A programme's hard core is always a
connection between two different concepts.

### A rival can always be founded

A believer that can no longer form a rival cannot change its mind, however
fairly it treats the rivals it has. Programmes used to be founded only from
the unconnected start, and the start is refuted as soon as anything is
found; after that, no new worldview could arise.

Kuhn describes how a rival paradigm arises: from anomaly, what the reigning
one fails to account for (*Structure*, ch. 6–8). The engine now founds a
rival the same way (D26). Whenever the recent evidence supports, beyond
what chance could fit, a connection between two concepts that the leader
lacks, it founds a programme on it: the leader's own structure without its
hard core, with the new connection in its place. The rival shares the
leader's auxiliaries, which D23 holds no rival should be judged on; it
denies the leader's core and asserts its own. The trial is then of the
core itself. If the leader's core does real work, the rival falls behind
and is refuted. If it does not, the rival leads, and that is a change of
worldview, not of belt.

A trial must also be fair at its start. A rival given its parent's past, as
other descendants are, would inherit the leader's lead over it and be
refuted at birth. So a rival begins level with the leader: the same record
of the past, judged only on what comes after. Where it is the simpler of
the two, its fit is lowered by the difference, so it ties rather than
leading before it has predicted anything; on a tie the incumbent keeps the
lead.

Proliferation has a limit. Rivals are founded only while fewer than half
the population's places hold programmes, so each programme keeps room to
revise itself (section 6, *A fair trial*). That limit is a convention, like
the population's size.

### The core is on trial

Lakatos protects the hard core. A programme's *negative heuristic* forbids
aiming the evidence at it and directs refutation onto the protective belt.
Popper exempts nothing. No statement of science is beyond test, a theory is
held only while it survives serious attempts to refute it, and the game
has no end at which a theory is retired from testing (*Logic of
Scientific Discovery*, §§11, 85; *Conjectures and Refutations*, ch. 1).

Under D26 the engine was on Lakatos's side. The core was challenged only
when an anomaly offered a rival, and after 2009 none did: for seventeen
years nothing was aimed at the leader's core (replay 13). A core could be
lost in passing, by a blind variant that dropped it or by the evidence
making the link unlikely enough to switch off (Level 2), but the
explanation kept the programme's name, so a worldview could lose its
defining claim without anything saying so (section 11).

So the engine now aims at the core (D27). While no other worldview is
alive, it founds a trial of the leader's core: the leader's own structure
without the connection that founded its programme, everything else kept,
level with it on score. A trial asserts nothing new. It says only that the
core does no work.
- If the core does work, the leader outpredicts the trial by more than the
  core costs in complexity. Once the evidence is decisive, the trial is
  refuted, and the next is founded. The core is under test every week, not
  merely presumed.
- If it does not, the trial leads and the leader's worldview is given up.
  Without its core the trial holds no worldview. The engine keeps its
  persistence and the auxiliaries, but has no programme until the evidence
  prompts a new one: Kuhn's crisis, with no successor yet.

This is Popper's demand on Lakatos's structure. A programme still keeps its
core against rivals while it has the chance to develop; the trial asks,
only in quiet times, whether the core still earns its place. A trial waits
while any other worldview is alive, another trial among them. The
population is not filled with tests, and a core is not tried while a rival
is already challenging it.

The start must again be fair. A trial is simpler than the leader, so to tie
it, its fit is lowered by the complexity it saves. That lowered fit is not
evidence against it, so it does not count toward refutation (section 5).

## 7. Changing its mind

### Shifts, worldview changes and revisions

Kuhn distinguished *normal science*, puzzle-solving within a paradigm whose
foundations are not in question, from *revolutions*, in which the paradigm
itself is replaced (*The Structure of Scientific Revolutions*, 1962).

The engine records every change of its leading explanation as a paradigm
shift (SPEC §3.1). It also marks which kind of change it is:
- **Worldview change:** the new leader comes from a different programme.
  This is a revolution in Kuhn's sense.
- **Revision:** the new leader is a variant of the same programme, with the
  same commitments and an adjusted belt. This is normal science, however
  often it happens.

### What 23 years taught it

Through 2003–2026, after the trial was made fair, the hand-written
worldviews never displaced persistence: none, given that signals persist,
explained the weeks better than persistence alone (replays 1–10).

This can be put in Kant's terms. The First Analogy of Experience
(A182/B224) is the principle that in all change something persists. The
Second (A189/B232) is that every alteration follows from something else by
a rule. That engine's experience of the economy was organized under the
First Analogy alone: it found that things stay as they were, not the rules
by which they change.

The engine that forms its own hypotheses, reading signals as degrees,
seemed to go further (replays 12 and 13). Every seed found every signal's
persistence and settled on one or two rules beyond it: inflation bearing on
credit stress, the labour trend on tech stocks, tech stocks on the dollar.
Which rule a run settled on depended on the run, so the evidence did not
choose between them.

Put on trial, none survived (replay 14). In four seeds the explanation
without the rule outpredicted the one with it by 2006, and the leader gave
up its worldview; in the fifth the rule had already been judged not to
exist, though the leader kept its name. From 2009 on, every seed held each
signal's persistence and nothing else, and forecast as well as before. So
the result of replays 1–10 stands, now reached the harder way: an engine
that formed its own conjectures and then tried to refute them found, at
the resolution of weekly levels, the First Analogy and no rule of the
Second (NEXT.md problem 1).

### Doubt in a crisis

Kuhn described how a paradigm loses its hold. Anomalies accumulate; when
they resist resolution, the community enters a *crisis*; and in a crisis the
rules of normal science loosen, which is what makes a new paradigm thinkable
(*Structure*, chs. VII–VIII).

The engine has a crisis of its own (D17). It tracks how surprised its leader
usually is by a week's evidence. A week more than two standard deviations
more surprising than usual (once a year of evidence has been seen) is a
crisis. Before learning that week, everything learned so far counts for
half: every table's counts and every explanation's score.

The justification:
- **The usual case.** Confidence earned from evidence presupposes that the
  world the evidence describes still exists. Ordinarily that presupposition
  is warranted, and old evidence keeps its weight.
- **A crisis.** A crisis is itself evidence that the presupposition may
  have failed. A believer should then loosen its certainties, without
  discarding them and without becoming fickle in calm years.

The thresholds were conventional and fixed before the replay that tested
them.

Without doubt, the relations learned over seventeen years outlasted the
world that produced them. Through 2020–21 the engine did worse than if it
had believed nothing was connected. With doubt, every run did better
(replay 4).

## 8. Knowing its own confidence

### Calibration

A believer who says 70% should be right about 70% of the time. Dawid argued
that a coherent Bayesian should expect to be calibrated, and that failing
the test is evidence against its beliefs ("The Well-Calibrated Bayesian",
*JASA*, 1982). The engine checks itself every week (D18). It records what
probability it gave each signal before seeing it, then how often signals
given that probability came true.

It is judged in two ways:
- **Against what the evidence said:** the standard it should meet where its
  evidence is testimony, which is uncertain (section 3).
- **Against what came:** for a measured signal the level is observed
  exactly, so the two judgments are one. A graded signal is judged level by
  level: the probability it gave each of low, middle and high, against
  whether that level came (D25).

Leading with persistence, it is calibrated to within about five points. It
is slightly unsure in the middle, saying 56% where the evidence says 65%
(NEXT.md problem 2).

### Humility: the leader is not the whole of belief

The engine's leading explanation is the one it would act on. But its belief
is the whole population, weighted by how well each member has done. When no
explanation clearly dominates, acting on the leader alone overstates what is
known.

So the engine also measures whether the weighted population predicts each
week better than its leader does (D18). When asked a question, it can answer
from the population as a whole (SPEC §4.4, D6). It also reports how spread
its belief is across rival structures, as the entropy of that weighting.
This is Bayesian model averaging, and it is the formal version of a virtue:
not mistaking the best available account for the truth.

## 9. Method: how the engine itself is tested

The engine's claims about itself are tested the way it tests its
explanations:
- **Planned before run.** Every replay is planned in writing before it runs:
  the data, the events it should notice, the questions it answers, and what
  would count as an answer.
- **Negative results stand.** Results are reported whether or not they
  flatter the engine. Several did not: shifts that never followed events,
  rivals refuted unfairly, timidity that was really in the measure.
- **No tuning to the answer.** Nothing is changed in response to a replay
  to make its answer come out better. A change a replay suggests is made
  only with a stated reason, and measured on the next replay.
- **Reproducible.** Each replay reruns from data committed in the
  repository, with the same seeds and the same result.

This is the same discipline as pre-registration in empirical science, and
for the same reason. A system tuned until its results look right has stopped
being tested.

## 10. What language models may do

A language model writes the plain-English report of each domain's state,
from a snapshot of what the engine believes. It may describe and paraphrase.
It may not change any belief, relation or score, and nothing it writes is
learned from (SPEC §15). The engine's beliefs come only from evidence.

## 11. Limits

These are known, and each is either an open problem (NEXT.md) or a
deliberate cost:

1. **Its concepts are given.** The engine forms its own hypotheses but
   never a concept. Every signal it reasons with was defined by a person,
   so the step from percepts to concepts (section 1) is outside it. The
   vocabulary also carries the hindsight that D24 removed from the
   hypotheses: a signal for tech momentum was chosen by someone who knew
   there would be an AI boom. Whether the vocabulary is the reason no
   worldview beats persistence cannot be answered from inside the engine.
   A companion engine that forms its own concepts from the same
   observations is planned for that question.
2. **Any relation is admissible.** A hypothesis may relate any two
   concepts, in either direction. Domain knowledge that some relations are
   impossible, such as an exogenous series having no causes within its
   domain, is not expressed (NEXT.md problem 4).
3. **Direction is not marked as undetermined.** From observation alone,
   "A bears on B" and "B bears on A" often predict exactly the same
   evidence (Verma and Pearl, 1990). The engine names programmes without
   a direction and turns a connection round only when the evidence orders
   it (section 2). But within an explanation, a connection the evidence
   cannot orient keeps whichever direction it was formed with, and the
   explanation does not say that the evidence could not decide.
4. **The razor is partly practical.** BIC ranks explanations partly because
   structures must stay small enough to compute (section 5).
5. **Testimony is rounded where it should not be.** For art, whose
   readings are testimony, last week's labels are given to this week's
   judgments rounded to true or false, and each label's doubt is counted
   apart from the others' (section 3; NEXT.md problems 2 and 9). Measured
   signals no longer have this flaw: their levels are observed exactly
   (D25).
6. **Finer concepts cost evidence.** A relation is priced by every cell of
   its table. Five levels, still read as probabilities, left room for only
   two or three relations (replay 8, reverted). Three exact levels (D25)
   cost less, a third of five's price per cause, but a relation between
   two different signals is still dear, and most of what the engine can
   afford is each signal's persistence. Tables that price a relation by
   the levels' order would cost a few numbers per cause (NEXT.md problem
   3).
7. **The conventions are conventions.** The 100-to-1 threshold, the
   two-year half-life, the crisis threshold, the halving and the limit on
   rivals (half the population's places) and the trial's wait for quiet
   times are conventional choices, fixed before the replays that tested
   them. They
   are not derived from anything deeper.
8. **A worldview can lose its core and keep its name.** A trial gives up
   the leader's worldview openly. But a core can also be lost in passing,
   by a blind variant that drops it or by Level 2 switching the link off,
   and the explanation keeps its programme's name. Such a leader is
   reported as holding a worldview it no longer reasons with, and since it
   has no core, none is put on trial (NEXT.md problem 10).
9. **Weak dependences go unfound.** A hypothesis is formed from the last
   100 records and must explain more than chance could. A real dependence
   weaker than about 0.04 nats a record is rarely formed, and if formed,
   rarely outscores its parent within the score's memory (section 2). A
   longer memory would find it and notice change more slowly (D14).

## Glossary

| Term | Meaning here |
|---|---|
| Concept (signal) | a domain's variable, such as "inflation shock", defined by its author |
| Level | how far a measured signal lies from the line that names its concept: low, middle or high, observed exactly (D25) |
| Soft evidence | testimony about a concept (art's reports), recorded as the probability that it applies |
| Relation (edge) | a dependence of one concept on another, with a probability that it exists |
| Explanation (candidate) | one whole structure: concepts, relations and strengths |
| Programme (lineage) | a connection between two concepts that the evidence prompted, from the unconnected start or as a rival to the leader, named for its pair ("A–C"), and every explanation descended from it |
| Trial | the leader without its programme's core, level with it, founded when no other worldview is alive (D27) |
| Synthesis | forming a hypothesis: the connection the remembered evidence most prompts, offered when it explains more than chance |
| Leader | the explanation ranked best on recent evidence |
| Paradigm shift | any change of leader |
| Worldview change / revision | a shift between programmes / within one |
| Refutation | a rival outpredicting an explanation by odds above 100 to 1, on fit and on fit less complexity both |
| Crisis | a week far more surprising to the leader than usual; what was learned then counts for half |
| Nat | the unit of surprise: one nat less surprise means about 2.7 times more probability given to what happened |

## References

- Campbell, D. T. "Blind variation and selective retention in creative
  thought as in other knowledge processes." *Psychological Review* 67
  (1960).
- Dawid, A. P. "The well-calibrated Bayesian." *Journal of the American
  Statistical Association* 77 (1982).
- Dawid, A. P. "Statistical theory: the prequential approach." *Journal of
  the Royal Statistical Society A* 147 (1984).
- Duhem, P. *The Aim and Structure of Physical Theory* (1906).
- Feyerabend, P. *Against Method*. London, 1975.
- Hamilton, J. D. "A new approach to the economic analysis of nonstationary
  time series and the business cycle." *Econometrica* 57 (1989).
- Hanson, N. R. *Patterns of Discovery*. Cambridge, 1958.
- Jeffrey, R. C. *The Logic of Decision*. New York, 1965, ch. 11.
- Jeffreys, H. *Theory of Probability*. Oxford, 1939; 3rd ed. 1961.
- Kant, I. *Critique of Pure Reason* (A 1781, B 1787); *Critique of the Power
  of Judgment* (1790), Introduction IV; *Jäsche Logic* (1800), Introduction
  VIII.
- Keynes, J. M. *A Treatise on Probability*. London, 1921, ch. IV.
- Kuhn, T. S. *The Structure of Scientific Revolutions*. Chicago, 1962.
- Lakatos, I. "Falsification and the Methodology of Scientific Research
  Programmes." In Lakatos and Musgrave (eds.), *Criticism and the Growth of
  Knowledge*. Cambridge, 1970.
- Locke, J. *An Essay Concerning Human Understanding*. London, 1690,
  II.i.2, III.iii.13–14.
- Peirce, C. S. *Collected Papers*, ed. Hartshorne and Weiss. Cambridge,
  Mass., 1931–35, 5.189, 6.169.
- Pearl, J. *Probabilistic Reasoning in Intelligent Systems*. San Mateo,
  1988.
- Popper, K. R. *The Logic of Scientific Discovery* (1934; English 1959),
  §§11, 65–68, 85; *Conjectures and Refutations* (1963); *Objective Knowledge*
  (1972).
- Quine, W. V. O. "Two Dogmas of Empiricism." *Philosophical Review* 60
  (1951).
- Reichenbach, H. *Experience and Prediction*. Chicago, 1938.
- Schwarz, G. "Estimating the dimension of a model." *Annals of Statistics*
  6 (1978).
- Verma, T. and Pearl, J. "Equivalence and synthesis of causal models."
  *Proceedings of UAI*, 1990.
- Williamson, T. *Vagueness*. London, 1994.
