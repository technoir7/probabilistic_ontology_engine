# Live state before the D24 reset (2026-10-24)

What each live domain had learned when it still began from hand-written
worldviews, saved from the public read routes just before every domain was
reset to start with no hypotheses (REFACTOR_SPEC D24). One gzipped JSON per
domain key, each holding the response of:

| Key | Route |
|---|---|
| `status` | `/v1/population/status` |
| `structure` | `/v1/debug/structure`: every candidate, pruned ones included, with its links and scores |
| `shifts` | `/v1/population/shifts`: the full paradigm-shift history |
| `learning` | `/v1/debug/learning` |
| `snapshot` | `/v1/export/narrative-snapshot` |
| `recent_evidence` | `/v1/evidence/recent?limit=100`, the latest 100 records |

Not saved: learned conditional probability tables, and evidence older than
the latest 100 records, which the domains' sources can serve again (macro's
is in `evals/data/fred/` and `alfred.json`).
