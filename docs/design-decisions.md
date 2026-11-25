# Design Decisions

> **2026-11-25 — access model replaced.** Sections 3, 4 and 11 (client/team/management levels and
> per-document grants) are superseded by **§12 Topic-based access**. They're kept for history.

Agreed during the design review on 2026-11-24. Each decision lists the reason, so it can be revisited
deliberately rather than drifted away from.

## 1. Scope: portfolio piece, built to grow

One company (XYZ Software), seeded users, local + one hosted demo. Every table and every chunk carries
`company_id` so multi-tenancy is a later feature, not a migration.

## 2. pgvector, not a separate vector DB

Users, permissions, documents and embeddings live in one PostgreSQL database. Retrieval is a single SQL
query, so a revoked permission takes effect on the very next query — there is no second store to keep
in sync. Retrieval sits behind a small interface so Qdrant could be added later.

## 3. Permission unit: the section

Documents are split into sections. Each section is `internal` (default) or `client_shared`.
In Markdown sources a section is marked on its heading line:

```markdown
## 5. Delivery Milestones <!-- visibility: client_shared -->
```

- **Deny by default:** an unmarked section is internal. Forgetting a tag can only hide content.
- **A chunk never crosses a section boundary**, so shared and internal text never mix in one chunk.

## 4. Three access layers + explicit grants

1. **Role × document type** (the matrix, stored as data in `role_doc_type_policy`).
2. **Project assignment** (`project_members`).
3. **Section visibility** (clients only ever see `client_shared` sections).

Document types are **standard** (BRD, PRD, Technical, QA, Minutes) or **restricted**
(Contract, Executive Report). Restricted documents are CEO-only by default; anyone else needs an
explicit, optionally expiring row in `document_grants`.

- A grant **widens** access; it never bypasses the client section rule.
- No deny overrides in the MVP.

| Document type     | PM  | Developer | QA  | CEO | Client       | Finance |
|-------------------|-----|-----------|-----|-----|--------------|---------|
| BRD               | ✓   | ✓         | ✓   | ✓   | shared only  | grant   |
| PRD               | ✓   | ✓         | ✓   | ✓   | shared only  | grant   |
| Technical         | ✓   | ✓         | ✓   | ✓   | ✗            | grant   |
| QA                | ✓   | ✓         | ✓   | ✓   | ✗            | grant   |
| Meeting minutes   | ✓   | ✓         | ✓   | ✓   | shared only  | grant   |
| Contract          | grant | grant   | grant | ✓ | grant (shared only) | grant |
| Executive report  | grant | grant   | grant | ✓ | grant (shared only) | grant |

✓ = for assigned projects (CEO: company-wide).

## 5. Data model and retrieval query

```
companies · users(role) · projects · project_members(user, project)
documents(id, project_id NULL = company-wide, doc_type, title, status, version, uploaded_by)
document_sections(id, document_id, ordinal, heading, visibility)
chunks(id, section_id, document_id, project_id, doc_type, visibility, content, embedding vector(1536))
document_grants(user_id, document_id, granted_by, reason, expires_at)
role_doc_type_policy(role, doc_type, scope)
audit_log(user_id, query, retrieved_chunk_ids, denied_reason, at)
```

- `chunks` carries copies of `project_id`, `doc_type`, `visibility` so filtering needs no joins.
  They are updated in the same transaction as their section.
- HNSW index with `hnsw.iterative_scan = relaxed_order` (pgvector ≥ 0.8) so selective filters still
  fill the LIMIT; B-tree on `(company_id, document_id)` for exact scans on small allowed sets.
- Row-level security on `chunks` as a second guard behind the application filter.
- Embeddings: OpenAI `text-embedding-3-small`, 1536 dims.
- Chat history uses keyset pagination on `(conversation_id, created_at, id)`.

## 6. Filter by rules, not by document-ID lists

The backend turns a user's permissions into an **AccessScope** — a small set of rules:

```
(project_id = ANY(:projects) AND doc_type = ANY(:doc_types))
OR document_id = ANY(:granted_doc_ids)
[AND visibility = 'client_shared']        -- clients only
```

