"""Permission-filtered retrieval (design decisions 2, 5, 6, 8).

Every call:
1. Loads the user's role, projects and active grants from the database (never from the client).
2. Builds an AccessScope and renders it as a WHERE clause (filter by rules, not doc-ID lists).
3. Runs the vector search as the restricted ``xyz_app`` role with ``app.user_id`` set, so
   row-level security re-checks every row independently of the application filter.
4. Writes an audit_log row, including when nothing authorized was found.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from .db import to_vector
from .embeddings import Embedder
from .policy import AccessScope, Grant, RolePolicy, User, build_scope


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    chunk_key: str
    document_id: str
    document_title: str
    heading: str
    content: str
    distance: float


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    outcome: str   # 'answered' | 'no_authorized_content'


def load_scope(conn: psycopg.Connection, user_id: str, *, now: datetime | None = None) -> AccessScope:
    row = conn.execute(
        """SELECT u.name, u.role, u.company_id, u.is_active, r.scope, r.shared_only
           FROM users u JOIN roles r ON r.name = u.role WHERE u.id = %s""",
        (user_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"unknown user {user_id!r}")
    name, role, company_id, is_active, scope, shared_only = row
    projects = frozenset(r[0] for r in conn.execute(
        "SELECT project_id FROM project_members WHERE user_id = %s", (user_id,)))
    user = User(user_id, name, role, company_id, projects)
    if not is_active:
        return AccessScope.deny_all(user)
    doc_types = frozenset(r[0] for r in conn.execute(
        "SELECT doc_type FROM role_doc_type_policy WHERE role = %s", (role,)))
    grants = [
        Grant(user_id, doc_id, expires_at)
        for doc_id, expires_at in conn.execute(
            "SELECT document_id, expires_at FROM document_grants WHERE user_id = %s AND revoked_at IS NULL",
            (user_id,),
        )
    ]
    policies = {role: RolePolicy(scope, doc_types, shared_only)}
    return build_scope(user, policies, grants, now=now or datetime.now(timezone.utc))


def retrieve(conn: psycopg.Connection, user_id: str, query: str, embedder: Embedder,
             *, k: int = 8, audit: bool = True) -> RetrievalResult:
    query_vec = to_vector(embedder.embed([query])[0])
    with conn.transaction():
        scope = load_scope(conn, user_id)
        _enter_app_role(conn, user_id)
        clause, params = scope.to_sql("c")
        rows = conn.execute(
            f"""SELECT c.id, c.chunk_key, c.document_id, c.heading, c.content,
                       c.embedding <=> %(q)s::vector AS distance
                FROM chunks c
                WHERE {clause}
                ORDER BY c.embedding <=> %(q)s::vector
                LIMIT %(k)s""",
            {**params, "q": query_vec, "k": k},
        ).fetchall()
        titles = dict(conn.execute(
            "SELECT id, title FROM documents WHERE id = ANY(%s)", ([r[2] for r in rows],)
        ).fetchall()) if rows else {}
        # Iterative scans return results in relaxed order; restore exact order.
        chunks = sorted(
            (RetrievedChunk(r[0], r[1], r[2], titles.get(r[2], r[2]), r[3], r[4], float(r[5])) for r in rows),
            key=lambda c: c.distance,
        )
        outcome = "answered" if chunks else "no_authorized_content"
        if audit:
            conn.execute(
                """INSERT INTO audit_log (company_id, user_id, query, retrieved_chunk_ids, outcome)
                   VALUES (%s, %s, %s, %s, %s)""",
                (scope.company_id, user_id, query, [c.id for c in chunks], outcome),
            )
    return RetrievalResult(chunks, outcome)


def _enter_app_role(conn: psycopg.Connection, user_id: str) -> None:
    """Switch this transaction to the RLS-restricted role. Reverts automatically at commit/rollback."""
    conn.execute("SET LOCAL ROLE xyz_app")
    conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
    conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
    conn.execute("SET LOCAL hnsw.ef_search = 100")
