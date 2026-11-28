# W-12 — What happens to conversation history after access is revoked? (V4)

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-28

Today the last 6 messages go to the model; after a revocation the model can restate an earlier answer
(design-decisions §9 accepted this). The brief's test 10 says history must not bypass filters.
Options: drop assistant turns whose citations are no longer readable; send only user turns; keep as is
and document. Question: which, given the user already saw that text?

## Answers (in progress)

- **Q1 — history after revocation:** option C. Before each question, past assistant answers whose sources the user can no longer read are left out of the model's history; the user's own past questions are always sent; old chats stay visible on screen; old citations are re-checked when opened (as today). Fixes V4 / brief test 10. *(agreed)*
- **Q2 — what is checked:** every passage sent to the model, not only cited ones. Each assistant message stores its sent chunk ids (as `audit_log.retrieved_chunk_ids` already does); it re-enters history only if the user can still read all of them. Answers with no passages sent (greetings, chat, not found) are always kept. Older messages without the list: kept only if they have no citations. *(agreed)*

## Resolution

History is permission-filtered like retrieval: past assistant answers re-enter the model's context only if the user can still read every passage that answer was built from; user questions always pass; screens unchanged. Supersedes the accepted trade-off in design-decisions §9 for model context. Fixes V4; covered by brief security test 10.
