# Art evidence: a plan

Status: approved 2026-10-26; section 5 revised after the probe (section 12).

## 1. Why art has no links

Since D24 the engine forms every link from evidence. Art has formed none in
92 records, and cannot:

- 9 of its 25 signals have never been observed.
- Signals that are observed are almost always "yes". The reports name trends
  that are happening and say nothing of the rest, and silence is recorded as
  MISSING. MarketUncertainty is yes in 15 of 15 records,
  BlueChipConcentration in 17 of 17.
- The one monthly series, AIImageSaturation, is yes in 58 of 60 months. It
  compares a rising series with its own past, so it reads high whenever the
  series is rising, which since 2022 is always.
- Reports arrive on irregular dates and label 3–5 signals each, so most
  pairs of signals are never seen in the same record.
- The signals are verdicts ("CollectorFlightToSafety"), not measurements.
  A theory is written into the inputs, as it was in the seed worldviews D24
  removed.

A link is learned from a difference: one signal changing when another
does (Mill's method of difference). This evidence shows none.

## 2. What the evidence can carry

The engine learns from many comparable periods. What can be had for art:

| Evidence | Periods | Since |
|---|---|---|
| Art Basel & UBS report figures, yearly | 9 (2016–2024) | 2017 edition |
| Museum acquisitions (Chicago), yearly | about 10 | |
| Newspaper art coverage, monthly | about 300 | about 2000 |
| GDELT news coverage, monthly | about 115 | 2017 |

At BIC's price, a link between two three-level signals judged on 9 records
must explain about 0.5 nats a record (4 extra parameters at ½·ln 9
each), and more if the child already has a parent: far stronger than any relation
found so far in any domain. The yearly figures cannot carry learning for
many years. They are worth recording, but only the monthly evidence can
show links.

## 3. What the domain is about

"Art prestige regime" asks what confers prestige in art, and how that
changes. Bourdieu's account (*The Field of Cultural Production*, 1993;
*The Rules of Art*, 1992) is that prestige is consecration, and three
bodies consecrate:
- critics and the press, who confer recognition;
- institutions, which collect and show;
- the market, which prices.

Each can be observed. The domain asks no more than that: what each body
does, and whether any of them moves with another. The old variables also
carried a particular thesis (AI-made imagery raising a premium on the
handmade, "aura", "authenticity"). It was never the project's question. It came in with
the hand-written inputs, as the seed worldviews did, and it goes with them.

Observation is always selective (Popper's "searchlight"), so the choice
of what to observe must not smuggle in a thesis. Topics are therefore
chosen by a rule, not by us: the papers' own subject tags for their art
coverage (section 5). The engine still starts with no links (D24) and
holds only those the evidence earns.

## 4. Three kinds of evidence, kept apart

The old design mixed these together. Here each is named for what it is.

1. **Observation:** numbers someone measured, such as sales totals and
   acquisitions (yearly).
2. **Discourse:** how much of a newspaper's art coverage is about a topic
   (monthly). For prestige, discourse is not a stand-in: being discussed
   is part of what being consecrated is. Signals are named as talk
   (AuctionsTalk), never as a trend ("AuctionBoom").
3. **Testimony:** what a text asserts, for example "collectors are fleeing
   to safety". It needs reading, not counting, and belongs to the
   abductive engine's art phase, where a language model reads and the
   engine judges (abductive_engine EPISTEMOLOGY §9). POE does not use it.

## 5. Monthly: talk in the art press

Each talk signal is the share of a paper's art-section articles that
mention a topic. A share within the art section, not of all news, so art
topics do not all rise and fall with the volume of art coverage, which
would show links where there are none (NEXT.md problem 6).

**Sources.** The Guardian (Open Platform, `artanddesign` section) and The
New York Times (Archive API, articles with subject "Art"), both from about 2000: around 300
months, against GDELT's 115. Both are free for non-commercial use but need
a key tied to an account (decision 2). The two papers are two voices, kept apart (below). GDELT, which is throttled
and starts in 2017, goes.

**Reading a share as a level.** Each month is compared with the two
years before it: what is news this month, rather than how big the topic
has become. A topic that keeps rising does not then read "high" for ever,
as AIImageSaturation did, and a change in the editors' tagging habits
(section 12) fades out after two years instead of shifting every later
month.

**Discourse is not a sample.** A share is not a noisy reading of some
hidden rate of interest: the articles a paper ran about sculpture this
month are the press talking about sculpture, which is what the signal
claims to be. So a topic is not dropped because its month-to-month
movement is small next to sampling chance, nor because the two papers
disagree. The Guardian and the NYT are two voices, London's art press and
New York's, kept apart as two signals each and never averaged. What is
kept from source criticism: the papers' own changes of bookkeeping are
not discourse (Guardian tags are used from 2010; NYT renamed subjects in
2009–10).

**Which topics.** Not chosen by us: the papers' own subject tags on their
art coverage (the Guardian's keyword tags within `artanddesign`, the NYT's
subject keywords on articles tagged Art). The rule:
- Rank the tags by how many art articles carry them over the usable
  period (Guardian 2010–, NYT 2000–).
- Leave out tags that are not topics within art: the section's own tags
  (Guardian tags of the form `x/x`, and its generic `artanddesign/art`;
  the NYT's "culture (arts)" and "culture"), article formats ("reviews",
  "deaths (obituaries)", "content type: personal profile",
  "biographical information", "correction stories"), and tags naming
  another of the paper's sections (music, theater, books and literature,
  movies, dancing, travel and vacations, fashion and apparel).
