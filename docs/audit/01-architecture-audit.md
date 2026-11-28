# Phase 1 — Architecture Audit

Date: 2026-11-26 · Scope: `backend/app` (≈3,550 lines), `backend/migrations` (7), `frontend/src`, 153 test
functions in 13 files. **No code was changed for this audit.**

## 1. Architecture as it is today

```
Upload (PDF/DOCX)  ─► storage (sha256) ─► parse worker (isolated process) ─► sections
Markdown (seed)    ─► parse_document (needs YAML front matter) ──────────────► sections
                                                                     │
         topics.classify(heading keywords) + split_commercial(price lines)
                                                                     ▼
                          draft (review screen; publish blocked if "unclassified")
                                                                     ▼
            embed worker ─► chunks (pgvector, HNSW) with project_id, doc_type, topic, access_key
                                                                     ▼
Question ─► load_scope(user) from DB ─► SQL filter (project ∧ access_key) + RLS (same rule)
         ─► top-k=8, cosine ≤ 0.77 ─► prompt (profile, last 6 messages, passages) ─► OpenAI
         ─► answer | chat | not_found ─► backend-built citations ─► audit_log
```

| Area | Where | What it does |
|------|-------|--------------|
| Formats | `parsing.py:detect_kind` | Uploads: **PDF and DOCX only**, by magic bytes. Markdown only via the seed path, and only with YAML front matter (`documents.py:72`). |
| Parsing | `parsing.py` | DOCX heading styles; PDF headings by font size/bold; TOC and repeated header/footer removal; tables → Markdown; 300 pages / 500 sections / 20 MB; 60 s isolated subprocess. |
| Metadata | `documents` table | Stores **id, project_id, doc_type, title, status** only. Owner, classification, authorized roles/users, sharing rules, version label: **not extracted, not stored**. |
| Topics | `topics.py`, `company.yaml` | Section → topic by heading keyword (longest match). Unmatched → `unclassified` (CEO/PM only). |
| Sensitive data | `topics.split_commercial` | Moves sentences with a **currency amount + money word** into a `commercial` section. Nothing else is detected. |
| Chunking | `documents.chunk_document` | Per section, paragraph-packed to 1,200 chars, **hard split** for larger paragraphs (`documents.py:175`). Chunk text prefixed `"{title} — {heading}"`. |
| Embeddings | `embeddings.py` | `text-embedding-3-small` (1536-d), or offline hashing embedder. |
| Vector store | `chunks` (pgvector) | Carries `company_id, project_id, doc_type, topic, access_key, status`. No owner/classification/section-path. |
| Auth | `auth.py`, `api.py` | bcrypt + 1-hour JWT (user id only); role/projects reloaded from DB every request. |
| Permissions | `policy.py`, migration 007 | Project membership (CEO: all) × `role_topic_access(role, doc_type, topic)`. Two layers: SQL filter and **RLS** (`app_can_read`), tested equal. No per-user, group or document-level grants (removed in 007). |
| Retrieval | `retrieval.py`, `answer.py:160` | Vector-only, top-k 8, threshold 0.77 (OpenAI). Follow-up = previous user question + current. Project guard by name/alias string. |
| LLM | `answer.py` | Profile (incl. own allowed/forbidden topics), last 6 messages of this conversation, delimited passages. JSON `answer/chat/not_found`. |
| Citations | `answer.validate_citations` | Built by the backend from retrieved chunks; invented numbers dropped. Fields: document, heading, snippet — **no page numbers, no document version**. |
| Tests | `backend/tests` | Leak grid per role/topic, Python/SQL/RLS equivalence, compromised-model sweeps, IDOR, token forgery, cross-tenant, parser round-trip, uploads, teams, 17 live OpenAI tests. |

## 2. Strengths

