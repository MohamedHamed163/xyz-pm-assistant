# XYZ PM Assistant — Permission-Based RAG

A project-management AI assistant for a simulated software company. Team members and clients ask
questions about project documents; the assistant answers **only from documents and sections they are
authorized to read**. Permissions are enforced by the backend and the database *before* retrieval —
the LLM never receives unauthorized content.

- Business scenario, people, documents, acceptance tests → [docs/business-scenario.md](docs/business-scenario.md)
- Every design decision and why → [docs/design-decisions.md](docs/design-decisions.md)
- Threat model, attacks, findings, residual risks → [docs/security-report.md](docs/security-report.md)

## Status

| Stage | What | Status |
|-------|------|--------|
| 0 | Scenario, sample documents, seed data | ✅ |
| 1 | Permission engine (`AccessScope`) + security test grid | ✅ |
| 2 | Postgres + pgvector schema, row-level security, ingestion worker, filtered retrieval | ✅ |
| 3 | LLM answers with validated citations, project guard, relevance threshold | ✅ |
| 4 | FastAPI auth, chat history API, React chat UI | ✅ |
| 5 | End-to-end attack suite + security report | ✅ |
| 6 | Conversational chat (profile, follow-ups) | ✅ |
| 7 | PDF/DOCX upload, review & publish, live fixes | ✅ |
| 8 | Topic-based access (role × doc type × topic), review requests, team management | ✅ |

## Layout

```
data/seed/company.yaml        users, projects, role policy, explicit grants
data/documents/               12 sample documents; sections marked <!-- visibility: client_shared -->
backend/migrations/           SQL schema: tables, HNSW + B-tree indexes, RLS policies, xyz_app role
backend/app/documents.py      parse documents → sections → chunks (never crossing a section)
backend/app/policy.py         user permissions → AccessScope (rules, not doc-ID lists) + SQL WHERE clause
backend/app/embeddings.py     OpenAI text-embedding-3-small, or an offline hashing embedder
backend/app/ingestion.py      upload → queued version → worker embeds → atomic swap live
backend/app/retrieval.py      load permissions from DB → filtered vector search as xyz_app → audit log
backend/app/seed_db.py        load the demo company + documents into Postgres
backend/app/answer.py         project guard → retrieve → relevance cut → prompt → validate citations → audit
backend/app/llm.py            OpenAI Chat (strict JSON schema), or an offline extractive answerer
backend/app/ask.py            CLI: ask a question as any demo user
backend/app/parsing.py        PDF/DOCX → sections, in an isolated process with limits
backend/app/uploads.py        upload permissions, drafts, review, publish, live level edits, restore
backend/app/storage.py        original files stored by SHA-256 (local folder; S3 later)
backend/app/worker.py         separate parse and embed loops
backend/app/auth.py           bcrypt passwords, 1-hour JWTs, login rate limit
backend/app/api.py            FastAPI: login, /me, conversations + messages (keyset pages), citation re-check
frontend/                     React + Vite chat UI: demo-user login, history, citations, source panel
backend/tests/                leak grid, acceptance scenarios, DB/RLS equivalence, ingestion failure modes
```

## Run it

Needs PostgreSQL 16+ with pgvector ≥ 0.8 (`brew install postgresql@17 pgvector`).

```bash
python3 -m venv .venv && .venv/bin/pip install pyyaml "psycopg[binary]" psycopg_pool fastapi uvicorn pyjwt bcrypt python-docx pdfplumber python-multipart pytest httpx reportlab
```

```bash
createdb xyz_pm
```

```bash
cd backend && ../.venv/bin/python -m app.seed_db              # add --sample-docs to load the sample corpus
```

