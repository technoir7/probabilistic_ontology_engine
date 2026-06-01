# Epistemic State Report — Output Format v2

Write the report now. Start with "## BOTTOM LINE" — do not introduce yourself, do not
describe what you are about to do, do not mention the JSON or the system. Begin writing
the report itself immediately.

---

## REQUIRED STRUCTURE

Use exactly these six section headers in this order:

### ## BOTTOM LINE
One to three sentences. What is happening right now in plain English? What should a
decision-maker take away from this reading?

### ## CURRENT BELIEFS
What does the evidence say is true? Name the variables that are most clearly active or
inactive. Translate every variable name on first use — write the plain-English meaning
in parentheses immediately after. Example: "YieldCurveInverted (short-term interest
rates exceed long-term rates, historically a recession signal) is firmly on."

If evidence_count is below 10, open this section with: "Note: this reading is
provisional — fewer than 10 data points have been ingested, so beliefs reflect starting
assumptions more than observed data."

If evidence_count is 0, open with: "No data has been ingested. The following reflects
prior assumptions only, not observed conditions."

### ## WHY
Which causal story (hypothesis) is leading, and by how much? Name the top two
hypotheses in plain English. If the dominant hypothesis is well ahead, say the system
has converged on a single explanation. If the top two are close (within 0.05
normalised score), say there is no clear winner and genuine uncertainty remains about
which story is right. Describe what each leading story claims is happening and why.

### ## WHAT IS UNCERTAIN
Which causal relationships are unresolved? For each frontier edge, say in plain English
what relationship is in question and why resolving it matters. Example: "The link
between rising energy prices and corporate defaults is still unresolved — whether one
is causing the other depends on which new data arrives first." If there are no frontier
edges, write: "The causal structure is settled — no relationships remain in active
question."

### ## WHAT WOULD CHANGE THE VIEW
What type of new data or event would flip the dominant hypothesis? Be specific. Name
the variable, the direction of change, and which alternative story it would favour.
Tie each trigger to a real-world observable — something a reader could look up in a
news feed or a data release.

### ## CONFIDENCE AND LIMITATIONS
State the evidence volume (evidence_count), the recency of the latest signal, and the
number of times the dominant story has changed. A system that has shifted many times is
epistemically volatile — its current view may not hold. A system with few data points
is speculative. Be direct about these limitations without hedging them away.

---

## ABSOLUTE PROHIBITIONS

Never write any of the following:
- "We are asked to..." / "Let's analyze..." / "I will now..." / "In this report..."
- "The JSON shows..." / "According to the snapshot..." / "The system outputs..."
- "The ontology engine..." / "The probabilistic model..." / any meta-reference to the
  system, the prompt, or the task
- Raw variable names without immediate plain-English translations
- "Bayesian", "ontology", "log score", "entropy", "paradigm" — unless each term is
  translated in the same sentence (e.g. "structure entropy, a measure of how spread
  belief is across competing stories")
- Sentences explaining what the next section will cover

---

## VARIABLE TRANSLATION GUIDE

Translate variable names the first time they appear. Use the parenthetical form:
VariableName (plain-English meaning). Examples:

- YieldCurveInverted → (short-term interest rates exceed long-term rates, a historic
  recession warning signal)
- LiquidityStress → (the central bank is shrinking its balance sheet, withdrawing
  money from the financial system)
- InflationShock → (inflation is running meaningfully above the historical average)
- CreditSpreadStress → (corporate borrowing costs are sharply elevated relative to
  government bonds, signalling rising default risk)
- VolatilityShock → (market fear indicators are unusually elevated)
- DollarStrength → (the US dollar is strengthening against other currencies,
  tightening global financial conditions)
- EquityRiskOn → (investors are buying equities and accepting more risk)
- SemiconductorMomentum → (chip stocks are rising; AI hardware demand is strong)
- HyperscalerCapexAccelerating → (Microsoft, Google, Amazon, and Meta are rapidly
  increasing data-centre spending)
- TempAnom → (temperatures are well above or below seasonal norms)
- HeatingDem → (demand for heating fuel is elevated)
- StorageDraw → (fuel is being drawn from storage at an above-normal rate)
- PriceUp → (spot prices are rising)
- BTCMomentumPositive → (Bitcoin prices are trending upward)
- ConflictIntensityElevated → (the volume and severity of armed conflicts is above
  historical norms)
- USYieldSpiking → (US 10-year Treasury yields are rising sharply above normal)
- HYSpreadElevated → (high-yield corporate bond spreads are elevated, signalling
  credit stress)
- UnemploymentRising → (the unemployment rate is trending upward)
- OilPriceSurge → (crude oil prices are rising significantly above recent norms)

For any variable not listed above, derive its plain-English meaning from its name and
provide it in parentheses on first use.

---

## EDGE CASE RULES

- evidence_count = 0: open CURRENT BELIEFS with the zero-data disclaimer above.
- evidence_count < 10: open CURRENT BELIEFS with the provisional disclaimer above.
- Top two hypotheses within 0.05 normalised score: state in WHY that there is no clear
  winner and the engine is genuinely undecided between two stories.
- paradigm_shifts_total = 0: note in CONFIDENCE that the dominant view has never
  changed — the system has consistently held this position since first ingesting data.
- frontier_edge_count = 0: write the settled-structure sentence in WHAT IS UNCERTAIN.

---

Begin with "## BOTTOM LINE" — write the report now.
