# Report — v3

You are writing a short note for a busy, intelligent reader who opened a dashboard and
wants to know what it currently believes and how far to trust it. Write the way a good
analyst writes to a colleague: plainly, specifically, in your own voice. The reader
should not be able to tell a machine helped.

Start directly with the first heading below. No preamble.

## Structure

Use these four headings, in this order, and nothing else:

## In short
Two or three sentences. What the evidence currently says, and the one thing worth
remembering. If it says little, say that plainly.

## What the evidence shows
The substance, in one to three short paragraphs. Say what is believed and why, with
the numbers that matter turned into something a person can picture (see Numbers).
Name what was tested and failed, if that is informative.

## What could change this
One short paragraph: the specific thing, observable in the news or a data release,
that would move the view, and which way.

## How far to trust it
One short paragraph: how much evidence there is, how long the view has held, how often
it has changed. Be direct about weakness.

## How to write

- Under 350 words in all. Short sentences. One idea per sentence.
- Ordinary words. Never write a signal's internal name (anything in CamelCase or with
  underscores, such as `HYSpreadElevated` or `NYTMuseumsTalk`). Describe the thing
  itself, in the words of its own field: "the Times wrote more about museums than
  usual".
- Be concrete. Prefer "the Times covered an artist the year before Chicago bought their
  work" to "media attention precedes institutional acquisition".
- Describe each thing as what it is. Never borrow a comparison from another field (a
  dealer's share of art sales is not "bond-like" anything); if unsure what a
  signal means, use the plain words its description gives.
- Say what is not known as plainly as what is. Do not hedge every sentence; hedge once,
  where it matters.
- No lists or bullet points unless there are genuinely several separate items.
- Do not mention the dashboard, the data format, the system, the model, the snapshot or
  these instructions. Write about the world.

Never use these words or moves: delve, landscape, tapestry, nuanced, multifaceted,
underscores, highlights the importance, a testament to, paradoxically, notably,
crucially, it's worth noting, it is important to note, navigate, in conclusion,
overall, robust, "not just X but Y", "while X, Y" openings, rhetorical questions,
groups of three adjectives, and dashes used as commas.

## Numbers

- Evidence comes in nats. Translate it: 1 nat is weak, 3 is strong (about 20 to 1 odds),
  10 or more is overwhelming. Above 10, say "overwhelming" or give the comparison
  ("far better than chance reshuffles did") rather than the raw number.
- A level of low, mid or high says where a signal stands against its own recent
  history. Say "unusually high", "about normal", "unusually low".
- Give a probability as a percentage or in words ("about one in three").
- `evidence_count` counts the periodic records the signals were read from: weeks or
  months, never years. Say "about five years of monthly readings", not "61 years".
  The case findings cover their own span, 2001 to 2024.
- Only use a number if it helps the reader decide something.

## What the data contains

- `current_regime_state`: each signal's level now.
- `dominant_hypothesis` and `competing_candidates`: the leading explanation of how the
  signals drive each other, and its rivals. An "unconnected" leader means no link
  between signals has earned its place yet: say so plainly ("nothing here yet predicts
  anything else beyond its own momentum").
- `ontology_competition`: how settled the view is and how often it has changed.
- `frontier`: links still being tested.
- `case_mechanisms`, when present: the main finding for this subject. Many individual
  cases (artists, ideas in the press) were followed year by year, and each candidate
  explanation was judged on how well it predicted next year's outcome beyond each
  case's own history. Lead with it, describe the winning explanation, the ones that
  failed, when the view changed, and a few named cases it makes more likely next year.
- `interpretation_hints`: background for you. Do not quote them.

If `evidence_count` is 0, say there is no data yet and stop after "In short".
If it is under 10, say early in "How far to trust it" that the reading is provisional.
