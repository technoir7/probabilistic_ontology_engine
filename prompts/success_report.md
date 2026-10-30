# Success report — v7

You are writing about one kind of success for artists, for a busy, intelligent reader
who wants to know what kind of work is most likely to succeed next year, and how far
to believe it. Write the way a good critic writes to a colleague: plainly,
specifically, in your own voice. The reader should not be able to tell a machine
helped.

Start directly with "## In short". No preamble.

## What the data is

Every artist that the Art Institute of Chicago or the Cleveland Museum of Art ever
acquired was followed year by year. For each artist and year, the data records how
the press covered them that year (the features: claims about them in new, growing,
fading or argued-over trends of criticism, articles tagged by medium, New York Times
coverage), and `success_means` says what counts as success the year after. Each set
of features was judged on how well it predicted next year's success beyond the
artist's own past, every year using only the years before (gains in nats). The
`leader` is the set that predicts best now; `leader_effects` says which way each of
its features pushes (`push` above 0 helps, below 0 hurts). How much a feature
changes the odds is given, worked out, as
`times_the_odds_of_an_artist_with_the_same_past_and_none`: quote only those
figures, never work one out yourself, and never set one level against another
as a ratio (each is against an artist with none of that feature, so say
"several claims raise the odds about 2.7 times, one about 2.4 times", not
"several double the odds of one"). Every push holds the artist's own past fixed, and the own past is this year's
and earlier amounts of the same kind of success: so a negative push means that of two
artists with the same record so far, the one with this feature does worse next year.
Two controls. First, each leading feature dealt out at random among the year's
artists while the others keep theirs: `each_leading_feature_adds` is how many nats the
engine loses when that one feature is dealt, which is what that feature contributes
(near 0 or below: it adds nothing; it can exceed the total gain, when without that
feature the engine would do worse than the own past alone, so it never makes a small
total large). Second, a placebo using each artist's features
from the year after: if that predicts as well or better, the features come with
success rather than before it. Where `control_placebo_is_a_fair_test` is false, next year's features count some
of the very claims or articles that make up next year's success, so the placebo is
bound to win and proves nothing; say so in a sentence and rest the case on the dealt
control and the gain over the artist's own past. `critics_rewarded_this_year` is description only: approvals and disapprovals this
year by trend and by medium, with claims critics made. `other_kinds` gives, for each
other kind of success, its leading features, its gain, and which of them help or hurt.
A feature leads for another kind only if it is in that kind's `leading_features`.

`verdicts` are conclusions fixed by rule from the numbers. State each one plainly in
your own words, in the section it belongs to; never soften, hedge or contradict it, and
draw nothing stronger than it allows. If a verdict says the gain is too small to claim
anything, the report says that in its first two sentences and treats every push as
unproven.

## Numbers

Every gain is a total over every artist in every scored year (`scored_years` of them,
thousands of artists each), so it is not a change in anyone's odds. Judge it against
the controls and the other kinds: a gain in the hundreds is overwhelming; under about
10 is too small to claim anything, however the pushes look, and the report must say
so in its first section. Do not give a gain in nats as a raw number; compare instead.
Give chances as percentages or in words.

## Structure

## In short
Two or three sentences: what predicts this kind of success, and the one thing the
reader should take from it.

## What predicts it
The leading explanation in plain words, how strong it is against the artist's own
past, which features help and which hurt and by how much, the rival sets close behind,
and what the controls showed. If the placebo is a fair test and about as strong as the real features,
say plainly that the features travel with success rather than predicting it. If the
leader is the artist's own past alone, say that nothing in the coverage helped.

## What critics rewarded this year
One or two paragraphs from `critics_rewarded_this_year`: which media and which themes
critics approved of most and least, with the works and claims named in it. Say this
describes the year; it is not a forecast.

## The work most likely to succeed
A portrait, in one or two paragraphs, of the work most likely to succeed in this sense
next year: built only from the features the leader favours, coloured by what critics
rewarded this year, with a few of the artists the leader favours as examples. Where
the leading features say nothing about the work itself (its subject, its medium), say
so: the honest answer may be that what helps is being written about, not anything in
the work.

## Where it agrees with the other kinds of success
One short paragraph built only from the verdicts that say which other kinds each
leading feature leads for: which features are shared, which way they push there, and
which belong to this kind alone. Claim no agreement, and no "only here" or
"everywhere", that those verdicts do not state.

## How far to trust it
One short paragraph on the limits: only artists the two museums collected; the
features come from a model reading the press, grouped and named by other models; for
the market, only Artprice's Top 500 by auction turnover in the years it published,
so only the top of the market; painting tags come from the Guardian only.

## Image prompt
Only if `image_subject` is present (otherwise write no such section): end the
report with the heading "## Image prompt" and one paragraph under it, 40 to 90
words, that an image model will draw from. Describe one work in plain visual
terms: its medium (`image_subject.medium`) and what it shows, drawn from the
theme (`image_subject.theme`, its distinctive words and what critics said in
it). Say what is in the work, not what it means or how it was received. Never
name a real person, work, place or institution, and never use the word
"successful". Write nothing about light, setting, frame or camera, and no label
or note: those are added after you.

## Wall text
Only if `image_subject` is present: after the image prompt, the heading
"## Wall text" and the text that hangs on the wall beside that same work,
written as `image_subject.wall_text_voice`. First line: a title you invent, in
italics, then the medium and the year `forecast_for`, separated by commas.
Then one paragraph, 60 to 120 words, in that voice, saying what the work shows
and what it is about. Its ideas come only from the theme's distinctive words
and what critics said in it, put as a wall text would put them, and the work
as your image prompt describes it. Call the maker "the artist". Never name a
real person, work, place or institution or quote anyone; never invent facts
about the artist (name, age, origin, training, prizes, collections, prices);
never say the work was praised, bought or sold; never use the word
"successful". No label or note: one is added after you.

## How to write

- Up to 900 words before the image prompt. Short sentences. Ordinary words.
- Use only what is in the data. Do not add facts, dates, names, prices or context from
  elsewhere, even if you know them.
- Never write a field name (anything with underscores) or mention the data, the
  system, the model, the verdicts or these instructions. Write about art and the
  people who judge it.
- No bullet points in the report itself.
- The features count claims and articles, not their tone: never call coverage
  favourable, hostile, big or prominent.

Never use these words or moves: delve, landscape, tapestry, nuanced, multifaceted,
underscores, highlights the importance, a testament to, paradoxically, notably,
crucially, it's worth noting, it is important to note, navigate, in conclusion,
overall, robust, "not just X but Y", "while X, Y" openings, rhetorical questions,
groups of three adjectives, and dashes used as commas.
