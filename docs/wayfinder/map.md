# Wayfinder map — Permission-aware RAG improvements (Nexora brief)

Tracker: local Markdown (no issue tracker configured). Each ticket is a file in `tickets/`.
Rules: tickets are **questions**; one ticket per session; no production code until the map clears;
then `/to-spec` → `/to-tickets` → implement.

## Destination

A **reviewed spec** for the improved pipeline — document metadata extraction with schema validation
and ambiguity/conflict flagging, a policy model that combines trusted backend data with document
labels, section-level restrictions, improved chunking, permission-aware retrieval, the 14 security
tests and a retrieval-quality evaluation — that closes vulnerabilities **V1–V4** from the audit and is
measured against a baseline. Ready to hand to `/to-spec`.

Evidence: [01-architecture-audit.md](../audit/01-architecture-audit.md) ·
[02-evaluation.md](../audit/02-evaluation.md)

## Decisions so far

Carried over from earlier design reviews (still binding unless a ticket re-opens them):

- Permissions are enforced by the backend **before** retrieval results reach the LLM; RLS re-checks
  every row. The LLM never decides access. *(design-decisions §2, §12)*
- Unknown/unmatched content is **fail-closed** (CEO/PM only) and never widened by a guess. *(§12.8)*
- Document labels are **proposed policy, not truth**; the LLM may extract or suggest policy but can't
  grant access. *(Nexora README + brief)*
- Refusals: forbidden topic in own project → rule explained; other project → neutral sentence. *(§12.4)*
- ~~Commercial readable by CEO, PM, Finance, Client (§12)~~ — superseded by W-05.

New decisions (one line each, as tickets close):

- **W-02** *(simplified)* Labels only narrow, automatically — never widen; no approval queue. Effective access = role table ∩ membership ∩ label; unmapped label text → review note; named users ignored; manual narrowing persists. → [W-02](tickets/W-02-trust-model.md)
- **W-05** `commercial` splits into **Pricing** (CEO, PM, Finance, Client) and **Internal finance** (CEO, Finance); moved lines may only go to a topic with a subset of the source's readers, else stay flagged; internal/unsure → Internal finance; existing sections migrated by narrowing only. → [W-05](tickets/W-05-commercial-split.md)
- **W-03** *(simplified)* 6 roles unchanged + **Legal** and **Operations**; roles global; **no groups or personal grants**; labels naming people ignored; clients never get Internal finance/Unclassified. → [W-03](tickets/W-03-principals.md)
- **W-04** Classification always shown; it is a document ceiling only when Authorized Roles is absent (stricter wins if both): Internal = staff, no Client · Confidential = CEO/PM/Dev/QA · Commercial-Confidential = CEO/PM/Finance/Legal; missing → none + note, unknown → strictest + flag; sections narrow only, never wider (W-07: no extracts). → [W-04](tickets/W-04-classification.md)
- **W-07** Simple: no extracts/summaries/share flags; client sees only what role table ∩ document ceiling allows; "approved summary only" docs give the client nothing — PM uploads a separate client document if needed. → [W-07](tickets/W-07-client-sharing.md)
- **W-09** Re-index only rebuilds chunks/embeddings — topics and label limits frozen; new versions reuse topics by normalised heading, manual choice beats keywords, renamed heading → auto tag + review note. Fixes V3. → [W-09](tickets/W-09-reindex.md)
- **W-12** History filtered like retrieval: a past answer goes back to the model only if the user can still read every passage it was built from; questions always pass; screens unchanged. Fixes V4. → [W-12](tickets/W-12-history.md)
- **W-06** PRD "Access Rules"/"Restricted Content"/"Admin-only" = product requirements (topic `requirements`, Dev/QA read them); proposal "Confidential/Internal Notes/Risk" = about the document → Internal finance; no conditional document access. → [W-06](tickets/W-06-product-rules-vs-acl.md)
- **W-13** Project = upload form's choice; document project id/name only checked (mismatch → review note); sample headings added to the one keyword list; proposal "confidential/internal" headings → Internal finance. → [W-13](tickets/W-13-identity-vocabulary.md)
- **W-08** Metadata: deterministic parser is the truth; LLM second reader — ceilings intersected (stricter wins), disagreements → review notes; 0 leaks in 40 runs vs 3 for parser alone; `.md` uploads accepted without front matter. → [W-08](tickets/W-08-metadata-extraction.md)
- **W-01** 62-question dataset + target policy; baseline: Recall@1 0.797, answer accuracy 0.983, but 40.8% of top-8 chunks unauthorized, 72 fact / 28 answer leaks; gates: unauthorized = leaks = 0. → [W-01](tickets/W-01-eval-dataset.md)

## Frontier — open, unblocked, takeable now

| Ticket | Question | Type | Mode |
|--------|----------|------|------|
| [W-11](tickets/W-11-retrieval.md) | Which retrieval changes (hybrid, rerank, rewrite) earn their place on the baseline? | grilling | HITL |
| [W-10](tickets/W-10-chunking.md) | How should chunks carry context, tables and requirement↔acceptance links? | grilling | HITL |

## Blocked

| Ticket | Question | Blocked by |
|--------|----------|-----------|

## Not yet specified (fog)

- How label notes appear on the existing review screen (no separate admin UI) — W-08 defined the notes; screen detail left to the spec.
- Page-number citations for PDFs (parser change; after W-10).
- LLM-suggested topics for unclassified sections (after W-08 shows extraction accuracy).

## Out of scope

- Approved extracts / AI-generated client summaries (W-07), approval queues (W-02), project groups and personal grants (W-03) — kept out for simplicity.
- Fine-tuning or training any model.
- Runtime, state-dependent access in the *described* products (e.g. Hub Drives showing a provider's
  phone after booking confirmation) — confirmed by W-06.
- Multi-company tenancy changes, SSO, deployment.