- Take the top four per paper, so that each voice has the same weight.

The result, from the probe (section 12):

| Signal | Paper | Tag | Art articles carrying it |
|---|---|---|---|
| GuardianPhotographyTalk | Guardian | artanddesign/photography | 28% |
| GuardianExhibitionTalk | Guardian | artanddesign/exhibition | 20% |
| GuardianPaintingTalk | Guardian | artanddesign/painting | 20% |
| GuardianArchitectureTalk | Guardian | artanddesign/architecture | 12% |
| NYTMuseumsTalk | NYT | museums | 18% |
| NYTPhotographyTalk | NYT | photography | 6% |
| NYTSculptureTalk | NYT | sculpture | 5% |
| NYTAuctionsTalk | NYT | auctions | 4% |

A paper's tags are its editors' categories, applied the same way to every
article, so a topic is in because the press keeps writing about it, not
because a theory needs it.

Free-text queries (as AIImageSaturation is now) are not used: a query's
words are ours, and B23 found an "AI" query matching "painting".

## 6. Yearly: report figures and acquisitions

From the Art Basel & UBS reports, using the figures that nearly every
edition gives in the same way (inventory of the 2017–2025 editions,
page-referenced):

| Signal | Figure | Notes |
|---|---|---|
| ArtSalesGrowth | global sales, change on the year | all 9 editions |
| HighEndShare | share of fine-art auction value from works over $10m | auction data source changed 2017–19; "fine art" widened in 2024 |
| OnlineShare | online share of all art sales | real jump in 2020 |
| DealerShare | dealers' share of sales, against auctions | all 9 |

- **Which figure for a year.** Each year's figure comes from the edition
  that first printed it, as macro uses first-published data (B10). Later
  editions revise totals by 1–3% and shares by a few points.
- **When it is seen.** Editions appear in March or early April (2023 on 4
  April, 2025 on 8 April), so each is observed in its year's April record,
  never earlier.
- **The file.** `art_prestige_regime_v1/report_figures.csv`: 36 figures
  from the 2017–2025 editions, each checked against its page (`pdf_page`
  counts PDF pages, not printed page numbers). The 2016 online share is
  printed as "almost 9%" and recorded as 9.
- **Last year's value.** It is the previous edition's first-printed figure,
  by the same rule, and was public a year earlier (section 7).
- **Signals left out:**
  - Shares that barely move: post-war and contemporary art's share stays
    at 46–55%.
  - Figures whose definition changed: art-fair share, and dealer sales by
    dealer size.
  - Figures in under 8 editions: the primary-market share, and women
    artists' share.
