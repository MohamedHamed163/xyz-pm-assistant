"""Permission engine: turns a user's permissions into an AccessScope.

An AccessScope is a small set of *rules* (not a list of document IDs — see design decision 6):

    company_id = :company AND status = 'ready' AND (
          ((:company_wide OR project_id = ANY(:projects)) AND doc_type = ANY(:doc_types)
                                                           AND visibility = ANY(:role_levels))
       OR (document_id = ANY(:granted_management))
       OR (document_id = ANY(:granted_team)          AND visibility IN ('client_shared', 'team'))
       OR (document_id = ANY(:granted_client_shared) AND visibility = 'client_shared')
    )
    [AND visibility = 'client_shared']   -- shared_only roles (clients), grants included

Section levels: client_shared < team < management. A role sees up to its ``max_visibility``;
each grant carries its own level; clients are always capped at client_shared.

The same scope is used two ways:
- ``AccessScope.allows(chunk)`` — in-memory check (tests, citation re-checks).
- ``AccessScope.to_sql()`` — the WHERE clause for the pgvector retrieval query.
Both must stay equivalent, and equivalent to the RLS function ``app_can_read``; tests cover all three.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

from .documents import CLIENT_SHARED, MANAGEMENT, TEAM

LEVELS = (CLIENT_SHARED, TEAM, MANAGEMENT)
RANK = {level: n for n, level in enumerate(LEVELS, start=1)}


def levels_up_to(level: str) -> tuple[str, ...]:
    return LEVELS[: RANK[level]]


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
    max_visibility: str = TEAM


@dataclass(frozen=True)
class Grant:
    user_id: str
    document_id: str
    expires_at: datetime | None = None
    max_visibility: str = TEAM

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
    max_visibility: str = TEAM
    grant_levels: frozenset[tuple[str, str]] = frozenset()   # (document_id, max_visibility)

    @classmethod
    def deny_all(cls, user: User) -> "AccessScope":
        return cls(user.id, user.company_id, False, frozenset(), frozenset(), frozenset(), True, CLIENT_SHARED)

    def _grant_level(self, document_id: str) -> str | None:
        levels = [lvl for doc, lvl in self.grant_levels if doc == document_id]
        if levels:
            return max(levels, key=RANK.__getitem__)
        return TEAM if document_id in self.granted_document_ids else None

    def allows(self, chunk: ChunkLike) -> bool:
        if chunk.company_id != self.company_id or chunk.status != "ready":
            return False
        rank = RANK.get(chunk.visibility)
        if rank is None:
            return False
        by_role = (
            chunk.doc_type in self.doc_types
            and (self.company_wide or (chunk.project_id is not None and chunk.project_id in self.project_ids))
            and rank <= RANK[self.max_visibility]
        )
        grant_level = self._grant_level(chunk.document_id)
        by_grant = grant_level is not None and rank <= RANK[grant_level]
        if not (by_role or by_grant):
            return False
        if self.shared_only and chunk.visibility != CLIENT_SHARED:
            return False
        return True

    def to_sql(self, table: str = "chunks") -> tuple[str, dict]:
        """Parameterized WHERE fragment (psycopg named-param style)."""
        t = table
        by_level = {level: sorted(d for d in self.granted_document_ids if self._grant_level(d) == level)
                    for level in LEVELS}
        clause = (
            f"{t}.company_id = %(company_id)s AND {t}.status = 'ready' AND ("
            f"((%(company_wide)s OR {t}.project_id = ANY(%(project_ids)s))"
            f" AND {t}.doc_type = ANY(%(doc_types)s) AND {t}.visibility = ANY(%(role_levels)s))"
            f" OR {t}.document_id = ANY(%(granted_management)s)"
            f" OR ({t}.document_id = ANY(%(granted_team)s) AND {t}.visibility IN ('{CLIENT_SHARED}', '{TEAM}'))"
            f" OR ({t}.document_id = ANY(%(granted_client_shared)s) AND {t}.visibility = '{CLIENT_SHARED}'))"
        )
        if self.shared_only:
            clause += f" AND {t}.visibility = '{CLIENT_SHARED}'"
        params = {
            "company_id": self.company_id,
            "company_wide": self.company_wide,
            "doc_types": sorted(self.doc_types),
            "project_ids": sorted(self.project_ids),
            "role_levels": list(levels_up_to(self.max_visibility)),
            "granted_document_ids": sorted(self.granted_document_ids),
            "granted_management": by_level[MANAGEMENT],
            "granted_team": by_level[TEAM],
            "granted_client_shared": by_level[CLIENT_SHARED],
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
    active = [g for g in grants if g.user_id == user.id and g.is_active(now)]
    return AccessScope(
        user_id=user.id,
        company_id=user.company_id,
        company_wide=policy.scope == "company",
        project_ids=user.projects,
        doc_types=policy.doc_types,
        granted_document_ids=frozenset(g.document_id for g in active),
        shared_only=policy.shared_only,
        max_visibility=CLIENT_SHARED if policy.shared_only else policy.max_visibility,
        grant_levels=frozenset((g.document_id, g.max_visibility) for g in active),
    )


def filter_chunks(scope: AccessScope, chunks: Iterable[ChunkLike]) -> list[ChunkLike]:
    return [c for c in chunks if scope.allows(c)]