For the CEO it collapses to `company_id = :company`. The rule stays small no matter how many documents
exist. Implemented in `backend/app/policy.py`.

## 7. Ingestion failure handling

- Document status: `processing` → `ready` | `failed` (with error). Only `ready` is searchable.
- Embedding runs in a background worker with 3 retries.
- All chunks of a document version are written in one transaction.
- New versions build alongside the old one and swap atomically when ready.
- Concurrent uploads of the same document serialize on a row lock.
- Deletes are soft (hidden immediately, purged later).

## 8. Denied questions get a neutral answer

"I couldn't find information about that in the documents available to you." — identical to the
answer for content that doesn't exist, so the system never confirms that restricted documents exist.
Attempts are logged in `audit_log`.

- Citations are built by the backend from retrieved chunks; AI-invented citations are discarded.
- Document text is data, not instructions. Prompt injection inside a document can only reveal what the
  user was already allowed to retrieve.

## 9. Permission changes and chat history

When a user loses access, old chat history stays visible to them, but every new question (including
follow-ups in old chats) re-retrieves with current permissions, and opening an old citation re-checks
access.

**Updated 2026-11-24 — conversational chat.** The assistant now behaves like a normal chat model:
- It receives the user's own profile (name, role, readable projects) and the last 6 messages of the
  *current* conversation, so it can greet, answer "what's my name?", and handle follow-ups.
- Sending history is safe because it is the user's own conversation, already on their screen; it
  reveals nothing new. Other conversations are never included.
- The model replies as `answer` (XYZ facts — citations required and validated), `chat` (no sources;
  greetings, profile, general knowledge) or `not_found` (the neutral sentence).
- Retrieval for a follow-up also uses the previous user message, so "and which one is in progress?"
  finds the milestones again.
- The project guard and constant-work rule still apply: a message naming only inaccessible projects
  gets the neutral sentence, whatever the model replies.

## 10. Authentication

Own login: bcrypt-hashed passwords, 1-hour JWT, "Demo users" switcher on the login page. The backend
reads only the user ID from the token and loads role, projects and grants from the database on every
request.

## Implementation notes (stage 2)

- **Two DB roles.** The owner runs migrations, seeding and the ingestion worker. Retrieval switches each
  transaction to `xyz_app` with `SET LOCAL ROLE xyz_app` and `set_config('app.user_id', …, true)`;
  both revert at commit. `xyz_app` can read (RLS-filtered) and append to `audit_log`, nothing else.
  In production `xyz_app` should be a separate login rather than a role the owner switches into.
- **RLS function.** `app_can_read()` re-derives access from `users`, `roles`, `role_doc_type_policy`,
  `project_members` and `document_grants`. `app_doc_meta()` is `SECURITY DEFINER` only to break the
  documents ↔ sections policy recursion.
- **Versions are the job queue.** `document_versions.status = 'processing'` rows are claimed with
  `FOR UPDATE SKIP LOCKED`, with a `locked_until` lease so crashed workers' jobs are reclaimed.
  Higher version id = newer upload; an older version finishing late is marked `superseded`.
- **First-upload race.** `submit_document` inserts the document row with `ON CONFLICT DO NOTHING`
  *before* `SELECT … FOR UPDATE`, because a row lock cannot protect a row that doesn't exist yet.

## 11. Document upload (PDF / DOCX) — agreed 2026-11-24

