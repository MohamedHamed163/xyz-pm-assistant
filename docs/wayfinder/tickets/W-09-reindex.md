# W-09 — How do manual decisions survive re-indexing and new versions? (fixes V3)

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-26

Evidence: a manual fix (`Constraints` planning → risks) reverted to `planning` after re-index; the
upload path re-uses topics only on exact heading match. Questions: stable section identity (normalized
heading + position + content hash?), and the rule "re-index may narrow automatically but never broaden
without review"?

## Answers (in progress)

- **Q1 — keeping manual choices:** match sections by normalised heading (case, numbering, spacing ignored) on both upload and Markdown paths · a CEO/PM manual topic always wins over keywords on re-index and new versions · renamed heading → fresh auto tag + review note "earlier manual choice for X not applied" (no fuzzy matching) · deleted section → its choice is dropped. *(agreed)*
- **Q2 — what a re-index may change:** nothing about access. Re-index = re-chunk + re-embed only; stored section topics and label ceilings are frozen. New keyword rules apply only to new uploads/versions; role-table changes still apply live. Test: topics/access identical before and after re-index (security test 13). *(agreed)*

## Resolution

Re-index never changes access (topics and label limits frozen; only chunks/embeddings rebuilt). New versions reuse topics by normalised heading, and a CEO/PM manual choice always beats keywords. A renamed heading gets an auto tag plus a review note. Fixes V3; covered by security test 13.
