# XYZ PM Assistant — Permission-Based RAG

A project-management AI assistant for a simulated software company. Team members and clients ask
questions about project documents; the assistant answers **only from documents and sections they are
authorized to read**. Permissions are enforced by the backend and the database *before* retrieval —
the LLM never receives unauthorized content.

- Business scenario, people, documents, acceptance tests → [docs/business-scenario.md](docs/business-scenario.md)
- Every design decision and why → [docs/design-decisions.md](docs/design-decisions.md)

## Status

| Stage | What | Status |
|-------|------|--------|
| 0 | Scenario, sample documents, seed data | ✅ |
| 1 | Permission engine (`AccessScope`) + security test grid | ✅ |
| 2 | Postgres + pgvector schema, row-level security, ingestion worker, filtered retrieval | ✅ |
| 3 | LLM answers with validated citations, project guard, relevance threshold | ✅ |
| 4 | FastAPI auth + React chat UI | ⏳ next |
| 5 | Prompt-injection and leak testing end to end | — |

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
backend/tests/                leak grid, acceptance scenarios, DB/RLS equivalence, ingestion failure modes
```

## Run it

Needs PostgreSQL 16+ with pgvector ≥ 0.8 (`brew install postgresql@17 pgvector`).

```bash
python3 -m venv .venv && .venv/bin/pip install pyyaml "psycopg[binary]" pytest
```

```bash
createdb xyz_pm
```

```bash
cd backend && ../.venv/bin/python -m app.seed_db
```

Set `OPENAI_API_KEY` first to use real embeddings; without it an offline word-hashing embedder is
used (permissions work identically; ranking is lexical, so "timeline" won't match "milestones").

Ask questions as any demo user:

```bash
cd backend && ../.venv/bin/python -m app.ask sara "What is the authentication flow in P001?"
```

Environment: `OPENAI_API_KEY` (real embeddings + answers), `OPENAI_MODEL` (default `gpt-4.1-mini`),
`RAG_MAX_DISTANCE` (relevance cut-off, default 0.75 for OpenAI). Without a key, an offline extractive
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

1. **Project guard** — a question that names only projects the user can't access ("P002", "Droop",
   "Project B") gets the neutral answer with no retrieval and no LLM call.
2. **Retrieve** authorized chunks, narrowed to named projects (+ company-wide docs).
3. **Relevance cut-off** — nothing close enough → neutral answer, no LLM call.
4. **Prompt** — passages are wrapped in `<passage>` blocks, declared untrusted data; a passage cannot
   close its own delimiter.
5. **Validate** — strict JSON; citation numbers that don't match a passage are dropped; an answer with
   no valid citation, or with `found=false`, is replaced by the neutral text.
6. **Audit** — one row per question: outcome, retrieved chunk ids, cited chunk ids, named projects.

Every refusal path returns the identical sentence, so a refusal never confirms that something exists.
Tests cover a fully compromised model that dumps its whole prompt: it can only leak what the user
was already allowed to read.

## Known limits / next

- The OpenAI path is implemented but has only been exercised by its skipped live test — run
  `tests/test_live_openai.py` with a key, and tune `RAG_MAX_DISTANCE` on real questions.
- The offline embedder is lexical: "timeline" won't find "milestones".
- RLS evaluates `app_can_read()` per row; fine at demo scale. At millions of chunks, see the scaling
  path in the design doc.
