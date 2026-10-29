# Success report — v1

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
its features pushes (`push` above 0 helps, below 0 hurts; 0.7 roughly doubles the
odds). Two controls: each leading feature dealt out at random among the year's artists
(it should then gain nothing), and a placebo using each artist's features from the year
after (if that predicts as well, the features come with success rather than before
it). Where `control_placebo_is_a_fair_test` is false, next year's features count some
of the very claims or articles that make up next year's success, so the placebo is
bound to win and proves nothing; say so in a sentence and rest the case on the dealt
control and the gain over the artist's own past. `critics_rewarded_this_year` is description only: approvals and disapprovals this
year by trend and by medium, with claims critics made. `other_kinds` gives what
predicts each other kind of success.

## Numbers

1 nat is weak, 3 is strong (about 20 to 1), 10 or more is overwhelming; above 10 say
"overwhelming" or compare with the controls rather than give the raw number. Give
chances as percentages or in words.

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
One short paragraph: which features also lead for the other kinds, and where this kind
pulls apart from them.

## How far to trust it
One short paragraph on the limits: only artists the two museums collected; the
features come from a model reading the press, grouped and named by other models; for
the market, only Artprice's Top 500 by auction turnover in the years it published,
so only the top of the market; painting tags come from the Guardian only.

## How to write

- Up to 900 words. Short sentences. Ordinary words.
- Use only what is in the data. Do not add facts, dates, names, prices or context from
  elsewhere, even if you know them.
- Never write a field name (anything with underscores) or mention the data, the
  system, the model or these instructions. Write about art and the people who judge it.
- No bullet points in the report itself.

Never use these words or moves: delve, landscape, tapestry, nuanced, multifaceted,
underscores, highlights the importance, a testament to, paradoxically, notably,
crucially, it's worth noting, it is important to note, navigate, in conclusion,
overall, robust, "not just X but Y", "while X, Y" openings, rhetorical questions,
groups of three adjectives, and dashes used as commas.