- **Museums:**
  - MuseumAcquisitionMomentum stays, with Cleveland added to Chicago
    (B23).
  - CraftPrestigeRising goes: craft was singled out by the thesis that
    section 3 drops.
- **The PDFs:**
  - They stay out of git for copyright reasons, in
    `~/Documents/art-market-reports/`.
  - Only the figures are committed, each with its edition and page.

## 7. Last year's value (decided)

A yearly signal is MISSING eleven months in twelve, so last month's value
is almost always MISSING, and the engine could never learn that a yearly
signal persists. Instead, the source gives last year's value itself: the
previous edition's figure, or the previous fiscal year's acquisitions. The
engine's one change is to keep a last-period value
that a record observed itself, rather than overwrite it with the previous
record's (`model/temporal.py`). A test shows no other domain changes,
because no other source supplies one.

## 8. What to expect

- **Within talk** (about 300 months): links are possible, but only strong
  ones (problem 8).
- **Within the yearly signals:** persistence at best, for years.
- **Between talk and the market:** a link is judged only on the records
  where both are seen, about 9. Whether the press leads the market will not
  be answered for years. The plan does not pretend otherwise.

A replay that finds nothing would still be a result. The aim is evidence
that could show a link, not a promise that it will.

## 9. What goes

- The 24 hand-named signals other than museum acquisitions. Their names sit in the
  dashboard's art copy, which changes with them.
- Learning from the hand-labelled report files (kept in git history). The
  reports return as figures (section 6).
- GDELT, for art.

## 10. Build order

Each step is test first, with passing tests before the next.

0. **Keys.** You register free Guardian and NYT developer keys and put
   them in `.env` and on Railway.
1. **Probe the talk signals.** For each topic, check whether it varies,
   the 15% level rule, whether the two papers agree, and a sample of
   matched headlines read for what the matches are about (B23 found an
   "AI" query matching "painting"). Report back before going on.
2. **Figures:** one committed file with signal, year, value, edition and
   page, each checked against its page.
3. **The lag rule** (section 7).
4. **The domain:** new signals as levels; newspaper and museum sources;
   figures from the file; dashboard copy.
5. **Replay** from 2000, planned in evals/README.md first, then a live
   rebuild.

## 11. Decisions for you

1. The framing: three bodies that consecrate, kept apart from testimony,
   which goes to the abductive engine.
2. Registering the two free API keys. Account sign-ups are yours to do.
3. Accepting that the yearly figures will mostly be recorded, not learned
   from, for some years.

## 12. Step 1 findings (2026-10-26)

Counts only, per month: art articles and how many carry each tag (Guardian
`artanddesign` keyword tags; NYT articles with subject "Art" and their other
subjects), January 2000 to September 2026. No headlines were kept.

1. **The 15% level rule filters almost nothing.** Against the last two
   years every tag tested passes; against the whole past most do. It
   cannot be the test of whether a signal is worth having.
2. **Most monthly movement is chance.** A Guardian month has about 110 art
   articles (from about 200 in 2012 to 75 in 2026), so a tag on 5% of them
   is five or six articles, and its level is mostly sampling luck. Measured
   as the variance about the last two years' mean over what chance alone
   gives, most tags are 1.0–2.0 (1 is pure chance; architecture is 1.04 in
   both papers). By quarter the larger tags reach 2–6, so at least half of
   their movement is more than chance.
3. **The two papers do not agree.** On every tag both use (photography,
   sculpture, architecture, design, museums), the quarterly changes
   correlate at -0.04 to 0.03; monthly, -0.12 to 0.21. They are not two
   witnesses of one art world but two presses, London's and New York's,
   each with its own rhythm. Averaging them would blur both.
4. **Tagging habits change.** The Guardian's scheme changed 2008–2010
   (usable from 2010: 67 quarters). The NYT renamed subjects about 2009–10
   ("motion pictures" to "movies", "culture" to "culture (arts)"), and its
   tags per art article doubled from 2019 to 2020 (1.6 to 3.1), which
   raises every NYT share from then on for reasons that are about the
   editors' tagging, not about art.
5. **Market talk is thin in the Guardian** ("art-market": about one
   article a month). The NYT tags auctions (4%) and collectors (3%).
