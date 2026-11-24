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

_CHUNK_COLUMNS = "c.id, c.chunk_key, c.document_id, c.project_id, c.heading, c.content"


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    chunk_key: str
    document_id: str
    project_id: str | None
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


def accessible_projects(conn: psycopg.Connection, scope: AccessScope) -> frozenset[str]:
    """Projects the user can read anything in: assigned projects + projects of granted documents."""
    if scope.company_wide:
        return frozenset(r[0] for r in conn.execute(
            "SELECT id FROM projects WHERE company_id = %s", (scope.company_id,)))
    granted = {r[0] for r in conn.execute(
        "SELECT project_id FROM documents WHERE id = ANY(%s) AND project_id IS NOT NULL",
        (sorted(scope.granted_document_ids),),
    )}
    return frozenset(scope.project_ids | granted) if scope.doc_types else frozenset(granted)


def retrieve(conn: psycopg.Connection, user_id: str, query: str, embedder: Embedder, *, k: int = 8,
             audit: bool = True, project_filter: frozenset[str] | None = None,
             scope: AccessScope | None = None) -> RetrievalResult:
    """Top-k authorized chunks for ``query``.

    ``project_filter`` can only NARROW results (to those projects + company-wide documents); it is
    ANDed with the permission clause and never widens access.
    """
    query_vec = to_vector(embedder.embed([query])[0])
    with conn.transaction():
        scope = scope or load_scope(conn, user_id)
        _enter_app_role(conn, user_id)
        clause, params = scope.to_sql("c")
        if project_filter is not None:
            clause += " AND (c.project_id = ANY(%(project_filter)s) OR c.project_id IS NULL)"
            params["project_filter"] = sorted(project_filter)
        rows = conn.execute(
            f"""SELECT {_CHUNK_COLUMNS}, c.embedding <=> %(q)s::vector AS distance
                FROM chunks c
                WHERE {clause}
                ORDER BY c.embedding <=> %(q)s::vector
                LIMIT %(k)s""",
            {**params, "q": query_vec, "k": k},
        ).fetchall()
        chunks = _with_titles(conn, rows)
        # Iterative scans return results in relaxed order; restore exact order.
        chunks.sort(key=lambda c: c.distance)
        outcome = "answered" if chunks else "no_authorized_content"
        if audit:
            write_audit(conn, scope.company_id, user_id, query, [c.id for c in chunks], outcome)
    return RetrievalResult(chunks, outcome)


def fetch_chunk_for_user(conn: psycopg.Connection, user_id: str, chunk_id: int) -> RetrievedChunk | None:
    """Re-check a citation when it is opened (design decision 9). None if no longer readable."""
    with conn.transaction():
        scope = load_scope(conn, user_id)
        _enter_app_role(conn, user_id)
        clause, params = scope.to_sql("c")
        rows = conn.execute(
            f"SELECT {_CHUNK_COLUMNS}, 0.0 FROM chunks c WHERE c.id = %(chunk_id)s AND {clause}",
            {**params, "chunk_id": chunk_id},
        ).fetchall()
        chunks = _with_titles(conn, rows)
    return chunks[0] if chunks else None


def write_audit(conn: psycopg.Connection, company_id: str, user_id: str, query: str,
                retrieved_ids: list[int], outcome: str, *, cited_ids: list[int] | None = None,
                mentioned_projects: list[str] | None = None) -> None:
    conn.execute(
        """INSERT INTO audit_log (company_id, user_id, query, retrieved_chunk_ids, outcome,
                                  cited_chunk_ids, mentioned_projects)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (company_id, user_id, query, retrieved_ids, outcome, cited_ids or [], mentioned_projects or []),
    )


def _with_titles(conn: psycopg.Connection, rows) -> list[RetrievedChunk]:
    if not rows:
        return []
    titles = dict(conn.execute(
        "SELECT id, title FROM documents WHERE id = ANY(%s)", (list({r[2] for r in rows}),)
    ).fetchall())
    return [
        RetrievedChunk(r[0], r[1], r[2], r[3], titles.get(r[2], r[2]), r[4], r[5], float(r[6]))
        for r in rows
    ]


def _enter_app_role(conn: psycopg.Connection, user_id: str) -> None:
    """Switch this transaction to the RLS-restricted role. Reverts automatically at commit/rollback."""
    conn.execute("SET LOCAL ROLE xyz_app")
    conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
    conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
    conn.execute("SET LOCAL hnsw.ef_search = 100")
