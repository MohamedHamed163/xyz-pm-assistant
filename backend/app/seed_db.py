"""Load the demo company (projects, users, topic rules) and optionally sample documents into Postgres.

    cd backend && ../.venv/bin/python -m app.seed_db                 # company + rules only (empty documents)
    cd backend && ../.venv/bin/python -m app.seed_db --sample-docs   # also the Markdown sample corpus

Idempotent. Topic rules are replaced from the YAML on every run. Users are upserted; project
memberships are only seeded for users created by this run, so team changes made in the app survive.
"""

from __future__ import annotations

import hashlib
import sys

import psycopg
import yaml

from .auth import demo_password, hash_password
from .db import apply_migrations, connect
from .embeddings import Embedder, default_embedder
from .ingestion import run_worker_until_empty, submit_document
from .seed import DOCUMENTS_DIR, SEED_FILE, load_company


def seed_company(conn: psycopg.Connection) -> None:
    company = load_company()  # validates the YAML (unknown roles, topics, projects) before touching the DB
    raw = yaml.safe_load(SEED_FILE.read_text(encoding="utf-8"))
    cid = raw["company"]["id"]
    rules = company.rules
    # All demo users share one demo password (set DEMO_PASSWORD; see .env.example). Hashed once.
    password_hash = hash_password(demo_password()) if demo_password() else None
    with conn.transaction():
        conn.execute(
            "INSERT INTO companies (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            (cid, raw["company"]["name"]),
        )
        for p in raw["projects"]:
            conn.execute(
                """INSERT INTO projects (id, company_id, name, client_name, aliases) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, client_name = EXCLUDED.client_name,
                     aliases = EXCLUDED.aliases""",
                (p["id"], cid, p["name"], p.get("client"), p.get("aliases", [])),
            )
        for name, spec in raw["doc_types"].items():
            conn.execute(
                """INSERT INTO doc_types (name, label) VALUES (%s, %s)
                   ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label""",
                (name, spec["label"]),
            )
        for role, scope in rules.role_scope.items():
            conn.execute(
                "INSERT INTO roles (name, scope) VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET scope = EXCLUDED.scope",
                (role, scope),
            )

        # Topic rules: replaced wholesale from the YAML.
        conn.execute("DELETE FROM role_topic_access")
        conn.execute("DELETE FROM topic_headings")
        for doc_type, topics in rules.topics.items():
            conn.execute("DELETE FROM topics WHERE doc_type = %s AND NOT (key = ANY(%s))", (doc_type, list(topics)))
            for n, (key, label) in enumerate(topics.items()):
                conn.execute(
                    """INSERT INTO topics (doc_type, key, label, ordinal) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (doc_type, key) DO UPDATE SET label = EXCLUDED.label, ordinal = EXCLUDED.ordinal""",
                    (doc_type, key, label, n),
                )
            for keyword, topic in rules.headings[doc_type]:
                conn.execute("INSERT INTO topic_headings (doc_type, keyword, topic) VALUES (%s, %s, %s)",
                             (doc_type, keyword, topic))
        for role, by_type in rules.role_access.items():
            for doc_type, topics in by_type.items():
                for topic in sorted(topics):
                    conn.execute("INSERT INTO role_topic_access (role, doc_type, topic) VALUES (%s, %s, %s)",
                                 (role, doc_type, topic))

        for u in raw["users"]:
            (created,) = conn.execute(
                """INSERT INTO users (id, company_id, name, email, role, organization) VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email,
                     organization = EXCLUDED.organization
                   RETURNING (xmax = 0)""",
                (u["id"], cid, u["name"], u["email"], u["role"], u.get("organization")),
            ).fetchone()
            if password_hash:
                conn.execute("UPDATE users SET password_hash = %s WHERE id = %s AND password_hash IS NULL",
                             (password_hash, u["id"]))
            no_memberships = conn.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM project_members WHERE user_id = %s)", (u["id"],)).fetchone()[0]
            if created or no_memberships:
                for pid in u["projects"]:
                    conn.execute("INSERT INTO project_members (user_id, project_id) VALUES (%s, %s) "
                                 "ON CONFLICT DO NOTHING", (u["id"], pid))


def seed_documents(conn: psycopg.Connection, embedder: Embedder, uploaded_by: str = "u-mona") -> list:
    """Load the Markdown sample corpus (data/documents) — used by the tests and for quick demos."""
    live = dict(conn.execute(
        """SELECT d.id, v.source_sha256 FROM documents d
           JOIN document_versions v ON v.id = d.current_version_id"""
    ).fetchall())
    for path in sorted(DOCUMENTS_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_id = yaml.safe_load(text.split("---")[1])["id"]
        if live.get(doc_id) == hashlib.sha256(text.encode()).hexdigest():
            continue
        submit_document(conn, text, uploaded_by=uploaded_by)
    return run_worker_until_empty(conn, embedder)


def seed_all(conn: psycopg.Connection, embedder: Embedder | None = None, *, with_documents: bool = False) -> list:
    apply_migrations(conn)
    seed_company(conn)
    return seed_documents(conn, embedder or default_embedder()) if with_documents else []


def main() -> int:
    embedder = default_embedder()
    with connect() as conn:
        results = seed_all(conn, embedder, with_documents="--sample-docs" in sys.argv)
    print(f"embedder: {embedder.name}")
    for r in results:
        print(f"  {r.document_id:30s} v{r.version_id:<4d} {r.outcome}" + (f"  ({r.error})" if r.error else ""))
    print(f"{len(results)} document version(s) processed")
    return 0 if all(r.outcome == "ready" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