Set `OPENAI_API_KEY` first to use real embeddings; without it an offline word-hashing embedder is
used (permissions work identically; ranking is lexical, so "timeline" won't match "milestones").

Run the web app (two terminals):

```bash
cd backend && ../.venv/bin/uvicorn app.api:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 and pick a demo user. Settings are listed in `.env.example`; the demo
password for all fictional users defaults to `xyz-demo-2026`.

Or ask from the command line:

```bash
cd backend && ../.venv/bin/python -m app.ask sara "What is the authentication flow in P001?"
```

Environment: `OPENAI_API_KEY` (real embeddings + answers), `OPENAI_MODEL` (default `gpt-4.1-mini`),
`RAG_MAX_DISTANCE` (relevance cut-off, default 0.77 for OpenAI). Without a key, an offline extractive
answerer quotes the best-matching passage — no reasoning, but the same permission and citation rules.
If you switch embedders, re-create the database: OpenAI and offline vectors must not be mixed.

Tests create and drop their own database `xyz_pm_test` (`tests/test_live_openai.py` runs only with a key):

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## How permissions are enforced — two independent layers

1. **Application filter.** Each request loads the user's role, projects and active grants from the
   database and renders an `AccessScope` as a SQL `WHERE` clause on the vector search.
2. **Row-level security.** The search runs as the restricted `xyz_app` role with `app.user_id` set
   for the transaction. Postgres re-derives access from its own permission tables for every row.

The tests prove the Python policy, the SQL path and RLS-alone return **identical** chunk sets for every
user, and that RLS still holds when the application filter is deliberately broken.

## How leaks are tested

Each document contains **canary facts** (e.g. the contract fee `USD 486,000`, the internal margin
`USD 352,000`, `BUG-412`). `tests/test_permissions.py` declares, per user, exactly which canaries they
may retrieve; every other canary must be invisible.

## How an answer is produced

The assistant chats like a normal LLM — greetings, "what's my name?", follow-ups, general questions —
but anything about XYZ (projects, clients, contracts, people, documents) must come from documents
the user may read, with citations. Each reply is one of: a cited **answer**, a **chat** reply (never
with sources), or the neutral "couldn't find" sentence.

1. **Project guard** — a question that names only projects the user can't access ("P002", "Droop",
   "Project B") gets the neutral answer. The full pipeline still runs over the user's own content and
   is discarded, so response time can't reveal which names are real projects.
2. **Retrieve** authorized chunks, narrowed to named projects (+ company-wide docs).
3. **Relevance cut-off** — only passages close enough to the question are given to the model
   (for follow-ups, the previous question is included in the search).
4. **Prompt** — the user's own profile, the last 6 messages of this conversation, and the passages
   wrapped in `<passage>` blocks declared untrusted data; neither documents nor user text can open
   or close a prompt block.
5. **Validate** — strict JSON (`answer` / `chat` / `not_found`); citation numbers that don't match a
   passage are dropped; an `answer` with no valid citation becomes the neutral text; `chat` replies
   never show sources.
6. **Audit** — one row per question: outcome, retrieved chunk ids, cited chunk ids, named projects.

Every refusal path returns the identical sentence, so a refusal never confirms that something exists.
Tests cover a fully compromised model that dumps its whole prompt: it can only leak what the user
was already allowed to read.

## Access model — role × document type × topic

The assistant knows three document types — **BRD, PRD, Proposal** — and splits each into sections.
Every section is tagged with a **topic** automatically from its heading; a fixed rule table decides
which roles read which topics, in the projects they belong to (the CEO sees every project).

| Role | BRD | PRD | Proposal |
|------|-----|-----|----------|
| CEO, Project Manager, Client | everything | everything | everything |
| Developer | Context, Requirements & scope | everything except Commercial | Scope & deliverables, Timeline |
| QA Engineer | Goals & objectives, Business rules | everything except Commercial | Scope & deliverables, Completion & approval |
| Finance Manager | Goals & objectives, Commercial | Overview, Scope, Commercial | everything |

Plus "Document details" (the cover block) for anyone who may read part of a document.

- **Prices are split out**: a line with a currency amount and a money word ("Investment: $1,000")
  moves into a Commercial section — labelled with the plan it came from — so it never reaches a
  developer or QA engineer even when it sat inside an allowed section.
- **Unrecognized headings** become *Unclassified* (CEO/PM only). A document can't be published until
  every section has a topic; it appears under **Review requests** for the project's PMs and the CEO.
- **Asking outside your topics** gets the rule explained ("pricing is in the Proposal's Commercial
  section, which your role doesn't include"); asking about **another project** gets a neutral answer.

The rules live in `data/seed/company.yaml` (seeded into `role_topic_access`); changing a rule applies
on the next question without re-processing any document.

## Uploading documents and managing teams

CEO and PMs get a **Documents** button:

1. **Upload** a BRD, PRD or Proposal (PDF or Word) to a project — or a new version of one.
2. Sections are parsed and tagged; prices split out; tables of contents and page headers removed.
3. **Review**: check topics (bulk set, filter, search), rename, merge or split. The text itself can't
   change. Two reviewers can't overwrite each other — the second gets "reload".
4. **Publish** after a summary of who reads each topic.
5. **Live documents**: fix a section's topic later (immediate, audited) or restore the previous version.
6. **Team**: the CEO creates projects, assigns PMs and changes roles; PMs add or remove members on
  their own projects. Every project keeps a PM; every change is recorded.

Sample files for testing: `samples/Hub Drives BRD.pdf`, `Hub Drives PRD.docx`, `Hub Drives Proposal.pdf`.

## API

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/auth/login` | email + password → 1-hour bearer token; 10 failures / 10 min per email → 429 |
| GET | `/api/auth/demo-users` | login-page picker; 404 unless `DEMO_MODE=true` |
| GET | `/api/me` | role, readable projects, `client_view` — reloaded from the DB every request |
| GET/POST/DELETE | `/api/conversations` | own conversations only; keyset pagination (`cursor`) |
| GET/POST | `/api/conversations/{id}/messages` | POST asks a question; GET pages history (`before`) |
| GET | `/api/citations/{chunk_id}` | re-checks access when a source is opened; 404 if not readable |
| GET | `/api/uploads/options` | projects and document types this user may upload to |
| POST | `/api/uploads` | multipart file + project/type/title (or `document_id` for a new version) → 202 |
| GET | `/api/uploads`, `/api/uploads/{id}` | my uploads; a draft with its sections |
| PUT | `/api/uploads/{id}/sections` | save review edits (text must stay identical) |
| POST | `/api/uploads/{id}/publish`, `/discard` | publish (re-checks permission and base version) or discard |
| GET | `/api/uploads/{id}/file` | original file — uploader and CEO only |
| GET | `/api/documents/manage` | live documents this user may manage |
| PATCH | `/api/documents/{id}/sections/{n}` | change a live section's level (immediate, audited) |
| POST | `/api/documents/{id}/restore-previous` | make the previous version live again |

The API reports only `answered`, `no_answer` or `error`. Internal outcomes such as
`out_of_scope_project` stay in `audit_log`, because telling a user *why* there was no answer would
confirm that a project or document exists.

## Known limits / next

- The token is kept in `sessionStorage`; an httpOnly cookie would be stronger against XSS.

- The live OpenAI suite (`tests/test_live_openai.py`) passes; `RAG_MAX_DISTANCE` was tuned on 20
  questions of this demo corpus. Re-measure it when the document set grows.
- The offline embedder is lexical: "timeline" won't find "milestones".
- RLS evaluates `app_can_read()` per row; fine at demo scale. At millions of chunks, see the scaling
  path in the design doc.
