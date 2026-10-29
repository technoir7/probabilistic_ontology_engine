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

## When the data has `trends`

Then the subject is what critics write about, and the report leads with it. Use these
five headings instead, in this order:

## In short
Two or three sentences: the few ideas that most mark this year in criticism, and the
one forecasting finding worth remembering.

## What critics are arguing about
The heart of the report. Take five or six trends that together say most about the year:
something new, something growing, something fading, and the most divided. Give each its
own short paragraph of three to five sentences, opening with the trend's name in bold.
Say what the trend is about, using `what_critics_said` to name the actual works, shows,
places or disputes and what critics claimed about them. Say how it moved (its share of
critics this year against the years before) and whether critics agree or are split
(approvals against disapprovals). Say whether one paper or both carry it. Analyse,
do not list: say what the claims have in common and what is at stake.

## What predicts what
One or two short paragraphs. For artists, what the case engine found, and you may name
a few artists it favours. For ideas in the press, what kept a topic alive; never name
individual concepts from the Concepts set, which are too small to mean much to a reader.
Then say plainly that nothing in how critics write about a trend has predicted whether
it grows (the Trends case set), so the trends above are a picture of this year, not a
forecast.

## How far to trust it
One short paragraph, as below, and add that the trends are groups of claims found by
a model reading the press, named by another, so a name can be looser than its claims.

Up to 750 words in all. Everything in "How to write" still holds.

## How to write

- Under 350 words in all, unless the data has `trends`. Short sentences. One idea per sentence.
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
  Each case finding covers its own span (from its first year scored).
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
  case's own history. Lead with it (after the trends, when there are trends), describe the winning explanation, the ones that
  failed, when the view changed, and a few named cases it makes more likely next year.
- `trends`, when present: the broad ideas critics wrote about in the year given (new
  ones, growing, fading, and the most argued over, where critics split between
  approval and disapproval), each with its share of critics by year, its verdicts, the
  words that set it apart and some of this year's claims in `what_critics_said`. Use
  the layout in "When the data has `trends`". They describe the present: never present
  them as forecasts.
- `interpretation_hints`: background for you. Do not quote them.

If `evidence_count` is 0, say there is no data yet and stop after "In short".
If it is under 10, say early in "How far to trust it" that the reading is provisional.
