# Art by artist: a plan

Status: first draft, 2026-10-26, for review. No code until approved.

## 1. Why

Replay 15 read the art press month by month and found no relation the
engine could hold: 309 months is few, and a month's share of coverage is an
aggregate that hides what consecration acts on, which is artists. Art
history and the sociology of art reason from particular careers, not from
rates. This plan makes the case, not the month, the unit of evidence.

Precedent: Fraiberger, Sinatra, Resch, Riedl and Barabási, "Quantifying
reputation and success in art", *Science* 362 (2018), traced the exhibition
histories of about half a million artists and found that where an artist
showed early shaped the rest of the career.

## 2. The question

Bourdieu's three consecrating bodies, critics, institutions and the market,
act on artists (*The Rules of Art*, 1992). Two of them can be observed for
each artist, year by year, free:
- **the press**: whether the Guardian or the NYT wrote about the artist;
- **institutions**: whether the Art Institute of Chicago or the Cleveland
  Museum of Art acquired the artist's work.

The question: **does the press consecrate an artist before the museums do,
after, or not at all, and has that order changed since 2000?** The market
has no free per-artist data (B23), so it stays out; the yearly report
figures stay in the monthly domain.

## 3. The evidence

One record per artist per year. Variables, each with the artist's own
value the year before, supplied by the source (art plan §7):

| Variable | Levels | From |
|---|---|---|
| GuardianAttention | none / one article / several | Guardian `artanddesign` articles carrying the artist's tag |
| NYTAttention | none / one / several | NYT Art articles naming the artist (keyword "persons") |
| ChicagoAcquires | no / yes | AIC works acquired in the fiscal year, by artist |
| ClevelandAcquires | no / yes | CMA works accessioned in the year, by creator |

Three levels for attention are Kant's categories of quality (negation,
limitation, reality), as D25 uses them; the lines are counts, not set from
the data.

**Who is an artist here.** Chosen by rule, not by us: anyone who appears
in at least two of the four sources over the whole period, or twice in
one. Artists appear in each source under its own name; they are matched by
normalised name (accents, order "Kusama, Yayoi" / "Yayoi Kusama"), with
birth year where both sources give it, and a name that matches two people
is dropped. Match rates are reported. Artists dead before 1900 are kept: a
museum acquiring a Rembrandt is consecration too.

**Years.** 2010–2025 with both papers (the Guardian's tags settle in 2010,
art plan §12); 2000–2025 for the NYT and museums alone. Museums' recent
years fill in late, so the last year read is the one the monthly domain
reads in December 2025.

**What is fetched.** Guardian tags with their names (about 200 requests),
NYT persons keywords (321 archive months, about an hour at NYT's limit),
AIC acquisitions with artist by fiscal year, the CMA collection with
creators (about 13 minutes). Counts and names only; no article text.

## 4. The engine

POE as it is (D24–D27): no hypotheses given; it forms links from the
evidence and keeps rivals until refuted. Records are learned year by year,
each year's artists in an order shuffled by the seed. This is an
evaluation first (replay 17, planned in evals/README.md before it runs),
not a live domain. Whether it becomes one is for after the replay.

## 5. What could mislead

- **Fame is a common cause.** A famous artist gets press and acquisitions
  every year, so press and museums would look linked with no order between
  them. The question is about order: whether last year's press bears on
  this year's acquisition *given the artist's own last year*. The replay
  checks the links it finds against a control in which each artist's years
  are shuffled, which keeps fame and destroys order.
- **The two papers and two museums are not the art world.** London and New
  York presses, two American encyclopedic museums. A finding is about
  these four, and says so.
- **Name matching errors** make links weaker, not stronger, if random; the
  dropped and matched counts are reported.

## 6. Build order

Each step test first.

1. **Fetch and match.** The four sources by artist and year; match names;
   report how many artists, matched and dropped. Report back before going
   on.
2. **Records.** Artist-years with supplied last-year values.
3. **Replay 17**, plan first: links found, their direction, fit gap over
   independence, when the leading structure changes, and the shuffled
   control.

## 7. Step 1 findings (2026-10-26, NYT through March 2010 only)

The NYT's daily quota of 500 requests ran out at April 2010; the rest
downloads overnight. Counts so far:

- **Museums, 1995–2025:** Chicago acquired work by 6,205 artists, Cleveland
  by 4,584 named people (131 creators were places, periods or "unknown").
  Both acquired 962 of them.
- **The Guardian** tags only well-known artists: 419 `artanddesign` tags in
  26 years, topics included; 150 match a museum artist.
- **The NYT** names 9,717 people on its Art articles in 2000–2010, 1,098 of
  them also acquired by a museum.
- **Dropped as two people** (birth years 2+ apart): 39 names.
- **The plan's rule** (in two sources, or twice in one) keeps 5,012 names;
  1,126 have both press and a museum acquisition.

What the counts show:
- Matches read correctly on a sample of 40, but common names ("James
  Watson", "Peter Moore") may join two people, and the NYT gives no birth
  year to check.
- **People the NYT names are not all artists:** a sample of NYT-only names
  holds artists (Mark Ryden, Danica Phelps), art historians, a dealer, a
  composer and a senator. Only a museum acquisition shows a name is an
  artist's.

Decision for the user before step 2: who counts.
- **Artists any museum acquired, 1995–2025** (about 9,800 names): certainly
  artists; the question becomes whether press comes before the first
  acquisition, or after. Recommended.
- **Anyone named twice** (about 5,000 names): includes artists never
  acquired, and non-artists.
