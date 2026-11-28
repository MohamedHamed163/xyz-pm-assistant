# Phase 2 — Evaluation of the Current Pipeline on the Nexora Samples

Date: 2026-11-26 · Corpus: 9 Markdown documents (BRD/PRD/Proposal × P001 E-Commerce, P002 Droop LMS,
P003 Hub Drives) · Run against an **unmodified** pipeline in a throwaway database (`xyz_pm_eval`), offline
embedder, demo users (CEO Mona; P001: PM Hamed, Developer Sara, QA Omar, Finance Khaled, Client Amina;
P002: Developer Youssef). Script and raw JSON: kept outside the repo for now (will be committed with the
evaluation-dataset ticket).

> The documents' access labels were treated as **proposed policy**, not truth (per the sample README).
> "Doc says" below means "what the document declares" — a reference point, not the answer key.

## 1. Can it ingest the documents?

| Path | Result (9/9 documents) |
|------|-----------------------|
| Markdown seed path, as-is | **Rejected** — "missing YAML front matter" |
| Upload, as-is (`.md`) | **Rejected** — "Only PDF and Word (.docx) files can be uploaded" |
| Markdown path with a minimal hand-added front matter | Accepted, all 9 `ready` |

All further results use the hand-wrapped versions — the best case today.

## 2. Topic tagging (52 sections: 9 metadata blocks + 43 content sections)

| Document | Sections → topic (⚠ = unclassified, CEO/PM only) |
|----------|-----------------------------------------------|
| BRD-P001 | Background→context · Business Objectives→goals · Requirements→requirements · Constraints→planning · Stakeholders→governance |
| PRD-P001 | Scope→scope · User Stories→requirements · Acceptance Criteria→requirements · ⚠ Non-Functional · ⚠ Admin-only feature |
| Proposal-P001 | ⚠ Proposed Solution · Deliverables→scope · Timeline→timeline · Commercial Terms→commercial · ⚠ Assumptions · ⚠ Confidential Note · **Commercial details — from Confidential Note→commercial** |
| BRD-P002 | ⚠ Business Goal · Business Requirements→requirements · ⚠ Success Metrics · Stakeholders→governance |
| PRD-P002 | ⚠ Features · User Stories→requirements · ⚠ Restricted Content · Acceptance Criteria→requirements |
| Proposal-P002 | Scope→scope · Deliverables→scope · Schedule→timeline · Commercial Terms→commercial · ⚠ Internal Risk Assessment |
| BRD-P003 | ⚠ Business Goal · Business Requirements→requirements · Stakeholders→governance · ⚠ Success Metrics |
| PRD-P003 | ⚠ Features · User Stories→requirements · ⚠ Access Rules · Acceptance Criteria→requirements |
| Proposal-P003 | Proposed Scope→scope · Deliverables→scope · Timeline→timeline · Commercial Terms→commercial · ⚠ Internal Notes |

**15 of 43 content sections (35%) unclassified**, because the keyword list was built for a different
template ("Business Goal" vs "Business Goals", "Features", "Success Metrics", "Proposed Solution").
Every metadata block became an "Introduction" section tagged `details`.

## 3. Who can retrieve what today (Y = retrievable)

| Probe (exact text) | CEO | PM P001 | Dev P001 | QA P001 | Finance P001 | Client P001 | Dev P002 | Doc says |
|---|---|---|---|---|---|---|---|---|
| P001 internal delivery cost "USD 15,000" | Y | **Y** | · | · | Y | **Y ❌** | · | CEO, Finance, Legal, account team |
| P001 illustrative total "USD 24,000" | Y | Y | · | · | Y | Y | · | CEO, PM, Finance, Legal, (client contacts?) |
| P001 admin-only refund feature | Y | Y | · ⚠ | · ⚠ | · | · | · | CEO, PM, Developer, QA |
| P001 PRD non-functional (HTTPS, audit log) | Y | Y | · ⚠ | · ⚠ | · | · | · | CEO, PM, Developer, QA (no client) |
| P001 BRD constraints "12 weeks" | Y | Y | · ⚠ | · ⚠ | · | **Y ❌** | · | CEO, PM, Dev, QA; client: approved summary only |
| P002 BRD content | Y | · | · | · | · | · | Y | P002 team, CEO |
| P002 answer-key rule | Y | · | · | · | · | · | · ⚠ | CEO, PM, Dev, QA, Instructor |
| P002 contingency reserve "USD 4,000" | Y | · | · | · | · | · | · | CEO, Finance, Legal, account team |
| P003 gross margin "32%" | Y | · | · | · | · | · | · | CEO, Finance, Legal, account team |
| P003 commission rule | Y | · | · | · | · | · | · | CEO, PM, Dev, QA, Operations |

