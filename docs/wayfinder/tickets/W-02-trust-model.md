# W-02 — How do document-declared permissions combine with the trusted policy store?

**Type:** grilling · **Mode:** HITL · **Blocks:** W-03, W-04, W-06, W-07 · **Status:** closed 2026-11-26

## Context
Documents declare Classification, Authorized Roles, Authorized Users and Sharing Rules. Today these
are ignored; access comes only from `role_topic_access`. The README says labels are proposed policy.
Evaluation §3 shows the two disagree (client and PM read internal cost; Developer reads parts of a
Commercial-Confidential proposal; Developer/QA can't read BRD constraints the document allows).

## Question
When a document's labels and the policy store disagree, which wins, and who decides?

## Options to grill
- **A. Labels ignored** (today) — simplest, but V2 stays open.
- **B. Labels may only narrow, automatically; widening needs admin approval** — fail-safe.
- **C. Labels are suggestions only; an admin approves every document's policy before publish.**
- Effective access = policy store ∩ approved document policy (never ∪).

## Recommended starting point
B: extracted labels can only *remove* access without review; anything that would *add* access, and
any conflict or ambiguity, goes to the existing Review requests queue.

## Resolution (2026-11-26, grilled with the user)

1. **Precedence — option B.** Document labels may only *restrict* automatically. Anything that would
   grant more access, and anything ambiguous, waits for human approval. Effective access =
   trusted rules (`role_topic_access` + project membership) **∩** approved document policy — never ∪.
2. **Which label parts, at what level.**
   - *Authorized Roles* → a **document-level ceiling** (roles not listed read no section). Auto-applied when it narrows.
   - *Sharing Rules* (free text) → **topic restrictions inside the document**. Narrowing parts apply
     immediately **and** are shown on review for confirmation of the interpretation.
   - *Authorized Users* = "assigned project team" → already enforced by membership.
   - *Authorized Users* naming people/external contacts → recorded, **not applied**, flagged (model in W-03).
   - Uninterpretable text → document publishes under existing rules with a "needs review" flag quoting the sentence.
3. **Approval and interim state.**
   - Approver: **CEO** for anything; **PM of the project** only for topics the PM can read, never
     Commercial or classification.
   - While pending: the stricter setting applies; the document stays published (not blocked).
   - Conflicts inside one label (e.g. PM in Authorized Roles but excluded from pricing by Sharing
     Rules): the **stricter part wins** for the affected sections, flagged for confirmation.
   - Every auto-restriction and approval is audited (who, when, label sentence, old → new access).
4. **Versions and missing labels.**
   - Approvals are bound to the exact label text; a changed label is re-decided under rule 1.
   - A **missing or unreadable label never means "no restrictions"**: previous approved policy is
     kept and flagged "label removed/unreadable".
   - Manual overrides by CEO/PM beat the label and persist across versions until changed (W-09 builds on this).

## Simplified (2026-11-26, user: "keep the RAG simple")

Replaces points 1–4 above where they differ:

- **Labels only ever narrow, automatically. Nothing can widen through a label.** No approval queue,
  no approvers, no pending state. Effective access = role table ∩ project membership ∩ document label.
- *Authorized Roles* → document ceiling. *Classification* → fallback ceiling (W-04).
  *Sharing Rules* → narrowing only where the sentence clearly maps to a topic (e.g. "pricing, margin …
  restricted to Finance, Legal, CEO" → Internal finance); stricter part wins.
- *Authorized Users* text (named people, "client contacts in CRM", "proposal team") → **not applied**;
  project membership already defines who is on the project.
- Anything the parser can't map → a plain **note on the review screen** quoting the sentence; the
  CEO/PM can narrow sections by hand if they want. Publishing is never blocked by a note.
- Each version uses its own label; a removed or changed label is shown as a note on review.
- CEO/PM manual narrowing persists across re-index/versions (W-09). Audit log kept.
