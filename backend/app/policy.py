"""Permission engine: turns a user's permissions into an AccessScope.

Access = project membership (the CEO reads every project) × the role's allowed TOPICS per document
type. A topic is addressed by its access key, ``"<doc_type>:<topic>"`` — e.g. ``brd:business_rules``.

    company_id = :company AND status = 'ready'
      AND (:company_wide OR project_id = ANY(:projects))
      AND access_key = ANY(:access_keys)

The rule stays tiny however many documents exist (at most a few dozen access keys).

The same scope is used two ways, and both must agree with the RLS function ``app_can_read``:
- ``AccessScope.allows(chunk)`` — in-memory check (tests, citation re-checks).
- ``AccessScope.to_sql()`` — the WHERE clause for the pgvector retrieval query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class ChunkLike(Protocol):
    document_id: str
    company_id: str
    project_id: str | None
    doc_type: str
    topic: str
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
    scope: str                       # "assigned" | "company"
    access_keys: frozenset[str]      # {"brd:goals", "prd:scope", …}


@dataclass(frozen=True)
class AccessScope:
    user_id: str
    company_id: str
    company_wide: bool
    project_ids: frozenset[str]
    access_keys: frozenset[str]

    @classmethod
    def deny_all(cls, user: User) -> "AccessScope":
        return cls(user.id, user.company_id, False, frozenset(), frozenset())

    def allows(self, chunk: ChunkLike) -> bool:
        return (
            chunk.company_id == self.company_id
            and chunk.status == "ready"
            and (self.company_wide or (chunk.project_id is not None and chunk.project_id in self.project_ids))
            and f"{chunk.doc_type}:{chunk.topic}" in self.access_keys
        )

    def topics_for(self, doc_type: str) -> list[str]:
        return sorted(k.split(":", 1)[1] for k in self.access_keys if k.startswith(f"{doc_type}:"))

    def to_sql(self, table: str = "chunks") -> tuple[str, dict]:
        """Parameterized WHERE fragment (psycopg named-param style)."""
        t = table
        clause = (
            f"{t}.company_id = %(company_id)s AND {t}.status = 'ready'"
            f" AND (%(company_wide)s OR {t}.project_id = ANY(%(project_ids)s))"
            f" AND {t}.access_key = ANY(%(access_keys)s)"
        )
        params = {
            "company_id": self.company_id,
            "company_wide": self.company_wide,
            "project_ids": sorted(self.project_ids),
            "access_keys": sorted(self.access_keys),
        }
        return clause, params


def build_scope(user: User, role_policies: dict[str, RolePolicy]) -> AccessScope:
    """Build the scope from the *current* permission records. Call on every request."""
    policy = role_policies.get(user.role)
    if policy is None:
        return AccessScope.deny_all(user)  # unknown role: fail closed
    return AccessScope(
        user_id=user.id,
        company_id=user.company_id,
        company_wide=policy.scope == "company",
        project_ids=user.projects,
        access_keys=policy.access_keys,
    )


def filter_chunks(scope: AccessScope, chunks: Iterable[ChunkLike]) -> list[ChunkLike]:
    return [c for c in chunks if scope.allows(c)]