❌ = more access than the document allows (**leak relative to declared policy**) · ⚠ = less access than the
document allows (safe, but answers are missing).

## 4. Results against the 15 required capabilities

| # | Capability | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Identify document type (BRD/PRD/Proposal) | ❌ Fail | Not read from the document; must be supplied by uploader/front matter. |
| 2 | Extract document ID & project ID | ❌ Fail | `BRD-P001-001` etc. ignored; project comes from the upload form. |
| 3 | Extract owner | ❌ Fail | No column; stays in text. |
| 4 | Extract classification | ❌ Fail | Internal / Confidential / Commercial-Confidential ignored. |
| 5 | Roles permitted | ❌ Fail | Declared roles ignored; access from `role_topic_access` only. Roles Legal, Operations, Instructor, Vendor, Student don't exist. |
| 6 | User-specific permissions | ❌ Fail | No user/document grants since migration 007. |
| 7 | Project-based permissions | ✅ Pass | Cross-project denial holds both ways (Dev P001 ↛ P002/P003, Dev P002 ↛ P001). |
| 8 | Conditional access rules | ❌ Fail / N/A | "Phone shown after booking confirmed" is not representable — and is arguably a *product* rule, not a document ACL (see ticket W-06). |
| 9 | Client-sharing restrictions | ❌ Fail | Client reads full BRD and internal cost; "approved summary only" not supported. |
| 10 | Sensitive information | ⚠ Partial | Currency lines detected (1 of 3 internal-finance facts); margin % and reserve wording not detected — protected only because their sections happened to be unclassified. |
| 11 | Sections with different permission levels | ⚠ Partial | Per-section topics exist; restricted sections ("Confidential Note", "Internal Notes") are only protected when unclassified, not by intent. |
| 12 | Document context in chunks | ⚠ Partial | Title + heading prefixed; no document ID, classification or heading path; large tables split mid-row. |
| 13 | Permission metadata on every chunk | ⚠ Partial | Every chunk has project + topic; no classification/owner/grant data. **Re-index reverted a manual topic fix** (`risks` → `planning`). |
| 14 | Accurate citations | ⚠ Partial | Backend-built and validated; no page/version; requirement↔acceptance-criteria not linked. |
| 15 | Prevent unauthorized retrieval | ⚠ Partial | Holds for the *configured* policy (cross-project, topic). Fails against *declared* policy: client and PM retrieve internal cost (V1/V2). |

**Score: 1 pass · 6 partial · 8 fail.**

## 5. Required security tests (brief, Phase 6) — current status

| # | Scenario | Today |
|---|----------|-------|
| 1 | Dev P001 can't retrieve P002 | ✅ covered (`test_role_table`, eval) |
| 2 | Dev can't retrieve confidential commercial | ✅ for `commercial` topic; ⚠ Dev reads parts of Commercial-Confidential proposals |
| 3 | Client can't retrieve internal technical docs | ❌ client reads full PRD by role table |
| 4 | Client can't retrieve internal financial info | ❌ **client retrieves "USD 15,000" internal cost** |
| 5 | PM can't access unassigned projects | ✅ covered |
| 6 | CEO accesses what policy allows | ✅ covered |
| 7 | Unauthorized content never reaches the LLM | ✅ covered (compromised-model sweeps) — for configured policy |
| 8 | Not in citations | ✅ covered |
| 9 | Prompt injection can't bypass | ✅ covered |
| 10 | Follow-ups / history can't bypass | ⚠ retrieval yes; history replays earlier answers after revocation (V4) |
| 11 | Ambiguous permissions handled safely | ⚠ headings yes (unclassified); declared metadata ambiguity not detected |
| 12 | Conflicting permissions flagged | ❌ not detected |
| 13 | Re-index doesn't broaden | ❌ manual fix reverted on re-index |
| 14 | Permission changes apply immediately | ✅ covered |

## 6. Retrieval quality

Not yet measurable: there is no fixed question set with expected answers and expected authorized
documents. Building that dataset and a baseline is the first ticket on the map (W-01).