- **Permissions enforced before the LLM**, in two independent layers (application filter + Postgres RLS) that are tested to agree; the model never receives unauthorized chunks.
- **Fail-closed defaults**: unknown headings → `unclassified` (CEO/PM only); unknown roles see nothing; publish blocked until classified.
- **Backend-built citations**, constant-work refusals (no timing oracle), neutral answers that confirm nothing.
- **Strong adversarial tests**: two "fully compromised model" sweeps, mutation-checked.
- Permission changes apply on the **next request** (no cached authorization).

## 3. Weaknesses

1. **Document metadata is ignored.** The Nexora documents declare classification, owner, authorized roles/users and sharing rules; none of it is parsed, stored or checked.
2. **Access is decided only by section topic**, never by document classification. A *Commercial-Confidential* proposal is readable in part by Developers (Scope, Timeline) even though the document lists only CEO/PM/Finance/Legal.
3. **`commercial` conflates client-facing pricing with internal cost/margin.** Clients and PMs can read both.
4. **Sensitive-data detection is currency-only**: "gross margin target 32%" or a "contingency reserve" without a currency word isn't detected.
5. **Role vocabulary is too small** for the samples: no Legal, Operations, Account team, Instructor, Vendor, Student.
6. **No user-specific or group grants** ("client contacts listed in CRM", "named proposal team").
7. **Markdown documents can't be ingested** without hand-written front matter; uploads reject `.md`.
8. **Re-indexing loses manual decisions**: the Markdown path re-classifies from keywords; the upload path re-uses topics only when the heading text matches exactly.
9. **Chunking loses relationships**: User Stories and Acceptance Criteria become separate sections with no link; tables larger than 1,200 chars are cut mid-row and lose their header.
10. **Retrieval is vector-only** (no keyword/BM25 component, no reranking); IDs like "BR-02" or "US-03" depend on embeddings alone.
11. **Citations have no page or version**, although the PRDs require page references.

## 4. Security vulnerabilities

| # | Finding | Severity | Evidence |
|---|---------|----------|----------|
| V1 | **Price-split widens access**: a sentence in an internal "Confidential Note" (unclassified → CEO/PM) is moved into `commercial`, which **clients and Finance** can read. Restricted content inherits a broader permission. | **High** | Evaluation §3: Client retrieves "Internal estimated delivery cost: USD 15,000". |
| V2 | **Document-declared restrictions are not enforced** (classification, authorized roles, sharing rules). Policy contradicts the document for clients (full BRD/PRD) and PMs (internal cost). | High | Evaluation §3 matrix. |
| V3 | **Re-index reverts a manual narrowing** to the keyword topic (can broaden). | Medium | Evaluation §4: `risks` → back to `planning` after re-index. |
| V4 | **Conversation history** sends earlier answers to the model even after access is revoked; the model can restate them (accepted trade-off in decision 9, but conflicts with the brief's test 10). | Medium | `answer.py` history handling; design-decisions §9. |
| V5 | Topic tagging trusts heading text: an uploader (PM) can widen access by naming a section "Business Rules". Insider risk, mitigated by review and audit only. | Low | `topics.classify` |
| V6 | Metadata block becomes the `details` topic, readable by every role with any access to the document (sharing rules, team names). | Low | Evaluation §2. |

Existing mitigations (unchanged): JWT in `sessionStorage`, demo mode, per-process rate limit — see `docs/security-report.md`.

## 5. Retrieval weaknesses

- Vector-only search; identifiers (BR-02, US-03) and exact terms rely on embeddings.
- Project narrowing depends on literal aliases; a misspelled project name escapes narrowing (safe, but less precise).
- Follow-up rewriting is naive concatenation, not a standalone-question rewrite.
- No measured baseline for relevance, citation accuracy or answer accuracy on a fixed dataset (only 17 live spot checks).

## 6. Missing capabilities (vs. the brief)

Metadata extraction (all 14 fields) · schema validation · ambiguity/conflict flagging · document-level policy · user/group grants · conditional rules · client-shareable flag · internal-vs-client commercial split · non-currency sensitive data · requirement↔acceptance-criteria linkage · table-aware chunking · `.md` ingestion · retrieval-quality evaluation dataset and metrics.
