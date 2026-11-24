"""Load the demo company and documents into Postgres.

    cd backend && ../.venv/bin/python -m app.seed_db            # uses DATABASE_URL or dbname=xyz_pm

Idempotent for the company records (upserts). Documents are only (re)queued when their source text
changed since the live version.
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
    load_company()  # validates the YAML (unknown roles, projects, doc types) before touching the DB
    raw = yaml.safe_load(SEED_FILE.read_text(encoding="utf-8"))
    cid = raw["company"]["id"]
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
                """INSERT INTO doc_types (name, label, restricted) VALUES (%s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label, restricted = EXCLUDED.restricted""",
                (name, spec["label"], spec["restricted"]),
            )
        for role, spec in raw["role_policy"].items():
            conn.execute(
                """INSERT INTO roles (name, scope, shared_only, max_visibility) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET scope = EXCLUDED.scope, shared_only = EXCLUDED.shared_only,
                     max_visibility = EXCLUDED.max_visibility""",
                (role, spec["scope"], bool(spec.get("shared_only", False)), spec.get("max_visibility", "team")),
            )
            conn.execute("DELETE FROM role_doc_type_policy WHERE role = %s", (role,))
            for dt in spec["doc_types"]:
                conn.execute("INSERT INTO role_doc_type_policy (role, doc_type) VALUES (%s, %s)", (role, dt))
        for u in raw["users"]:
            conn.execute(
                """INSERT INTO users (id, company_id, name, email, role, organization) VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email,
                     role = EXCLUDED.role, organization = EXCLUDED.organization""",
                (u["id"], cid, u["name"], u["email"], u["role"], u.get("organization")),
            )
            if password_hash:
                conn.execute("UPDATE users SET password_hash = %s WHERE id = %s AND password_hash IS NULL",
                             (password_hash, u["id"]))
            conn.execute("DELETE FROM project_members WHERE user_id = %s", (u["id"],))
            for pid in u["projects"]:
                conn.execute("INSERT INTO project_members (user_id, project_id) VALUES (%s, %s)", (u["id"], pid))


def seed_grants(conn: psycopg.Connection) -> None:
    """Grants reference documents, so they are inserted after documents exist."""
    raw = yaml.safe_load(SEED_FILE.read_text(encoding="utf-8"))
    with conn.transaction():
        for g in raw.get("grants", []):
            conn.execute(
                """INSERT INTO document_grants (user_id, document_id, granted_by, reason, expires_at, max_visibility)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id, document_id) WHERE revoked_at IS NULL
                   DO UPDATE SET max_visibility = EXCLUDED.max_visibility""",
                (g["user"], g["document"], g.get("granted_by"), g.get("reason"), g.get("expires_at"),
                 g.get("max_visibility", "team")),
            )


def seed_documents(conn: psycopg.Connection, embedder: Embedder, uploaded_by: str = "u-mona") -> list:
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


def seed_all(conn: psycopg.Connection, embedder: Embedder | None = None) -> list:
    apply_migrations(conn)
    seed_company(conn)
    results = seed_documents(conn, embedder or default_embedder())
    seed_grants(conn)
    return results


def main() -> int:
    embedder = default_embedder()
    with connect() as conn:
        results = seed_all(conn, embedder)
    print(f"embedder: {embedder.name}")
    for r in results:
        print(f"  {r.document_id:30s} v{r.version_id:<4d} {r.outcome}" + (f"  ({r.error})" if r.error else ""))
    print(f"{len(results)} document version(s) processed")
    return 0 if all(r.outcome == "ready" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
