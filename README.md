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
| 3 | LLM answers with citations + relevance threshold | ⏳ next |
| 4 | FastAPI auth + React chat UI | — |
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

Tests create and drop their own database `xyz_pm_test`:

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

## Known limits / next

- Retrieval always returns the top-k *authorized* chunks, even if irrelevant. When Sara asks about
  P002, she gets P001 auth chunks. Stage 3 must add a relevance threshold and instruct the LLM to give
  the neutral "couldn't find" answer when retrieved content doesn't answer the question.
- RLS evaluates `app_can_read()` per row; fine at demo scale. At millions of chunks, see the scaling
  path in the design doc.
