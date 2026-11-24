"""Permission engine: turns a user's permissions into an AccessScope.

An AccessScope is a small set of *rules* (not a list of document IDs — see design decision 6):

    company_id = :company AND status = 'ready' AND (
          (:company_wide AND doc_type = ANY(:doc_types))
       OR (project_id = ANY(:projects) AND doc_type = ANY(:doc_types))
       OR document_id = ANY(:granted_docs)
    )
    [AND visibility = 'client_shared']   -- shared_only roles (clients), grants included

The same scope is used two ways:
- ``AccessScope.allows(chunk)`` — in-memory check (tests, citation re-checks).
- ``AccessScope.to_sql()`` — the WHERE clause for the pgvector retrieval query.
Both must stay equivalent; tests cover both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

from .documents import CLIENT_SHARED


class ChunkLike(Protocol):
    document_id: str
    company_id: str
    project_id: str | None
    doc_type: str
    visibility: str
    status: str


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    company_id: str
    projects: frozenset[str]


@dataclass(frozen=True)
class RolePolicy:
    scope: str                    # "assigned" | "company"
    doc_types: frozenset[str]
    shared_only: bool = False


@dataclass(frozen=True)
class Grant:
    user_id: str
    document_id: str
    expires_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now


@dataclass(frozen=True)
class AccessScope:
    user_id: str
    company_id: str
    company_wide: bool
    project_ids: frozenset[str]
    doc_types: frozenset[str]
    granted_document_ids: frozenset[str]
    shared_only: bool

    @classmethod
    def deny_all(cls, user: User) -> "AccessScope":
        return cls(user.id, user.company_id, False, frozenset(), frozenset(), frozenset(), True)

    def allows(self, chunk: ChunkLike) -> bool:
        if chunk.company_id != self.company_id or chunk.status != "ready":
            return False
        by_role = chunk.doc_type in self.doc_types and (
            self.company_wide or (chunk.project_id is not None and chunk.project_id in self.project_ids)
        )
        by_grant = chunk.document_id in self.granted_document_ids
        if not (by_role or by_grant):
            return False
        if self.shared_only and chunk.visibility != CLIENT_SHARED:
            return False
        return True

    def to_sql(self, table: str = "chunks") -> tuple[str, dict]:
        """Parameterized WHERE fragment (psycopg named-param style)."""
        t = table
        clause = (
            f"{t}.company_id = %(company_id)s AND {t}.status = 'ready' AND ("
            f"(%(company_wide)s AND {t}.doc_type = ANY(%(doc_types)s))"
            f" OR ({t}.project_id = ANY(%(project_ids)s) AND {t}.doc_type = ANY(%(doc_types)s))"
            f" OR {t}.document_id = ANY(%(granted_document_ids)s))"
        )
        if self.shared_only:
            clause += f" AND {t}.visibility = '{CLIENT_SHARED}'"
        params = {
            "company_id": self.company_id,
            "company_wide": self.company_wide,
            "doc_types": sorted(self.doc_types),
            "project_ids": sorted(self.project_ids),
            "granted_document_ids": sorted(self.granted_document_ids),
        }
        return clause, params


def build_scope(
    user: User,
    role_policies: dict[str, RolePolicy],
    grants: Iterable[Grant],
    *,
    now: datetime | None = None,
) -> AccessScope:
    """Build the scope from the *current* permission records. Call on every request."""
    policy = role_policies.get(user.role)
    if policy is None:
        return AccessScope.deny_all(user)  # unknown role: fail closed
    now = now or datetime.now(timezone.utc)
    granted = frozenset(g.document_id for g in grants if g.user_id == user.id and g.is_active(now))
    return AccessScope(
        user_id=user.id,
        company_id=user.company_id,
        company_wide=policy.scope == "company",
        project_ids=user.projects,
        doc_types=policy.doc_types,
        granted_document_ids=granted,
        shared_only=policy.shared_only,
    )


def filter_chunks(scope: AccessScope, chunks: Iterable[ChunkLike]) -> list[ChunkLike]:
    return [c for c in chunks if scope.allows(c)]