| # | Topic | Decision |
|---|-------|----------|
| 1 | Section levels | 🟢 `client_shared` < 🔵 `team` (default) < 🔴 `management` |
| 2 | Sectioning | DOCX heading styles; PDF headings from font size/boldness; one section per page if none; rename/merge/split on review; scanned PDFs rejected; tables → Markdown |
| 3 | Who uploads | CEO: any type, any project or company-wide. PM: standard types in own projects. Others: none. Backend-enforced |
| 4 | Flow | upload → `parsing` → `draft` (invisible, all 🔵) → review → publish with summary → `processing` → `ready`. Drafts expire after 7 days |
| 5 | Level per role | CEO/PM 🔴🔵🟢 · developer/QA 🔵🟢 · client 🟢. Grants carry their own level; the client cap always wins |
| 6 | Storage | Originals stored by SHA-256 outside the web root; only uploader and CEO can download them |
| 7 | Limits | 20 MB, 300 pages, 500 sections, 60 s parse timeout, 5 files parsing per user; bulk review actions |
| 8 | Edge cases | TOC and repeated headers/footers stripped; most frequent heading level is the boundary; re-uploads reuse levels by heading with a "changed" badge; stale-base and permission re-checks at publish |
| 9 | Fixes | Change a live section's level in one transaction (audited); restore the previous version; zip-bomb limits; isolated parser |
| 10 | Libraries | `python-docx` + `pdfplumber` (MIT); no PyMuPDF (AGPL) |

Implementation notes:
- Drafts reuse `document_sections`; RLS only exposes a document's *current* version, and no chunks
  exist until publish, so drafts cannot reach search.
- Review may rename, merge and split, but the backend rejects any change to the text itself
  (the concatenated content must be identical).
- Merging two sections keeps the *more restrictive* level, so a merge never widens access.
- `visibility_changes` records every level set at publish, live edit and restore.
- Parsing and embedding run as separate worker loops (in the API process in dev, or
  `python -m app.worker`).

## 12. Topic-based access — agreed 2026-11-25

| # | Topic | Decision |
|---|-------|----------|
| 1 | Who decides access | Fixed rules: role × document type × topic. Sections auto-tagged by heading keyword; the uploader only checks tags |
| 2 | Topics | BRD: details, context, goals, requirements, business rules, planning, risks, governance. PRD: details, overview, scope, requirements, delivery. Proposal: details, summary, scope, timeline, engagement, completion. All: commercial, unclassified |
| 3 | Prices | Currency amount + money word → moved into a Commercial section (labelled with its sub-heading) |
| 4 | Refusals | Own project, forbidden topic → the rule is explained. Other project → neutral sentence |
| 5 | Reset | Backup, then all content removed; only BRD/PRD/Proposal; P001 Droob AI, P002 Hub Drives; Finance is a project member |
| 6 | Teams | CEO: projects, PMs, roles. PM: members of own projects. Last PM protected. Audited |
| 7 | Data | `topics`, `topic_headings`, `role_topic_access`; `topic` + generated `access_key` on chunks; index `(company_id, project_id, access_key)`; `membership_changes`; levels and grants dropped |
| 8 | Unmatched headings | *unclassified* (CEO/PM only); never widened by a guess |
| 9 | Review | Publish blocked while anything is unclassified; Review requests for the project's PMs and the CEO; cover blocks → Document details |
| 10 | Failures | Live topic fixes audited; rule changes need no re-processing; optimistic lock between reviewers; permission re-check at publish |

Measured on the real Droob AI BRD, PRD and Proposal PDFs: 48 sections, 46 tagged correctly by
heading, 2 cover blocks sent to review; every "Investment" line split out of the delivery plans.

## Relevance threshold (measured 2026-11-24)

Closest-chunk cosine distance with `text-embedding-3-small` on the 12 demo documents:

| Question set | Range |
|--------------|-------|
| 12 relevant questions (all roles; e.g. "When do I have to pay the second instalment?") | 0.438 – 0.670 |
| 8 off-topic questions (weather, recipes, jokes, trivia) | 0.860 – 0.956 |

Default `RAG_MAX_DISTANCE = 0.77` sits in the gap, slightly toward recall. Off-topic questions are
refused without an LLM call. Re-measure as the corpus grows; the gap will narrow.

## Open risks

- A section wrongly marked `client_shared` will be shown to clients — deny-by-default only covers
  forgotten tags. Mitigated by an admin review screen for uploads.
- Clients see only shared sections, so their view can lag internal reports.
- Permissions prevent leaks, not mistakes: the LLM can still misread authorized content.

## Deferred (scaling path)

- `halfvec`, partitioning `chunks` by `company_id`, or Qdrant behind the retrieval interface at
  millions of chunks.
- Supabase/SSO, multi-company onboarding, deny overrides.
